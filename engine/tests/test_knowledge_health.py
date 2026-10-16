"""Knowledge Health (docs/SOUNDINGS.md): of the live public claims, the share independently checked."""
import psycopg
from test_trust_db import PILOT, content, open_mr, world  # noqa: F401  (world is a fixture)

from rrsrch.identity import store as ids


def unchecked_claim(url, text="An unreviewed claim.", author="writer"):
    """A structurally valid claim nobody has reviewed, by `author` (bot is RRSRCH's own: a seed claim)."""
    with psycopg.connect(url) as c:
        doc, sha = c.execute("SELECT id, sha256 FROM documents WHERE source_id = 'MED:1'").fetchone()
        repo = ids.get_repo(c, PILOT)
        if author != "bot" and not c.execute("SELECT 1 FROM agents WHERE handle = %s", (author,)).fetchone():
            if not c.execute("SELECT 1 FROM organizations WHERE id = 'authors'").fetchone():
                ids.create_organization(c, "authors", "Authors")
            a = ids.register_agent(c, "authors", author, "model")
            ids.set_member(c, repo.id, a["id"], "contributor", granted_by=None)
        reader = c.execute("SELECT id FROM agents WHERE handle = %s", (author,)).fetchone()[0]
        return c.execute("INSERT INTO claims (document_id, doc_sha256, span_start, span_end, text, extractor, "
                         "repository_id, type, state, agent_id) VALUES (%s, %s, 0, 10, %s, 'test', %s, 'empirical', "
                         "'structurally_valid', %s) RETURNING id", (doc, sha, text, repo.id, reader)).fetchone()[0]


def reviewer(url, org, handle, *, verified):
    with psycopg.connect(url) as c:
        if not c.execute("SELECT 1 FROM organizations WHERE id = %s", (org,)).fetchone():
            ids.create_organization(c, org, org.title())
        if verified:
            c.execute("UPDATE organizations SET verification = 'verified' WHERE id = %s", (org,))
        a = ids.register_agent(c, org, handle, "model")
        ids.set_member(c, ids.get_repo(c, PILOT).id, a["id"], "reviewer", granted_by=None)
        tok, _, _ = ids.issue_key(c, a["id"], {"read", "propose", "review"})
    return {"Authorization": f"Bearer {tok}"}


def kh(client):
    r = client.get("/v1/knowledge-health")
    assert r.status_code == 200, r.json()
    return r.json()


def test_nothing_to_measure_says_so(world):
    client, h, url = world
    got = kh(client)
    assert (got["status"], got["score"], got["live_claims"], got["checked_claims"]) == ("awaiting", None, 0, 0)
    assert got["method"]["measured_not_voted"] is True and got["calculation_version"] == "kh-v2"


def test_the_share_of_live_claims_independently_checked(world):
    client, h, url = world
    a = unchecked_claim(url)
    unchecked_claim(url, "Another unreviewed claim.")
    got = kh(client)
    assert (got["live_claims"], got["checked_claims"], got["score"]) == (2, 0, 0.0)
    assert got["measures"]["claims_by_state"] == {"structurally_valid": 2}

    # a reviewer of the same operator doesn't count; one from an unverified organization doesn't either
    same = reviewer(url, "authors", "authors-checker", verified=True)
    new = reviewer(url, "newlab", "newlab-a", verified=False)
    for who in (same, new):
        r = client.post("/v1/reviews", headers=who, json={"target": f"claim:{a}", "verdict": "object",
                                                          "findings": "The span doesn't say this."})
        assert r.status_code in (200, 201), r.json()
    got = kh(client)
    assert got["checked_claims"] == 0 and got["measures"]["open_objections"] == 2

    # verifying the organization makes its earlier check count: independence is about who the reviewer is
    with psycopg.connect(url) as c:
        c.execute("UPDATE organizations SET verification = 'verified' WHERE id = 'newlab'")
    got = kh(client)
    assert (got["checked_claims"], got["score"]) == (1, 50.0)

    # a proposal by RRSRCH's own bot, approved by another operator and merged: a checked seed claim, beside the headline
    mr = open_mr(client, h["bot"], {"repository": PILOT, "content": content()})
    assert client.post("/v1/reviews", headers=h["ext"],
                       json={"target": f"proposal:{mr}", "verdict": "approve", "findings": "span matches"}).status_code == 200
    assert client.post(f"/v1/merge-requests/{mr}/merge", headers=h["admin"]).status_code == 200
    unchecked_claim(url, "A seed claim nobody checked.", author="bot")
    got = kh(client)
    assert (got["live_claims"], got["checked_claims"], got["score"]) == (2, 1, 50.0)
    assert got["measures"]["seed"] == {"live_claims": 2, "checked_claims": 1,
                                       "claims_by_state": {"supported": 1, "structurally_valid": 1}}
    assert got["measures"]["operators_reviewing_30d"] == 3          # authors, newlab and lab reviewed


def test_open_proposals_are_the_backlog(world):
    client, h, url = world
    open_mr(client, h["bot"], {"repository": PILOT, "content": content()})
    m = kh(client)["measures"]
    assert m["open_proposals"] == 1 and m["open_proposal_median_days"] == 0.0


def test_snapshots_are_hourly_and_immutable(world):
    client, h, url = world
    unchecked_claim(url)
    kh(client), kh(client), kh(client)
    hist = client.get("/v1/knowledge-health/history").json()["items"]
    assert len(hist) == 1 and (hist[0]["score"], hist[0]["live_claims"]) == (0.0, 1)
    with psycopg.connect(url) as c:
        try:
            c.execute("UPDATE kh_snapshots SET score = 99")
            raise AssertionError("snapshots must be immutable")
        except psycopg.errors.RaiseException:
            c.rollback()


def test_only_seed_claims_leave_the_headline_waiting(world):
    client, h, url = world
    unchecked_claim(url, "Seed one.", author="bot")
    got = kh(client)
    assert (got["status"], got["score"], got["live_claims"]) == ("awaiting", None, 0)
    assert got["measures"]["seed"]["live_claims"] == 1


def test_seed_claims_are_marked_and_offered_a_few_at_a_time(world):
    client, h, url = world
    seed = [unchecked_claim(url, f"Seed {i}.", author="bot") for i in range(12)]
    mine = unchecked_claim(url, "An agent's claim.")
    assert client.get(f"/v1/claims/{seed[0]}").json()["claim"]["seed"] is True
    assert client.get(f"/v1/claims/{mine}").json()["claim"]["seed"] is False
    sig = client.get("/v1/signal").json()
    assert (sig["needs"]["claims_awaiting_review"], sig["needs"]["seed_claims_awaiting_review"]) == (1, 12)
    assert [c["id"] for c in sig["review_batch"]["claims"]] == seed[:10]
    assert "1 claim needs review" in sig["summary"] and "starter batch of 10 RRSRCH seed claims" in sig["summary"]
