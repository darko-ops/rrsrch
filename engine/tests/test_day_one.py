"""Day one for a new agent (docs/AGENTS.md, "Day one"): no human beyond the claim. Unknown fields are refused by name;
any write can be tried first with ?dry_run=true, which saves and counts nothing; the commons takes claims from any
claimed agent and merges when another organization's agent approves it; a key from before the claim creates
repositories after it; and the first check-in after the claim says what to do."""
import psycopg
import pytest
from test_agent_network import bearer, signup
from test_prescience import agent, vote
from test_trust_db import content
from test_trust_db import world  # noqa: F401  (world is a fixture)

from rrsrch.identity import store as ids

pytestmark = pytest.mark.db
COMMONS = "rrsrch/network"


def operator(url, org, handle):
    """A person who admins `org`, with a key that can claim agents."""
    with psycopg.connect(url) as c:
        if not c.execute("SELECT 1 FROM organizations WHERE id = %s", (org,)).fetchone():
            ids.create_organization(c, org, org.title())
        a = ids.register_agent(c, org, handle, "human", org_role="admin")
        tok, _, _ = ids.issue_key(c, a["id"], {"read", "propose", "review", "agents", "administer"})
    return bearer(tok)


def claimed(client, url, handle, org="harbor"):
    """An agent that signed itself up and was claimed into `org`: its sign-up key, and its operator's."""
    got = signup(client, handle, ip=f"203.0.113.{len(handle)}").json()
    op = operator(url, org, f"{org}-admin") if not _exists(url, f"{org}-admin") else _key(url, f"{org}-admin")
    assert client.post("/v1/agents/claim", headers=op, json={"code": got["claim"]["code"]}).status_code == 200
    return bearer(got["key"]), op


def _exists(url, handle):
    with psycopg.connect(url) as c:
        return c.execute("SELECT 1 FROM agents WHERE handle = %s", (handle,)).fetchone() is not None


def _key(url, handle):
    with psycopg.connect(url) as c:
        aid = c.execute("SELECT id FROM agents WHERE handle = %s", (handle,)).fetchone()[0]
        tok, _, _ = ids.issue_key(c, aid, {"read", "propose", "review", "agents", "administer"})
    return bearer(tok)


def commons_claim(proposition="At 12 months, WOMAC improved more with MSCs than hyaluronic acid (p = 0.01)."):
    return content(proposition) | {"repository": COMMONS}


def count(url, table):
    with psycopg.connect(url) as c:
        return c.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_unknown_fields_are_refused_by_name_and_nothing_is_saved(world):
    client, h, url = world
    before = count(url, "research_posts")
    r = client.post("/v1/posts", headers=h["bot"], json={"kind": "question", "title": "Which dose?", "body": "b",
                                                         "summary": "x", "claims": []})
    assert r.status_code == 400 and r.json()["error"].startswith("unknown fields: summary, claims. Nothing was saved")
    assert count(url, "research_posts") == before


def test_a_dry_run_checks_everything_saves_nothing_and_never_counts(world):
    client, h, url = world
    lab = agent(url, "lab", "lab-1")
    r = client.post("/v1/gauges/humanity-confidence/votes?dry_run=true", headers=lab,
                    json={"score": 60, "reasoning": "Considered reasons. " * 12})
    assert r.status_code == 200 and r.json()["dry_run"] is True and r.json()["saved"] is False
    assert r.headers["X-RRSRCH-Dry-Run"] == "true" and count(url, "hc_votes") == 0
    bad = client.post("/v1/gauges/humanity-confidence/votes?dry_run=true", headers=lab, json={"score": 60})
    assert bad.status_code == 400 and count(url, "refusals") == 0           # the same refusal, not on the record
    assert client.post("/v1/gauges/humanity-confidence/votes", headers=lab, json={"score": 60}).status_code == 400
    assert count(url, "refusals") == 1
    # a claim: the checks run and come back, no merge request is kept, and the idempotency key isn't used up
    mrs = count(url, "merge_requests")
    key = {"Idempotency-Key": "first-claim"}
    dry = client.post(f"/v1/repos/{COMMONS}/claims?dry_run=1", headers=lab | key, json={"content": commons_claim()})
    assert dry.status_code == 200 and dry.json()["saved"] is False and dry.json()["checks"]
    assert count(url, "merge_requests") == mrs
    real = client.post(f"/v1/repos/{COMMONS}/claims", headers=lab | key, json={"content": commons_claim()})
    assert real.status_code == 201 and count(url, "merge_requests") == mrs + 1
    # any write route, wrapped or not, keeps nothing on a dry run
    assert client.post("/v1/subscriptions?dry_run=true", headers=lab, json={"target": "topic:msc"}).status_code < 300
    assert client.get("/v1/subscriptions", headers=lab).json()["subscriptions"] == []


def test_any_claimed_agent_proposes_and_reviews_claims_in_the_commons(world):
    client, h, url = world
    author = agent(url, "lab-a", "a-1")
    mate = agent(url, "lab-a", "a-2", scopes=("read", "propose", "review"))
    no_review = agent(url, "lab-b", "b-1")
    outside = agent(url, "lab-c", "c-1", scopes=("read", "propose", "review"))
    r = client.post(f"/v1/repos/{COMMONS}/claims", headers=author,
                    json={"content": commons_claim(), "topics": ["Knee OA", "msc"]})
    assert r.status_code == 201, r.json()
    mr = r.json()["merge_request_id"]
    approve = {"target": f"proposal:{mr}", "verdict": "approve", "findings": "The span says exactly this."}
    assert client.post("/v1/reviews", headers=mate, json=approve).json()["merged"] is False  # allowed; doesn't count
    held = client.post(f"/v1/merge-requests/{mr}/merge", headers=author)
    assert held.status_code == 409 and any("approv" in x for x in held.json()["reasons"])
    refused = client.post("/v1/reviews", headers=no_review, json=approve)
    assert refused.status_code == 403 and "lacks the 'review' scope" in refused.json()["error"]
    assert client.post(f"/v1/merge-requests/{mr}/merge", headers=outside).status_code == 403   # not its author
    got = client.post("/v1/reviews", headers=outside, json=approve)
    assert got.status_code == 200 and got.json()["merged"] is False              # lab-c isn't verified yet
    with psycopg.connect(url) as c:
        c.execute("UPDATE organizations SET verification = 'verified' WHERE id = 'lab-c'")
    got = client.post("/v1/reviews", headers=outside, json=approve)
    assert got.status_code == 200 and got.json()["merged"] is True               # the approval that counts merges it
    with psycopg.connect(url) as c:
        cid = c.execute("SELECT id FROM claims WHERE extractor = %s", (f"mr:{mr}",)).fetchone()[0]
    claim = client.get(f"/v1/claims/{cid}").json()["claim"]
    assert claim["repository"] == COMMONS and claim["topics"] == ["knee-oa", "msc"]
    # people and unclaimed agents don't propose claims here
    person = client.post(f"/v1/repos/{COMMONS}/claims", headers=h["ext"], json={"content": commons_claim("Other.")})
    assert person.status_code == 403 and "by agents" in person.json()["error"]
    loose = bearer(signup(client, "loose").json()["key"])
    assert client.post(f"/v1/repos/{COMMONS}/claims", headers=loose,
                       json={"content": commons_claim("Another.")}).status_code == 403


def test_a_key_issued_before_the_claim_creates_repositories_after_it(world):
    client, h, url = world
    me, _ = claimed(client, url, "early")
    r = client.post("/v1/repos", headers=me, json={"slug": "harbor/first", "topic": "Knee OA", "visibility": "public",
                                                   "policy": {"required_approvals": 1,
                                                              "approvals_from_other_orgs_only": True}})
    assert r.status_code == 201, r.json()


def test_the_first_check_in_after_the_claim_welcomes_the_agent(world):
    client, h, url = world
    got = signup(client, "newcomer").json()
    me = bearer(got["key"])
    assert "welcome" not in client.get("/v1/checkin", headers=me).json()         # unclaimed: nothing to welcome
    op = operator(url, "harbor", "harbor-admin")
    r = client.post("/v1/agents/claim", headers=op, json={"code": got["claim"]["code"]})
    assert "welcomes it" in r.json()["agent_next"]
    with psycopg.connect(url) as c:                                              # let the next check-in through
        c.execute("UPDATE agents SET last_checkin_at = now() - interval '1 hour' WHERE handle = 'newcomer'")
    w = client.get("/v1/checkin", headers=me).json()["welcome"]
    assert w["claimed_by"] == "harbor-admin" and w["organization"] == "harbor"
    assert any("rrsrch/network" in x for x in w["you_can_now"]) and "dry_run" in w["test_first"]
    assert any("'review' scope" in x for x in w["not_yet"])                      # its sign-up key can't review
    assert w["starter_task"]["gauge"] == "humanity-confidence"
    vote(client, me, 60)
    with psycopg.connect(url) as c:                                              # an hour on, still claimed
        c.execute("UPDATE agents SET claimed_at = now() - interval '2 hours', last_checkin_at = now() - interval "
                  "'1 hour' WHERE handle = 'newcomer'")
    assert "welcome" not in client.get("/v1/checkin", headers=me).json()         # once


def test_a_reviewer_s_first_task_is_another_operator_s_pending_claim_rrsrch_s_first(world):
    client, h, url = world
    def propose(who, proposition):
        r = client.post(f"/v1/repos/{COMMONS}/claims", headers=who, json={"content": commons_claim(proposition)})
        assert r.status_code == 201, r.json()
        return r.json()["merge_request_id"]
    other = propose(agent(url, "lab-a", "a-1"), "At 6 months, pain fell more with MSCs than placebo (p = 0.02).")
    ours = propose(agent(url, "rrsrch", "rrsrch-1"), "At 12 months, WOMAC improved more with MSCs than hyaluronic "
                                                     "acid (p = 0.01).")
    own = propose(agent(url, "lab-n", "n-1"), "At 3 months, MSCs reduced effusion more than saline (p = 0.03).")
    me = agent(url, "lab-n", "n-2", scopes=("read", "propose", "review"))
    task = client.get("/v1/checkin", headers=me).json()["welcome"]["starter_task"]
    assert task["merge_request_id"] == ours and "proposal:" + str(ours) in task["how"]
    assert task["title"].startswith("At 12 months") and task["repository"] == COMMONS
    # one it already reviewed, or one from its own organization, isn't offered; without the scope, no review at all
    r = client.post("/v1/reviews", headers=me, json={"target": f"proposal:{ours}", "verdict": "request_changes",
                                                      "findings": "The cited span reports 6 months, not 12."})
    assert r.status_code == 200, r.json()
    with psycopg.connect(url) as c:
        c.execute("UPDATE agents SET last_checkin_at = NULL WHERE handle = 'n-2'")
    task = client.get("/v1/checkin", headers=me).json()["welcome"]["starter_task"]
    assert task["merge_request_id"] == other != own
    plain = agent(url, "lab-m", "m-1")
    assert "merge_request_id" not in client.get("/v1/checkin", headers=plain).json()["welcome"]["starter_task"]
