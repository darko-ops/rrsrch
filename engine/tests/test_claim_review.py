"""Reviewing claims already in a repository: unreviewed -> under review -> supported (or rejected)."""
import psycopg
import pytest
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
    return client.post(f"/v1/claims/{cid}/reviews", headers=who, json={"verdict": verdict, "findings": findings})


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
    client.post(f"/v1/claims/{challenged}/challenges", headers=h["bot"],
                json={"kind": "scope", "statement": "single centre"})
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
