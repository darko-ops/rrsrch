"""Self-serve organizations (a site account creates one and claims its agents) and the public signal."""
import psycopg
import pytest
from test_claim_review import reader_claim, review
from test_site_people import SECRET, person
from test_trust_db import PILOT, world  # noqa: F401  (world is a fixture)

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
    assert [g["gauge"] for g in s["gauges"]["items"]][:4] == ["humanity-confidence", "ai-safety",
                                                              "scientific-progress", "human-agency"]
    assert "POST https://rrsrch.com/api/engine/v1/gauges" in s["gauges"]["about"]


def test_the_signal_counts_independent_operators_toward_the_arena(world):
    from test_prescience import agent
    client, h, url = world
    arena = lambda: client.get("/v1/signal").json()["arena"]  # noqa: E731
    assert arena()["operators"] == 0 and arena()["needed"] == 8 and arena()["open"] is False
    ask = lambda who, t: client.post("/v1/posts", headers=who, json={"kind": "question", "title": t, "body": "?"})  # noqa: E731
    assert ask(h["ext"], "A person asks?").status_code == 201        # lab is verified, but a person isn't an agent
    assert ask(h["bot"], "RRSRCH asks?").status_code == 201          # RRSRCH's own never count
    assert arena()["operators"] == 0
    with psycopg.connect(url) as c:
        c.execute("UPDATE organizations SET verification = 'verified' WHERE id = 'lab'")
    assert ask(agent(url, "lab", "lab-1"), "Which dose?").status_code == 201
    assert arena()["operators"] == 1
    owner = agent(url, "ominis-labs", "om-1")
    with psycopg.connect(url) as c:
        c.execute("UPDATE organizations SET verification = 'verified' WHERE id = 'ominis-labs'")
    assert ask(owner, "Owner asks?").status_code == 201
    assert ask(agent(url, "harbor", "h-1"), "Unverified asks?").status_code == 201
    assert arena()["operators"] == 1                                  # the owner's org and unverified ones don't


def test_a_person_who_admins_an_organization_creates_its_repositories_from_the_site(world, monkeypatch):
    client, h, url = world
    monkeypatch.setenv("RRSRCH_PROXY_SECRET", SECRET)
    me = person("u-3", "Katherine Johnson")
    client.post("/v1/subscriptions", headers=me, json={"target": "topic:msc"})
    client.post("/v1/organizations", headers=me, json={"id": "johnson-lab", "name": "Johnson Lab"})
    assert "administer" in client.get("/v1/whoami", headers=me).json()["scopes"]
    r = client.post("/v1/repos", headers=me, json={"slug": "johnson-lab/semis", "topic": "Semiconductors",
                                                   "visibility": "public", "policy": {}})
    assert r.status_code == 201, r.json()                                 # a person sets any policy
    repo = r.json()["repository"]
    assert (repo["created_via"], repo["operator_verified"]) == ("human", False)
    assert client.post("/v1/repos", headers=me, json={"slug": "rrsrch/x", "topic": "t",
                                                      "visibility": "private"}).status_code == 403
    other = person("u-4", "Someone")                                       # a person in no organization can't
    client.post("/v1/subscriptions", headers=other, json={"target": "topic:msc"})
    assert "administer" not in client.get("/v1/whoami", headers=other).json()["scopes"]


def test_featured_topics_follow_this_weeks_activity_not_all_time_counts(world):
    client, h, url = world
    def ask(title, topics, who="ext"):
        r = client.post("/v1/posts", headers=h[who], json={"kind": "question", "title": title, "body": "?",
                                                           "topics": topics})
        assert r.status_code == 201, r.text
        return r.json()["post_id"]
    for title in ("Solar", "Global health", "Test"):
        assert client.post("/v1/topics", headers=h["admin"], json={"title": title}).status_code == 201
    old = [ask(f"Old {i}", ["knee-oa"], who) for i, who in enumerate(("ext", "ext", "bot", "bot"))]
    with psycopg.connect(url) as c:                       # knee-oa was busy, but a month ago
        c.execute("UPDATE research_posts SET created_at = now() - interval '30 days' WHERE id = ANY(%s)", (old,))
    solar = ask("Do panels degrade?", ["solar"], "admin")
    health = ask("Which interventions save lives?", ["global-health"], "admin")
    client.post("/v1/comments", headers=h["bot"], json={"target": f"post:{health}", "body": "This trial."})
    ask("[Test] ignore", ["test"], "admin")
    f = client.get("/v1/signal").json()["featured"]
    got = [(t["topic"], t["activity"]) for t in f["items"]]
    assert got == [("global-health", 2), ("solar", 1), ("knee-oa", 0)]       # this week first; quiet ones fill in
    assert f["items"][1]["question"] == {"id": solar, "title": "Do panels degrade?"}
    assert f["items"][0]["question"]["id"] == health and f["items"][2]["question"]["id"] == old[-1]
    assert f["items"][0]["url"] == "https://rrsrch.com/topics/global-health"


def test_topics_tagged_together_take_one_featured_place(world):
    client, h, url = world
    for title in ("Solar", "Batteries"):
        assert client.post("/v1/topics", headers=h["admin"], json={"title": title}).status_code == 201
    for who, topics in (("ext", ["batteries", "solar"]), ("bot", ["batteries", "solar"]), ("admin", ["knee-oa"])):
        r = client.post("/v1/posts", headers=h[who], json={"kind": "question", "title": f"Q {who}", "body": "?",
                                                           "topics": topics})
        assert r.status_code == 201, r.text
    got = [t["topic"] for t in client.get("/v1/signal").json()["featured"]["items"]]
    assert got[:2] == ["batteries", "knee-oa"] and got.index("solar") > 1     # solar's posts already shown under batteries


def test_a_retired_collections_claims_leave_the_signal_and_the_count(world):
    client, h, url = world
    reader_claim(url, author="bot")
    assert client.get("/v1/health").json()["claims"] >= 1
    assert client.delete(f"/v1/repos/{PILOT}", headers=h["admin"], params={"confirm": PILOT}).status_code == 200
    s = client.get("/v1/signal").json()
    assert s["review_batch"]["claims"] == [] and s["needs"]["seed_claims_awaiting_review"] == 0
    assert "seed claim" not in s["summary"]
    assert client.get("/v1/health").json()["claims"] == 0


def test_an_admin_connects_an_agent_claimed_and_keyed_in_one_step(world, monkeypatch):
    client, h, url = world
    monkeypatch.setenv("RRSRCH_PROXY_SECRET", SECRET)
    me = person("u-3", "Lin")
    client.post("/v1/subscriptions", headers=me, json={"target": "topic:msc"})
    body = {"handle": "lin-claude", "client": "claude-code", "description": "reads trials"}
    assert client.post("/v1/agents/connect", headers=me, json=body).status_code == 403     # no organization yet
    assert client.post("/v1/agents/connect", json=body).status_code == 401
    client.post("/v1/organizations", headers=me, json={"id": "lin-lab", "name": "Lin Lab"})
    assert client.post("/v1/agents/connect", headers=me, json=body | {"client": "emacs"}).status_code == 400
    r = client.post("/v1/agents/connect", headers=me, json=body)
    assert r.status_code == 201, r.json()
    got = r.json()
    assert got["agent"]["organization_id"] == "lin-lab" and got["scopes"] == ["propose", "read", "review"]
    assert got["mcp_url"].endswith("/mcp") and got["key"].startswith("rrsrch_")
    assert client.post("/v1/agents/connect", headers=me, json=body).status_code == 409    # the handle is taken

    # the key works at once, as a claimed agent: its first check-in welcomes it, naming who claimed it
    agent = {"Authorization": f"Bearer {got['key']}"}
    who = client.get("/v1/whoami", headers=agent).json()
    assert (who["handle"], who["organization_id"]) == ("lin-claude", "lin-lab")
    checkin = client.get("/v1/checkin", headers=agent).json()
    assert checkin["welcome"]["claimed_by"] == "lin"
    keys = client.get("/v1/agents/lin-claude/keys", headers=me).json()["keys"]
    assert [k["label"] for k in keys] == ["Claude Code MCP"]
    assert client.post("/v1/agents/connect", headers=h["bot"], json=body | {"handle": "x-bot"}).status_code == 403
    with psycopg.connect(url) as c:
        assert audit.verify(c) == []
        assert c.execute("SELECT count(*) FROM audit_events WHERE action = 'agent.connect'").fetchone()[0] == 1
