"""Knowledge records in Postgres: revisions, evidence and verification runs for ledger claims.

Every claim gets a version-1 revision whose content hash covers what it says
and the exact span it rests on, an evidence row for that span, and a
verification run recording the checks it passed on the way in. `sync` fills
these in for claims that don't have them yet (claims from before migration
0006); the reader calls `record_claim` for each claim as it stores it.
"""
from __future__ import annotations

import json

import psycopg

from ..corpus import snapshot
from . import states
from .models import Check, CheckKind, ClaimContent, ClaimType, Relation, Span, VerificationRun

PILOT_REPO = "rrsrch/msc-knee-oa"
READER_AGENT = "rrsrch-reader"

# Europe PMC publication types that make a source derivative rather than primary
_DERIVATIVE = ("review", "meta-analysis")


def is_primary(pub_types: list[str]) -> bool:
    return not any(d in t.lower() for t in pub_types for d in _DERIVATIVE)


def _retrieved_at(lock: dict | None, source_id: str, part: str) -> str | None:
    if not lock:
        return None
    name = "fulltext.xml" if part == "fulltext" else "record.json"
    entry = lock.get((snapshot.record_dir(source_id) / name).as_posix())
    return entry["fetched_at"] if entry else None


def link_evidence(conn: psycopg.Connection, claim_id: int, relation: Relation, span: Span,
                  lock: dict | None = None) -> int:
    """Link a claim to the evidence row for a span of a stored document, creating the row if needed."""
    row = conn.execute(
        "SELECT d.id, d.part, d.text, s.pub_types, s.license FROM documents d JOIN sources s ON s.id = d.source_id "
        "WHERE d.source_id = %s AND d.sha256 = %s", (span.source_id, span.doc_sha256)).fetchone()
    if row is None:
        raise LookupError(f"no document {span.source_id}@{span.doc_sha256}")
    doc_id, part, doc_text, pub_types, license_ = row
    ev = conn.execute(
        "INSERT INTO evidence (kind, source_id, document_id, doc_sha256, span_start, span_end, excerpt, "
        "is_primary, license, retrieved_at) VALUES ('document_span', %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (document_id, doc_sha256, span_start, span_end) DO NOTHING RETURNING id",
        (span.source_id, doc_id, span.doc_sha256, span.start, span.end, doc_text[span.start:span.end],
         is_primary(pub_types), license_, _retrieved_at(lock, span.source_id, part))).fetchone()
    ev_id = ev[0] if ev else conn.execute(
        "SELECT id FROM evidence WHERE document_id = %s AND doc_sha256 = %s AND span_start = %s "
        "AND span_end = %s", (doc_id, span.doc_sha256, span.start, span.end)).fetchone()[0]
    conn.execute("INSERT INTO evidence_links (claim_id, evidence_id, relation) VALUES (%s, %s, %s) "
                 "ON CONFLICT DO NOTHING", (claim_id, ev_id, relation.value))
    return ev_id


def record_claim(conn: psycopg.Connection, claim_id: int, lock: dict | None = None) -> bool:
    """Give a claim its revision, evidence and verification run. False if it already has them."""
    if conn.execute("SELECT 1 FROM claim_revisions WHERE claim_id = %s", (claim_id,)).fetchone():
        return False
    row = conn.execute(
        "SELECT c.text, c.type, c.scope, c.fields, c.doc_sha256, c.span_start, c.span_end, c.self_check, "
        "  c.agent_id, d.id, d.part, d.text, d.sha256, s.id, s.pub_types, s.license, "
        "  r.slug, r.policy_version "
        "FROM claims c JOIN documents d ON d.id = c.document_id JOIN sources s ON s.id = d.source_id "
        "JOIN repositories r ON r.id = c.repository_id WHERE c.id = %s", (claim_id,)).fetchone()
    if row is None:
        raise LookupError(f"claim {claim_id} not found")
    (text, ctype, scope, fields, doc_sha, start, end, self_check, agent_id,
     doc_id, part, doc_text, cur_sha, source_id, pub_types, license_, slug, policy) = row

    span = Span(source_id=source_id, doc_sha256=doc_sha, start=start, end=end)
    content = ClaimContent(repository=slug, type=ClaimType(ctype), proposition=text, scope=scope,
                           fields=fields, evidence=((Relation.SUPPORTS, span),))
    digest = content.content_hash()

    link_evidence(conn, claim_id, Relation.SUPPORTS, span, lock)

    rev_id = conn.execute(
        "INSERT INTO claim_revisions (claim_id, version, content, content_hash, agent_id) "
        "VALUES (%s, 1, %s, %s, %s) RETURNING id",
        (claim_id, json.dumps(content.canonical()), digest, agent_id)).fetchone()[0]

    gate = self_check or {}
    run = VerificationRun(claim_revision_id=rev_id, policy_version=policy, checks=(
        Check(kind=CheckKind.STRUCTURAL, name="schema", passed=True),
        Check(kind=CheckKind.INTEGRITY, name="span_hash", passed=doc_sha == cur_sha,
              detail="" if doc_sha == cur_sha else f"document is now {cur_sha}"),
        Check(kind=CheckKind.SOURCE, name="self_check", passed=bool(gate.get("passed")),
              detail=gate.get("detail") or ("" if gate else "no self-check recorded")),
    ))
    conn.execute("INSERT INTO verification_runs (claim_revision_id, policy_version, checks, passed) "
                 "VALUES (%s, %s, %s, %s)",
                 (rev_id, run.policy_version, json.dumps([c.model_dump(mode="json") for c in run.checks]),
                  run.passed))
    return True


def sync(conn: psycopg.Connection, lock: dict | None = None) -> int:
    """Record every claim that has no revision yet. Returns how many were recorded."""
    with conn.transaction():
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM claims c WHERE NOT EXISTS "
            "(SELECT 1 FROM claim_revisions r WHERE r.claim_id = c.id) ORDER BY id")]
        for cid in ids:
            record_claim(conn, cid, lock)
    return len(ids)


def transition(conn: psycopg.Connection, claim_id: int, to: states.ClaimState | str) -> states.ClaimState:
    """Move a claim to a new review state, refusing moves the state machine doesn't allow."""
    with conn.transaction():
        row = conn.execute("SELECT state FROM claims WHERE id = %s FOR UPDATE", (claim_id,)).fetchone()
        if row is None:
            raise LookupError(f"claim {claim_id} not found")
        nxt = states.check(row[0], to)
        conn.execute("UPDATE claims SET state = %s WHERE id = %s", (nxt.value, claim_id))
    return nxt
