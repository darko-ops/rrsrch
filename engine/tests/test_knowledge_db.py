"""Knowledge records against a real Postgres: the pilot repository, revisions, evidence, states."""
import json

import psycopg
import pytest

from rrsrch.knowledge import canonical, states, store
from rrsrch.knowledge.models import ClaimContent
from rrsrch.ledger import db

pytestmark = pytest.mark.db


def add_claim(conn, text="n=40", start=None):
    doc_id, sha, body = conn.execute(
        "SELECT id, sha256, text FROM documents WHERE part = 'abstract'").fetchone()
    s = body.index(text) if start is None else start
    return conn.execute(
        "INSERT INTO claims (document_id, doc_sha256, span_start, span_end, text, extractor, self_check, "
        "repository_id, type, state, agent_id) VALUES (%s, %s, %s, %s, %s, 'test', %s, "
        "(SELECT id FROM repositories WHERE slug = %s), 'empirical', 'structurally_valid', "
        "(SELECT id FROM agents WHERE handle = %s)) RETURNING id",
        (doc_id, sha, s, s + len(text), f"The trial enrolled {text}.",
         json.dumps({"passed": True, "rule": "pass", "detail": "", "log": []}),
         store.PILOT_REPO, store.READER_AGENT)).fetchone()[0]


@pytest.fixture
def ledger(conn, corpus_dir):
    db.migrate(conn)
    db.load_corpus(conn, corpus_dir)
    return conn


def test_migration_seeds_the_pilot(ledger):
    slug, org, vis = ledger.execute("SELECT slug, organization_id, visibility FROM repositories ORDER BY id LIMIT 1").fetchone()
    assert (slug, org, vis) == ("rrsrch/msc-knee-oa", "rrsrch", "public")
    assert ledger.execute("SELECT handle, kind FROM agents").fetchone() == ("rrsrch-reader", "service")


def test_sync_records_each_claim_once(ledger):
    cid = add_claim(ledger)
    lock = {(store.snapshot.record_dir("MED:1") / "record.json").as_posix(): {"fetched_at": "2026-10-12T22:21:29+00:00"}}
    assert store.sync(ledger, lock) == 1
    assert store.sync(ledger, lock) == 0

    version, parent, content, digest = ledger.execute(
        "SELECT version, parent_id, content, content_hash FROM claim_revisions WHERE claim_id = %s",
        (cid,)).fetchone()
    assert (version, parent) == (1, None)
    assert canonical.digest(content) == digest                      # stored content is what was hashed
    assert ClaimContent.model_validate(content).content_hash() == digest

    excerpt, primary, retrieved = ledger.execute(
        "SELECT e.excerpt, e.is_primary, e.retrieved_at FROM evidence e "
        "JOIN evidence_links l ON l.evidence_id = e.id WHERE l.claim_id = %s AND l.relation = 'supports'",
        (cid,)).fetchone()
    assert excerpt == "n=40" and primary is True and retrieved is not None

    checks, passed, policy = ledger.execute(
        "SELECT v.checks, v.passed, v.policy_version FROM verification_runs v "
        "JOIN claim_revisions r ON r.id = v.claim_revision_id WHERE r.claim_id = %s", (cid,)).fetchone()
    assert passed is True and policy == "msc-v1"
    assert [c["kind"] for c in checks] == ["structural", "integrity", "source"]


def test_claims_sharing_a_passage_share_its_evidence(ledger):
    a, b = add_claim(ledger), add_claim(ledger)
    store.sync(ledger)
    assert ledger.execute("SELECT count(*) FROM evidence").fetchone()[0] == 1
    assert ledger.execute("SELECT count(DISTINCT claim_id) FROM evidence_links").fetchone()[0] == 2
    assert {a, b} == {r[0] for r in ledger.execute("SELECT claim_id FROM claim_revisions")}


def test_revisions_cannot_be_rewritten(ledger):
    add_claim(ledger)
    store.sync(ledger)
    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        ledger.execute("UPDATE claim_revisions SET content_hash = %s", ("0" * 64,))


def test_state_moves_are_checked(ledger):
    cid = add_claim(ledger)
    ledger.commit()
    assert store.transition(ledger, cid, "under_review") is states.ClaimState.UNDER_REVIEW
    with pytest.raises(states.IllegalTransition):
        store.transition(ledger, cid, "draft")
    assert ledger.execute("SELECT state FROM claims WHERE id = %s", (cid,)).fetchone()[0] == "under_review"
    with pytest.raises(psycopg.errors.CheckViolation):
        ledger.execute("UPDATE claims SET state = 'true' WHERE id = %s", (cid,))
