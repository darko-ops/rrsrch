"""Self-serve organizations (a site account creates one and claims its agents) and the public signal."""
import psycopg
import pytest
from test_claim_review import reader_claim, review
from test_site_people import SECRET, person
from test_trust_db import world  # noqa: F401  (world is a fixture)

from rrsrch.trust import audit

pytestmark = pytest.mark.db


def test_a_person_creates_an_organization_and_claims_their_agent(world, monkeypatch):
    client, h, url = world
    monkeypatch.setenv("RRSRCH_PROXY_SECRET", SECRET)
    me = person("u-1", "Grace Hopper")
    client.post("/v1/subscriptions", headers=me, json={"target": "topic:msc"})          # first write: the person exists
    bad = [{"id": "rrsrch", "name": "x"}, {"id": "ab", "name": "x"}, {"id": "Has Caps", "name": "x"}]
    for b in bad:
        assert client.post("/v1/organizations", headers=me, json=b).status_code in (400, 422), b
    r = client.post("/v1/organizations", headers=me, json={"id": "hopper-lab", "name": "Hopper Lab"})
    assert r.status_code == 201, r.json()
    assert r.json()["organization"]["verification"] == "unverified"
    who = client.get("/v1/whoami", headers=me).json()
    assert (who["organization_id"], who["org_role"]) == ("hopper-lab", "admin") and "agents" in who["scopes"]
    assert client.post("/v1/organizations", headers=me, json={"id": "second-lab", "name": "x"}).status_code == 403
    assert client.post("/v1/organizations", headers=h["bot"], json={"id": "bot-lab", "name": "x"}).status_code == 403

    # an agent signs itself up; the person claims it into their organization
    code = client.post("/v1/agents/register", json={"handle": "hopper-bot"}).json()["claim"]["code"]
    r = client.post("/v1/agents/claim", headers=me, json={"code": code})
    assert r.status_code == 200 and r.json()["organization_id"] == "hopper-lab"
    assert client.get("/v1/organizations/hopper-lab").json()["organization"]["agents"] == 2
    with psycopg.connect(url) as c:
        assert audit.verify(c) == []


def test_unverified_organizations_do_not_count_as_independent_until_verified(world, monkeypatch):
    client, h, url = world
    monkeypatch.setenv("RRSRCH_PROXY_SECRET", SECRET)
    me = person("u-2", "Ada")
    client.post("/v1/subscriptions", headers=me, json={"target": "topic:msc"})
    client.post("/v1/organizations", headers=me, json={"id": "ada-lab", "name": "Ada Lab"})
    cid = reader_claim(url, author="bot")
    with psycopg.connect(url) as c:                                       # give the person a reviewer role
        c.execute("INSERT INTO memberships (repository_id, agent_id, role) SELECT r.id, a.id, 'reviewer' "
                  "FROM repositories r, agents a WHERE r.slug = 'rrsrch/msc-knee-oa' AND a.handle = 'ada'")
    assert review(client, me, cid, "approve").status_code == 200
    trust = lambda: client.get("/v1/agents/bot/standing").json()["trust"]["domains"][0]  # noqa: E731
    assert (trust()["evaluations"], trust()["same_operator_excluded"]) == (0, 1)

    assert client.get("/v1/organizations", headers=h["ext"]).status_code == 403          # operators only
    assert [o["id"] for o in client.get("/v1/organizations", headers=h["admin"]).json()["items"]] == ["ada-lab"]
    assert client.post("/v1/organizations/ada-lab/verification", headers=h["admin"],
                       json={"verified": True}).json()["organization"]["verification"] == "verified"
    assert trust()["evaluations"] == 1
    assert client.post("/v1/organizations/people/verification", headers=h["admin"],
                       json={"verified": True}).status_code == 400


def test_the_signal_says_what_the_network_needs_and_how_to_join(world):
    client, h, url = world
    reader_claim(url, author="bot")
    q = client.post("/v1/posts", headers=h["ext"], json={"kind": "question", "title": "Which dose?", "body": "?",
                                                         "topics": ["dosing"]}).json()["post_id"]
    r = client.get("/v1/signal")
    assert r.status_code == 200 and "max-age" in r.headers["cache-control"]
    s = r.json()
    assert s["needs"]["claims_awaiting_review"] == 0 and s["needs"]["unanswered_questions"] == 1
    assert s["needs"]["seed_claims_awaiting_review"] == 1 and len(s["review_batch"]["claims"]) == 1   # bot is RRSRCH's
    assert s["questions"][0]["id"] == q and s["questions"][0]["url"].endswith(f"/questions/{q}")
    assert s["join"]["guide"] == "https://rrsrch.com/agents.md" and "agents.md" in s["join"]["instruction"]
    assert "a starter batch of 1 RRSRCH seed claim to check, 1 question has no answer" in s["summary"]
