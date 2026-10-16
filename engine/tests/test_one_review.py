"""One review record (migration 0026): every way of judging work lands in `reviews`, and reads back in one list."""
import shutil

import psycopg
import pytest
from reviewing import object_to, report, reports  # noqa: F401
from test_knowledge_api import claim_of, merged_claim
from test_trust_db import PILOT, content, open_mr, world  # noqa: F401  (world is a fixture)

from rrsrch.ledger import db

pytestmark = pytest.mark.db


def test_every_kind_of_review_is_one_record_read_in_one_list(world):
    client, h, url = world
    cid = claim_of(url, merged_claim(client, h)[0])
    mr = open_mr(client, h["bot"], {"repository": PILOT, "content": content()})
    assert client.post("/v1/reviews", headers=h["ext"], json={"target": f"proposal:{mr}", "verdict": "request_changes",
                                                              "findings": "Cite the table."}).status_code == 200
    assert client.post("/v1/reviews", headers=h["ext"], json={"target": f"proposal:{mr}", "verdict": "approve",
                                                              "findings": "Fixed."}).status_code == 200   # revised
    assert object_to(client, h["ext"], cid,
                       **{"kind": "scope", "statement": "One centre.", "blocking": False}).status_code == 201
    for ctx, outcome in (("reproduction", "reproduced"), ("usage", "worked")):
        assert report(client, h["ext"], **{
            "target": f"claim:{cid}", "context": ctx, "outcome": outcome, "observations": "Same result."}).status_code == 201

    got = client.get("/v1/reviews", params={"target": f"proposal:{mr}"}).json()["items"]
    assert [(r["kind"], r["verdict"], r["findings"]) for r in got] == [("decision", "approve", "Fixed.")]
    got = client.get("/v1/reviews", params={"target": f"claim:{cid}"}).json()["items"]
    assert [(r["kind"], r["verdict"]) for r in got] == [("objection", "object"), ("reproduction", "reproduced"),
                                                        ("usage", "worked")]
    assert got[0]["details"]["objection"] == "scope" and got[0]["state"] == "open" and "legacy" not in got[0]["details"]
    assert [r["kind"] for r in client.get("/v1/reviews", params={"target": f"claim:{cid}",
                                                                  "kind": "usage"}).json()["items"]] == ["usage"]
    assert client.get("/v1/reviews", params={"target": "claim:99999"}).status_code == 404
    assert client.get("/v1/reviews", params={"target": "nonsense"}).status_code == 400

    # the old shapes still answer, from the one table
    claim = client.get(f"/v1/claims/{cid}").json()["claim"]
    assert [c["kind"] for c in claim["challenges"]] == ["scope"]
    reports_ = client.get(f"/v1/claims/{cid}/feedback").json()["formal"]["verification_reports"]
    assert reports_["summary"]["reproduction"]["reproduced"] == 1
    with psycopg.connect(url) as c:
        assert c.execute("SELECT count(*) FROM reviews").fetchone()[0] == 4 + 1      # + the merged claim's approval
        with pytest.raises(psycopg.errors.RaiseException):
            c.execute("UPDATE reviews SET findings = 'edited' WHERE kind = 'reproduction'")


ALL_MIGRATIONS = db.MIGRATIONS


def _upto(tmp_path, name: str, last: str):
    """A migrations directory holding the real migrations up to and including `last`."""
    d = tmp_path / name
    d.mkdir()
    for f in sorted(ALL_MIGRATIONS.glob("*.sql")):
        if f.name <= last:
            shutil.copy(f, d / f.name)
    return d


def test_the_migration_moves_existing_reviews_and_repoints_what_pointed_at_them(db_url, tmp_path, monkeypatch):
    before = _upto(tmp_path, "before", "0025_bounties.sql")
    real = db.MIGRATIONS
    monkeypatch.setattr(db, "MIGRATIONS", before)
    with psycopg.connect(db_url) as c:
        db.migrate(c)
        c.execute("INSERT INTO sources (id, title, has_full_text, snapshot_sha256) VALUES ('S:1', 't', false, 'x')")
        doc = c.execute("INSERT INTO documents (source_id, part, text, sha256) VALUES ('S:1', 'abstract', 'abc def', "
                        "repeat('a', 64)) RETURNING id").fetchone()[0]
        repo = c.execute("SELECT id FROM repositories WHERE slug = 'rrsrch/msc-knee-oa'").fetchone()[0]
        agent = c.execute("SELECT id FROM agents LIMIT 1").fetchone()[0]
        claim = c.execute("INSERT INTO claims (document_id, doc_sha256, span_start, span_end, text, extractor, "
                          "repository_id, type, state, agent_id) VALUES (%s, repeat('a', 64), 0, 3, 'abc', 'r', %s, "
                          "'empirical', 'supported', %s) RETURNING id", (doc, repo, agent)).fetchone()[0]
        ch = c.execute("INSERT INTO challenges (claim_id, author_id, kind, statement, blocking) VALUES "
                       "(%s, %s, 'scope', 'one centre', true) RETURNING id", (claim, agent)).fetchone()[0]
        c.execute("INSERT INTO discussions (repository_id, subject, title, author_id) VALUES (%s, %s, 't', %s)",
                  (repo, f"challenge:{ch}", agent))
        c.execute("INSERT INTO verification_reports (target, repository_id, author_id, context, outcome, observations, "
                  "content_hash) VALUES (%s, %s, %s, 'reproduction', 'reproduced', 'ok', 'h')",
                  (f"claim:{claim}", repo, agent))
    monkeypatch.setattr(db, "MIGRATIONS", _upto(tmp_path, "step2", "0026_one_review_record.sql"))
    with psycopg.connect(db_url) as c:
        assert db.migrate(c) == ["0026_one_review_record.sql"]
        rows = c.execute("SELECT kind, verdict, findings, details->>'legacy' FROM reviews ORDER BY id").fetchall()
        assert rows == [("objection", "object", "one centre", f"challenge:{ch}"),
                        ("reproduction", "reproduced", "ok", rows[1][3])]
        new = c.execute("SELECT id FROM reviews WHERE kind = 'objection'").fetchone()[0]
        assert c.execute("SELECT subject FROM discussions").fetchone()[0] == f"challenge:{new}"
        assert c.execute("SELECT kind, blocking, state FROM challenges").fetchone() == ("scope", True, "open")
        assert c.execute("SELECT outcome FROM verification_reports").fetchone()[0] == "reproduced"
        assert c.execute("SELECT count(*) FROM retired_challenges").fetchone()[0] == 1           # kept until step 3
    monkeypatch.setattr(db, "MIGRATIONS", real)
    with psycopg.connect(db_url) as c:                                     # step 3: the reviews stay, the rest goes
        db.migrate(c)
        assert c.execute("SELECT count(*) FROM reviews").fetchone()[0] == 2
        gone = ["challenges", "verification_reports", "claim_reviews", "retired_challenges", "retired_reactions"]
        assert [c.execute("SELECT to_regclass(%s)", (t,)).fetchone()[0] for t in gone] == [None] * len(gone)


def test_observations_and_proposals_become_findings_and_reactions_retire(db_url, tmp_path, monkeypatch):
    before = _upto(tmp_path, "before28", "0027_questions_not_tasks.sql")
    real = db.MIGRATIONS
    monkeypatch.setattr(db, "MIGRATIONS", before)
    with psycopg.connect(db_url) as c:
        db.migrate(c)
        net = c.execute("SELECT id FROM repositories WHERE slug = 'rrsrch/network'").fetchone()[0]
        agent = c.execute("SELECT id FROM agents LIMIT 1").fetchone()[0]
        for kind in ("observation", "proposal", "question"):
            c.execute("INSERT INTO research_posts (repository_id, author_id, kind, title, body, content_hash) "
                      "VALUES (%s, %s, %s, %s, 'b', repeat('0', 64))", (net, agent, kind, kind))
    monkeypatch.setattr(db, "MIGRATIONS", _upto(tmp_path, "upto28", "0028_findings_and_threads.sql"))
    with psycopg.connect(db_url) as c:
        db.migrate(c)
        assert dict(c.execute("SELECT title, kind FROM research_posts")) == {
            "observation": "finding", "proposal": "finding", "question": "question"}
        assert c.execute("SELECT to_regclass('reactions'), to_regclass('retired_reactions') IS NOT NULL").fetchone() \
            == (None, True)
