"""The trust engine end to end over HTTP against a real Postgres: propose, review, merge, revise, audit."""
import hashlib

import psycopg
import pytest
from fastapi.testclient import TestClient

from rrsrch.identity import store as ids
from rrsrch.ledger import db
from rrsrch.serve import api
from rrsrch.trust import audit

pytestmark = pytest.mark.db

TITLE = "Bone marrow MSCs versus hyaluronic acid for knee osteoarthritis"
TEXT = ("Methods: 40 patients were randomised. Results: At 12 months, WOMAC scores improved more with MSCs "
        "than with hyaluronic acid (p = 0.01), while VAS pain did not differ (p = 0.41).")
SHA = hashlib.sha256(TEXT.encode()).hexdigest()
QUOTE = "At 12 months, WOMAC scores improved more with MSCs than with hyaluronic acid (p = 0.01)"
PILOT = "rrsrch/msc-knee-oa"


def content(proposition="At 12 months, WOMAC improved more with MSCs than hyaluronic acid (p = 0.01).", parent=None):
    s = TEXT.index(QUOTE)
    c = {"repository": PILOT, "type": "empirical", "proposition": proposition,
         "evidence": [["supports", {"source_id": "MED:1", "doc_sha256": SHA, "start": s, "end": s + len(QUOTE)}]]}
    return c | ({"parent_hash": parent} if parent else {})


@pytest.fixture
def world(db_url):
    """The pilot with one study, a contributor bot, an rrsrch admin and an outside human reviewer."""
    hdr = {}
    with psycopg.connect(db_url) as c:
        db.migrate(c)
        c.execute("INSERT INTO sources (id, title, has_full_text, snapshot_sha256, pub_types) "
                  "VALUES ('MED:1', %s, false, 'x', '{Randomized Controlled Trial}')", (TITLE,))
        c.execute("INSERT INTO documents (source_id, part, text, sha256) VALUES ('MED:1', 'abstract', %s, %s)",
                  (TEXT, SHA))
        ids.create_organization(c, "lab", "An outside lab")
        c.execute("UPDATE organizations SET verification = 'verified' WHERE id = 'lab'")   # a vetted outside operator
        repo = ids.get_repo(c, PILOT)
        for handle, org, kind, org_role, role in [("bot", "rrsrch", "service", "member", "contributor"),
                                                  ("admin", "rrsrch", "human", "admin", None),
                                                  ("ext", "lab", "human", "member", "reviewer")]:
            a = ids.register_agent(c, org, handle, kind, org_role=org_role)
            if role:
                ids.set_member(c, repo.id, a["id"], role, granted_by=None)
            tok, _, _ = ids.issue_key(c, a["id"], {"read", "propose", "review", "maintain", "administer", "agents"})
            hdr[handle] = {"Authorization": f"Bearer {tok}"}
    return TestClient(api.create_app(connect=lambda: psycopg.connect(db_url))), hdr, db_url


def open_mr(client, who, body):
    r = client.post("/v1/merge-requests", headers=who, json=body)
    assert r.status_code == 201, r.json()
    return r.json()["merge_request_id"]


def test_a_claim_is_proposed_reviewed_and_merged(world):
    client, h, url = world
    mr = open_mr(client, h["bot"], {"repository": PILOT, "content": content()})

    r = client.post(f"/v1/merge-requests/{mr}/merge", headers=h["admin"])
    assert r.status_code == 409 and any("approval" in x for x in r.json()["reasons"])
    assert client.post("/v1/reviews", headers=h["bot"],
                       json={"target": f"proposal:{mr}", "verdict": "approve"}).status_code == 403                 # authors don't review
    assert client.post(f"/v1/merge-requests/{mr}/merge", headers=h["bot"]).status_code == 403   # contributors don't merge

    assert client.post("/v1/reviews", headers=h["ext"],
                       json={"target": f"proposal:{mr}", "verdict": "approve", "findings": "span matches"}).status_code == 200
    preview = client.get(f"/v1/merge-requests/{mr}").json()["merge_preview"]
    assert preview["allowed"] is False and preview["reasons"] == ["merger: authentication required"]
    r = client.post(f"/v1/merge-requests/{mr}/merge", headers=h["admin"])
    assert r.status_code == 200, r.json()

    with psycopg.connect(url) as c:
        state, version, rel = c.execute(
            "SELECT c.state, r.version, l.relation FROM claims c JOIN claim_revisions r ON r.claim_id = c.id "
            "JOIN evidence_links l ON l.claim_id = c.id WHERE r.id = %s", (r.json()["revision_id"],)).fetchone()
        assert (state, version, rel) == ("supported", 1, "supports")
        actions = [a for (a,) in c.execute("SELECT action FROM audit_events ORDER BY id")]
        assert actions == ["merge_request.open", "merge.refused", "review.approve", "merge_request.merge"]
        assert audit.verify(c) == []
    assert client.get(f"/v1/merge-requests/{mr}").json()["merge_request"]["state"] == "merged"
    assert client.post(f"/v1/merge-requests/{mr}/merge", headers=h["admin"]).status_code == 409


def test_concurrent_revisions_of_one_head_cannot_both_merge(world):
    client, h, url = world
    mr = open_mr(client, h["bot"], {"repository": PILOT, "content": content()})
    client.post("/v1/reviews", headers=h["ext"], json={"target": f"proposal:{mr}", "verdict": "approve"})
    rev = client.post(f"/v1/merge-requests/{mr}/merge", headers=h["admin"]).json()["revision_id"]
    with psycopg.connect(url) as c:
        claim_id, head = c.execute("SELECT claim_id, content_hash FROM claim_revisions WHERE id = %s", (rev,)).fetchone()

    wording = ["At 12 months, WOMAC scores improved more with MSCs than hyaluronic acid (p = 0.01).",
               "WOMAC improved more with MSCs than with hyaluronic acid at 12 months (p = 0.01)."]
    a, b = (open_mr(client, h["bot"], {"repository": PILOT, "claim_id": claim_id,
                                       "content": content(w, parent=head)}) for w in wording)
    for m in (a, b):
        client.post("/v1/reviews", headers=h["ext"], json={"target": f"proposal:{m}", "verdict": "approve"})
    assert client.post(f"/v1/merge-requests/{a}/merge", headers=h["admin"]).status_code == 200
    r = client.post(f"/v1/merge-requests/{b}/merge", headers=h["admin"])
    assert r.status_code == 409 and any("parent_is_head" in x for x in r.json()["reasons"])
    with psycopg.connect(url) as c:
        assert c.execute("SELECT max(version), count(*) FROM claim_revisions WHERE claim_id = %s",
                         (claim_id,)).fetchone() == (2, 2)


def test_bad_proposals_and_objections(world):
    client, h, _ = world
    r = client.post("/v1/merge-requests", headers=h["bot"], json={"repository": PILOT, "content": {"type": "x"}})
    assert r.status_code == 400 and r.json()["ok"] is False
    assert client.post("/v1/merge-requests", json={"repository": PILOT, "content": content()}).status_code == 401
    assert client.post("/v1/merge-requests", headers=h["ext"],
                       json={"repository": "nope/none", "content": content()}).status_code == 404

    invented = open_mr(client, h["bot"], {"repository": PILOT, "content": content(
        "At 24 months, WOMAC improved more with MSCs (p = 0.01).")})
    got = client.get(f"/v1/merge-requests/{invented}", headers=h["admin"]).json()
    assert {c["name"] for c in got["checks"] if not c["passed"]} == {"evidence_gate:numbers"}

    mr = open_mr(client, h["bot"], {"repository": PILOT, "content": content()})
    client.post("/v1/reviews", headers=h["ext"], json={"target": f"proposal:{mr}", "verdict": "reject"})
    r = client.post(f"/v1/merge-requests/{mr}/merge", headers=h["admin"])
    assert r.status_code == 409 and any("says reject" in x for x in r.json()["reasons"])
    assert client.post(f"/v1/merge-requests/{mr}/close", headers=h["ext"],
                       json={"state": "withdrawn"}).status_code == 403
    assert client.post(f"/v1/merge-requests/{mr}/close", headers=h["bot"], json={"state": "withdrawn"}).status_code == 200
    assert client.post(f"/v1/merge-requests/{mr}/merge", headers=h["admin"]).status_code == 409


def test_audit_chain_is_append_only_and_tamper_evident(world):
    client, h, url = world
    open_mr(client, h["bot"], {"repository": PILOT, "content": content()})
    assert client.post("/v1/agents", headers=h["admin"], json={"handle": "bot-2", "kind": "service"}).status_code == 201
    events = client.get("/v1/repos/rrsrch/msc-knee-oa/events").json()["events"]
    assert [e["action"] for e in events] == ["merge_request.open"] and events[0]["actor"] == "bot"
    with psycopg.connect(url) as c:
        assert [a for (a,) in c.execute("SELECT action FROM audit_events ORDER BY id")] == \
            ["merge_request.open", "agent.register"]
        with pytest.raises(psycopg.errors.RaiseException):
            c.execute("UPDATE audit_events SET action = 'x'")
    with psycopg.connect(url) as c:
        with pytest.raises(psycopg.errors.RaiseException):
            c.execute("DELETE FROM audit_events")
    with psycopg.connect(url) as c:           # as the table owner could: switch the guard off and edit
        c.execute("ALTER TABLE audit_events DISABLE TRIGGER audit_events_no_update")
        c.execute("UPDATE audit_events SET detail = '{\"forged\": true}' WHERE id = (SELECT min(id) FROM audit_events)")
        problems = audit.verify(c)
    assert len(problems) == 1 and "does not match its hash" in problems[0]


def test_policies_are_versioned_not_edited(world):
    _, _, url = world
    with psycopg.connect(url) as c:
        with pytest.raises(psycopg.errors.RaiseException):
            c.execute("UPDATE policies SET rules = '{}'")
    with psycopg.connect(url) as c:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            c.execute("UPDATE repositories SET policy_version = 'msc-v2'")
            c.commit()
