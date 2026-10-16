"""Reviewing claims already in a repository: unreviewed -> under review -> supported (or rejected)."""
import psycopg
import pytest
from reviewing import object_to, report, reports  # noqa: F401
from test_trust_db import PILOT, QUOTE, SHA, TEXT, world  # noqa: F401  (world is a fixture)

from rrsrch.identity import store as ids
from rrsrch.knowledge import store as kstore

pytestmark = pytest.mark.db


def reader_claim(url, author="rrsrch-reader", text=QUOTE):
    """A claim as the reader stores it: structurally valid, never reviewed."""
    with psycopg.connect(url) as c:
        s = TEXT.index(QUOTE)
        cid = c.execute(
            "INSERT INTO claims (document_id, doc_sha256, span_start, span_end, text, extractor, repository_id, type, "
            "state, agent_id) VALUES ((SELECT id FROM documents LIMIT 1), %s, %s, %s, %s, 'reader', "
            "(SELECT id FROM repositories WHERE slug = %s), 'empirical', 'structurally_valid', "
            "(SELECT id FROM agents WHERE handle = %s)) RETURNING id",
            (SHA, s, s + len(QUOTE), text, PILOT, author)).fetchone()[0]
        kstore.record_claim(c, cid)
    return cid


def review(client, who, cid, verdict, findings=""):
    return client.post("/v1/reviews", headers=who, json={"target": f"claim:{cid}", "verdict": verdict, "findings": findings})


def state_of(url, cid):
    with psycopg.connect(url) as c:
        return c.execute("SELECT state FROM claims WHERE id = %s", (cid,)).fetchone()[0]


def test_the_queue_shows_each_claim_with_its_passage_in_context(world):
    client, h, url = world
    cid = reader_claim(url)
    q = client.get(f"/v1/repos/{PILOT}/review-queue").json()               # public repository: anyone can read it
    item = next(i for i in q["items"] if i["id"] == cid)
    assert q["waiting"] >= 1 and item["passage"]["excerpt"] == QUOTE
    assert item["passage"]["before"].endswith("Results: ") and item["passage"]["after"].startswith(", while VAS")
    assert item["contributor"] == "rrsrch-reader" and item["reviews"] == []


def test_one_independent_human_approval_makes_a_claim_supported(world):
    client, h, url = world
    cid = reader_claim(url)
    assert review(client, h["bot"], cid, "approve").status_code == 403      # contributors don't review
    r = review(client, h["ext"], cid, "approve", "matches the passage")
    assert r.status_code == 200 and r.json()["state"] == "supported" and r.json()["reasons"] == []
    assert review(client, h["ext"], cid, "approve").status_code == 409      # supported: challenge it instead
    with psycopg.connect(url) as c:
        actions = [a for (a,) in c.execute("SELECT action FROM audit_events ORDER BY id")]
    assert actions[-2:] == ["claim_review.approve", "claim.supported"]
    q = client.get(f"/v1/repos/{PILOT}/review-queue").json()
    assert cid not in [i["id"] for i in q["items"]]


def test_authors_cannot_review_their_own_claims(world):
    client, h, url = world
    cid = reader_claim(url, author="ext")
    r = review(client, h["ext"], cid, "approve")
    assert r.status_code == 403 and "own claim" in r.json()["error"]


def test_objections_challenges_and_changed_documents_hold_a_claim(world):
    client, h, url = world
    with psycopg.connect(url) as c:
        repo = ids.get_repo(c, PILOT)
        svc = ids.register_agent(c, "lab", "lab-bot", "service")
        ids.set_member(c, repo.id, svc["id"], "reviewer", granted_by=None)
        tok, _, _ = ids.issue_key(c, svc["id"], {"read", "review", "propose"})
    labbot = {"Authorization": f"Bearer {tok}"}

    held = reader_claim(url)
    r = review(client, labbot, held, "reject", "the passage is about WOMAC, not pain").json()
    assert r["state"] == "under_review" and any("says reject" in x for x in r["reasons"])
    r = review(client, h["ext"], held, "approve").json()
    assert r["state"] == "under_review" and any("says reject" in x for x in r["reasons"])   # the objection stands
    r = review(client, h["admin"], held, "reject", "agreed").json()
    assert r["state"] == "rejected"                                         # a maintainer settles it

    challenged = reader_claim(url, text=QUOTE + " ")
    object_to(client, h["bot"], challenged,
                **{"kind": "scope", "statement": "single centre"})
    r = review(client, h["ext"], challenged, "approve").json()
    assert r["state"] == "under_review" and any("blocking challenge" in x for x in r["reasons"])

    moved = reader_claim(url, text=QUOTE + "  ")
    with psycopg.connect(url) as c:
        c.execute("UPDATE claims SET doc_sha256 = %s WHERE id = %s", ("0" * 64, moved))
    r = review(client, h["ext"], moved, "approve").json()
    assert r["state"] == "under_review" and any("document changed" in x for x in r["reasons"])


def test_a_service_approval_alone_is_not_enough_for_a_policy_wanting_a_human(world):
    client, h, url = world
    with psycopg.connect(url) as c:
        repo = ids.get_repo(c, PILOT)
        svc = ids.register_agent(c, "lab", "lab-bot", "service")
        ids.set_member(c, repo.id, svc["id"], "reviewer", granted_by=None)
        tok, _, _ = ids.issue_key(c, svc["id"], {"read", "review"})
    cid = reader_claim(url)
    r = review(client, {"Authorization": f"Bearer {tok}"}, cid, "approve").json()
    assert r["state"] == "under_review" and "policy needs an approval from a human reviewer" in r["reasons"]
    assert review(client, h["ext"], cid, "approve").json()["state"] == "supported"
    assert state_of(url, cid) == "supported"


def test_the_queue_groups_claims_by_trial_with_the_abstract_once(world):
    client, h, url = world
    first, second = reader_claim(url), reader_claim(url, text=QUOTE + " (second reading)")
    with psycopg.connect(url) as c:                                   # a claim on the full text too
        c.execute("INSERT INTO documents (source_id, part, text, sha256) VALUES ('MED:1', 'fulltext', %s, %s)",
                  (TEXT + " Discussion.", "f" * 64))
        third = c.execute(
            "INSERT INTO claims (document_id, doc_sha256, span_start, span_end, text, extractor, repository_id, type, "
            "state, agent_id) SELECT d.id, d.sha256, 0, 7, 'Methods', 'reader', r.id, 'empirical', 'structurally_valid', "
            "a.id FROM documents d, repositories r, agents a WHERE d.part = 'fulltext' AND r.slug = %s "
            "AND a.handle = 'rrsrch-reader' RETURNING id", (PILOT,)).fetchone()[0]
    trials = client.get(f"/v1/repos/{PILOT}/review-queue/trials").json()
    assert trials["trials"] == 1 and trials["items"] == [
        {"source_id": "MED:1", "title": trials["items"][0]["title"], "year": None, "waiting": 3}]
    got = client.get(f"/v1/repos/{PILOT}/review-queue/trials/MED:1").json()
    assert [d["part"] for d in got["documents"]] == ["abstract", "fulltext"] and got["documents"][0]["text"] == TEXT
    assert [c["id"] for c in got["claims"]] == [first, second, third]
    c = got["claims"][0]
    assert TEXT[c["start"]:c["end"]] == QUOTE and c["part"] == "abstract" and c["reviews"] == []

    review(client, h["ext"], first, "approve")                      # supported: leaves the queue
    got = client.get(f"/v1/repos/{PILOT}/review-queue/trials/MED:1").json()
    assert [c["id"] for c in got["claims"]] == [second, third]
    assert client.get(f"/v1/repos/{PILOT}/review-queue/trials/MED:404").status_code == 404
    assert client.get("/v1/repos/rrsrch/nope/review-queue/trials").status_code == 404


def test_one_list_and_one_action_for_everything_waiting_for_review(world):
    from test_trust_db import content, open_mr
    client, h, url = world
    cid = reader_claim(url)
    mr = open_mr(client, h["bot"], {"repository": PILOT, "content": content()})
    q = client.get(f"/v1/repos/{PILOT}/needs-review").json()
    assert [p["id"] for p in q["proposals"]["items"]] == [mr] and q["proposals"]["waiting"] == 1
    assert cid in [c["id"] for c in q["claims"]["items"]] and q["waiting"] == 1 + q["claims"]["waiting"]

    post = lambda who, **b: client.post("/v1/reviews", headers=h[who], json=b)  # noqa: E731
    assert post("ext", target="proposal:abc", verdict="approve").status_code == 400
    assert post("ext", target=f"claim:{cid}", verdict="request_changes").status_code == 400
    assert post("bot", target=f"proposal:{mr}", verdict="approve").status_code == 403    # its author
    r = post("ext", target=f"proposal:{mr}", verdict="approve", findings="span matches")
    assert r.status_code == 200 and r.json()["merge_request_id"] == mr
    r = post("ext", target=f"claim:{cid}", verdict="approve", findings="matches the passage")
    assert r.status_code == 200 and r.json()["state"] == "supported"
    assert post("ext", target=f"mr:{mr}", verdict="request_changes").status_code == 200  # the comment-target spelling
    with psycopg.connect(url) as c:
        assert c.execute("SELECT verdict FROM reviews WHERE merge_request_id = %s", (mr,)).fetchone()[0] == \
            "request_changes"
    q = client.get(f"/v1/repos/{PILOT}/needs-review").json()
    assert cid not in [c["id"] for c in q["claims"]["items"]]
