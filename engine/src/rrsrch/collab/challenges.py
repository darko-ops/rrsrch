"""Challenges: structured objections to a claim (SPEC-v2 §8.2, §10.4).

A blocking challenge makes a supported claim contested, and while it is open
no revision of the claim can merge. A maintainer other than the challenger
resolves it: dismissed (the objection doesn't hold) returns the claim to
supported if nothing else holds it; upheld (it does) leaves the claim
contested until a revision that addresses it is merged.
"""
from __future__ import annotations

import json

import psycopg

from ..identity.access import Action, Principal
from ..knowledge import states
from ..knowledge.models import Span
from ..trust import audit
from ..trust.merge import Refused, require
from .common import rate_limit

KINDS = ("contradiction", "missing_assumption", "evidence_problem", "scope", "other")


def _claim(conn, claim_id: int, lock: bool = False) -> tuple[int, str]:
    row = conn.execute("SELECT repository_id, state FROM claims WHERE id = %s" + (" FOR UPDATE" if lock else ""),
                       (claim_id,)).fetchone()
    if row is None:
        raise Refused(404, "not found")
    return row


def _set_state(conn, claim_id: int, current: str, to: str) -> None:
    conn.execute("UPDATE claims SET state = %s WHERE id = %s", (states.check(current, to).value, claim_id))


def open_challenge(conn: psycopg.Connection, p: Principal | None, claim_id: int, kind: str, statement: str,
                   evidence: list[dict], blocking: bool) -> int:
    repo_id, state = _claim(conn, claim_id, lock=True)
    require(conn, p, Action.PROPOSE, repo_id)
    if kind not in KINDS:
        raise Refused(400, f"kind must be one of {', '.join(KINDS)}")
    try:
        spans = [Span.model_validate(e).model_dump() for e in evidence]
    except ValueError as e:
        raise Refused(400, f"evidence: {e}") from e
    rate_limit(conn, "SELECT count(*) FROM reviews WHERE reviewer_id = %s AND claim_id = %s AND kind = 'objection' AND claim_id IS NOT NULL "
                     "AND state = 'open'",
               (p.agent_id, claim_id), 3, "open challenges from you on this claim")
    head = conn.execute("SELECT id FROM claim_revisions WHERE claim_id = %s ORDER BY version DESC LIMIT 1",
                        (claim_id,)).fetchone()
    cid = conn.execute(    # one review record (0026): an objection, open until resolved
        "INSERT INTO reviews (target, repository_id, reviewer_id, kind, verdict, findings, details, blocking, state, "
        "revision_id) VALUES (%s, %s, %s, 'objection', 'object', %s, %s, %s, 'open', %s) RETURNING id",
        (f"claim:{claim_id}", repo_id, p.agent_id, statement, json.dumps({"objection": kind, "evidence": spans}),
         blocking, head[0] if head else None)).fetchone()[0]
    author = conn.execute("SELECT a.handle FROM claims c JOIN agents a ON a.id = c.agent_id WHERE c.id = %s",
                          (claim_id,)).fetchone()[0]
    contested = blocking and state == "supported"
    if contested:
        _set_state(conn, claim_id, state, "contested")
    audit.append(conn, "challenge.open", f"claim:{claim_id}", actor_id=p.agent_id, repository_id=repo_id,
                 detail={"challenge_id": cid, "claim_id": claim_id, "kind": kind, "blocking": blocking,
                         "claim_state": "contested" if contested else state,
                         "notify": [author] if author != p.handle else []})
    return cid


def _load(conn, challenge_id: int) -> dict:
    row = conn.execute("SELECT id, claim_id, reviewer_id, blocking, state FROM reviews WHERE id = %s "
                       "AND kind = 'objection' AND claim_id IS NOT NULL FOR UPDATE", (challenge_id,)).fetchone()
    if row is None:
        raise Refused(404, "not found")
    return dict(zip(("id", "claim_id", "author_id", "blocking", "state"), row))


def _close(conn, p: Principal, ch: dict, outcome: str, resolution: str | None) -> str:
    repo_id, state = _claim(conn, ch["claim_id"], lock=True)
    conn.execute("UPDATE reviews SET state = %s, resolution = %s, resolved_by = %s, resolved_at = now() "
                 "WHERE id = %s", (outcome, resolution, p.agent_id, ch["id"]))
    # a contested claim goes back to supported once nothing holds it: no open blocking challenge, and no
    # upheld one still waiting for a revision that addresses it
    held = conn.execute(
        "SELECT count(*) FROM reviews c WHERE c.claim_id = %s AND c.kind = 'objection' AND c.blocking "
        "AND (c.state = 'open' OR "
        "(c.state = 'upheld' AND c.resolved_at > coalesce((SELECT max(created_at) FROM claim_revisions "
        "WHERE claim_id = c.claim_id), '-infinity')))", (ch["claim_id"],)).fetchone()[0]
    if state == "contested" and not held:
        _set_state(conn, ch["claim_id"], state, "supported")
        state = "supported"
    audit.append(conn, f"challenge.{outcome}", f"claim:{ch['claim_id']}", actor_id=p.agent_id,
                 repository_id=repo_id,
                 detail={"challenge_id": ch["id"], "claim_id": ch["claim_id"], "claim_state": state})
    return state


def resolve(conn: psycopg.Connection, p: Principal | None, challenge_id: int, outcome: str, resolution: str) -> str:
    """Uphold or dismiss; returns the claim's state afterwards."""
    ch = _load(conn, challenge_id)
    repo_id, _ = _claim(conn, ch["claim_id"])
    require(conn, p, Action.MAINTAIN, repo_id)
    if outcome not in ("upheld", "dismissed"):
        raise Refused(400, "outcome must be upheld or dismissed")
    if ch["state"] != "open":
        raise Refused(409, f"challenge is {ch['state']}")
    if p.agent_id == ch["author_id"]:
        raise Refused(403, "a challenge is resolved by someone other than its author")
    return _close(conn, p, ch, outcome, resolution)


def withdraw(conn: psycopg.Connection, p: Principal | None, challenge_id: int) -> str:
    ch = _load(conn, challenge_id)
    if p is None or p.agent_id != ch["author_id"]:
        raise Refused(403, "only the challenger can withdraw a challenge")
    if ch["state"] != "open":
        raise Refused(409, f"challenge is {ch['state']}")
    return _close(conn, p, ch, "withdrawn", None)


def list_for_claim(conn: psycopg.Connection, claim_id: int) -> list[dict]:
    cols = ("id", "author", "author_kind", "kind", "statement", "evidence", "blocking", "state", "resolution",
            "resolved_by", "created_at", "resolved_at", "revision")
    return [dict(zip(cols, r)) for r in conn.execute(
        "SELECT c.id, a.handle, a.kind, c.details->>'objection', c.findings, coalesce(c.details->'evidence', '[]'), "
        "c.blocking, c.state, c.resolution, r.handle, c.created_at, c.resolved_at, "
        "(SELECT version FROM claim_revisions WHERE id = c.revision_id) "
        "FROM reviews c JOIN agents a ON a.id = c.reviewer_id LEFT JOIN agents r ON r.id = c.resolved_by "
        "WHERE c.claim_id = %s AND c.kind = 'objection' ORDER BY c.id", (claim_id,))]
