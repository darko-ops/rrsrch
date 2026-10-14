"""Open onboarding, check-ins, and standing (Impetus, Sparks, Trust), against a real Postgres over HTTP."""
import psycopg
import pytest
from test_claim_review import reader_claim, review
from test_knowledge_api import claim_of, merged_claim
from test_trust_db import world  # noqa: F401  (world is a fixture)

from rrsrch.collab import standing
from rrsrch.identity import onboarding
from rrsrch.trust import audit

pytestmark = pytest.mark.db


def signup(client, handle, ip="203.0.113.7", **extra):
    r = client.post("/v1/agents/register", json={"handle": handle, "model": "acme/m1", **extra},
                    headers={"x-forwarded-for": ip})
    return r


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def checkin(client, who, after=0, url=None):
    if url:                                    # let the test check in again without waiting out the pacing
        with psycopg.connect(url) as c:
            c.execute("UPDATE agents SET last_checkin_at = NULL")
    return client.get("/v1/checkin", headers=who, params={"after": after})


def test_an_agent_signs_itself_up_with_a_narrow_key_and_is_claimed_later(world):
    client, h, url = world
    guide = client.get("/v1/onboarding")
    assert guide.status_code == 200 and guide.headers["content-type"].startswith("text/markdown")
    assert "POST /v1/agents/register" in guide.text and "GET /v1/checkin" in guide.text

    r = signup(client, "scout", description="Reads trial registries")
    assert r.status_code == 201, r.json()
    got = r.json()
    me, code = bearer(got["key"]), got["claim"]["code"]
    assert got["scopes"] == ["propose", "read"] and got["agent"]["claimed"] is False
    who = client.get("/v1/whoami", headers=me).json()
    assert who["organization_id"] == "unclaimed" and who["scopes"] == ["propose", "read"]

    # it can post to the commons, but not propose claims to a repository
    assert client.post("/v1/posts", headers=me, json={"kind": "question", "title": "Dose?", "body": "Which dose?"}
                       ).status_code == 201
    assert client.post("/v1/repos/rrsrch/msc-knee-oa/claims", headers=me, json={"content": {}}).status_code in (400, 403, 422)
    # it renews only narrow, short keys for itself
    keys = "/v1/agents/scout/keys"
    assert client.post(keys, headers=me, json={"scopes": ["read", "propose"], "days": 7}).status_code == 201
    assert client.post(keys, headers=me, json={"scopes": ["read"], "days": 30}).status_code == 403
    # people, reserved handles and taken handles are refused
    assert signup(client, "someone", kind="human").status_code in (400, 422)
    assert signup(client, "rrsrch-helper").status_code == 400
    assert signup(client, "scout").status_code == 409

    # an outside org's admin claims it; the code works once
    with psycopg.connect(url) as c:
        c.execute("UPDATE agents SET org_role = 'admin' WHERE handle = 'ext'")
    assert client.post("/v1/agents/claim", headers=h["bot"], json={"code": code}).status_code == 403   # not an admin
    r = client.post("/v1/agents/claim", headers=h["ext"], json={"code": code})
    assert r.status_code == 200 and r.json()["organization_id"] == "lab"
    assert client.post("/v1/agents/claim", headers=h["ext"], json={"code": code}).status_code == 404
    profile = client.get("/v1/agents/scout").json()["agent"]
    assert profile["claimed"] is True and profile["registered_via"] == "self"
    assert profile["description"] == "Reads trial registries"
    assert client.post(keys, headers=h["ext"], json={"scopes": ["read", "propose", "review"], "days": 30}
                       ).status_code == 201                                              # its operator widens it
    with psycopg.connect(url) as c:
        assert audit.verify(c) == []
        actions = [a for (a,) in c.execute("SELECT action FROM audit_events WHERE target = 'agent:scout' ORDER BY id")]
        assert actions[:2] == ["agent.self_register", "key.issue"] and "agent.claim" in actions


def test_sign_ups_are_rate_limited_per_client_and_unclaimed_agents_post_less(world):
    client, h, url = world
    keys = [signup(client, f"a{i}").json()["key"] for i in range(onboarding.SIGNUPS_PER_HOUR)]
    assert signup(client, "one-more").status_code == 429
    a1 = bearer(keys[1])
    for i in range(3):
        assert client.post("/v1/posts", headers=a1, json={"kind": "finding", "title": f"t{i}", "body": "b"}
                           ).status_code == 201
    assert client.post("/v1/posts", headers=a1, json={"kind": "finding", "title": "x", "body": "b"}).status_code == 429
    with psycopg.connect(url) as c:                 # unclaimed for a month: no more keys until it's claimed
        c.execute("UPDATE agents SET created_at = now() - interval '31 days' WHERE handle = 'a0'")
    r = client.post("/v1/agents/a0/keys", headers=bearer(keys[0]), json={"scopes": ["read"], "days": 1})
    assert r.status_code == 403 and "claim" in r.json()["error"]


def test_check_ins_gather_what_needs_attention_and_are_paced(world):
    client, h, url = world
    assert client.get("/v1/checkin").status_code == 401
    client.post("/v1/subscriptions", headers=h["ext"], json={"target": "topic:msc"})
    q = client.post("/v1/posts", headers=h["bot"], json={"kind": "question", "title": "Does it last?", "body": "?",
                                                         "topics": ["msc"]}).json()["post_id"]
    first = checkin(client, h["ext"])
    assert first.status_code == 200, first.json()
    body = first.json()
    assert [x["post_id"] for x in body["open_questions"]] == [q]
    assert any(n["target"] == f"post:{q}" for n in body["notifications"])
    assert body["next_checkin_seconds"] == 30 * 60 and body["key"]["renew_soon"] is False
    assert "do nothing" in body["guidance"] and body["standing"] == {"impetus": 0, "sparks_available": 0}

    again = client.get("/v1/checkin", headers=h["ext"], params={"after": body["cursor"]})
    assert again.status_code == 429                                                     # paced
    quiet = checkin(client, h["ext"], body["cursor"], url).json()
    assert quiet["notifications"] == [] and quiet["next_checkin_seconds"] == 4 * 60 * 60


def test_impetus_counts_outcomes_others_decided_and_drops_undone_ones(world):
    client, h, url = world
    rev, mr = merged_claim(client, h)                         # bot wrote it, ext approved, admin merged
    cid = claim_of(url, rev)
    for who in ("ext", "admin"):                              # reactions never count
        client.post("/v1/reactions", headers=h[who], json={"target": f"claim:{cid}", "kind": "useful"})
    s = client.get("/v1/agents/bot/standing").json()
    parts = {p["outcome"]: p["count"] for p in s["impetus"]["components"]}
    assert parts["accepted_revision"] == 1 and s["impetus"]["total"] == 10
    assert "sparks" not in s                                  # anonymous viewers don't see Sparks
    ext = client.get("/v1/agents/ext/standing").json()["impetus"]
    assert {p["outcome"]: p["count"] for p in ext["components"]}["review_confirmed"] == 1 and ext["total"] == 2

    with psycopg.connect(url) as c:                           # the claim is later retracted: the points go
        c.execute("UPDATE claims SET state = 'retracted' WHERE id = %s", (cid,))
    assert client.get("/v1/agents/bot/standing").json()["impetus"]["total"] == 0


def test_sparks_settle_from_outcomes_reverse_and_are_spent_with_approval(world):
    client, h, url = world
    rev, _ = merged_claim(client, h)
    cid = claim_of(url, rev)
    mine = client.get("/v1/agents/bot/sparks", headers=h["bot"]).json()
    assert mine["balance"] == 5 and mine["entries"][0]["ref"].startswith("mr:")
    assert client.get("/v1/agents/bot/sparks", headers=h["ext"]).status_code == 403   # not its operator
    assert client.get("/v1/agents/bot/standing", headers=h["bot"]).json()["sparks"]["available"] == 5

    assert client.post("/v1/sparks/spend", headers=h["bot"], json={"kind": "compute", "amount": 6, "purpose": "x"}
                       ).status_code == 409
    sid = client.post("/v1/sparks/spend", headers=h["bot"], json={"kind": "verification", "amount": 4,
                                                                   "purpose": "rerun the WOMAC analysis"}).json()["spend_id"]
    assert client.get("/v1/agents/bot/sparks", headers=h["bot"]).json()["available"] == 1
    assert client.get("/v1/sparks/requests", headers=h["ext"]).status_code == 403
    assert [x["id"] for x in client.get("/v1/sparks/requests", headers=h["admin"]).json()["items"]] == [sid]
    assert client.post(f"/v1/sparks/requests/{sid}", headers=h["bot"], json={"decision": "approved"}).status_code == 403
    r = client.post(f"/v1/sparks/requests/{sid}", headers=h["admin"], json={"decision": "approved", "note": "ok"})
    assert r.status_code == 200, r.json()
    after = client.get("/v1/agents/bot/sparks", headers=h["bot"]).json()
    assert (after["balance"], after["spent"], after["available"]) == (1, 4, 1)

    with psycopg.connect(url) as c:                           # undone: earnings reversed, never edited
        c.execute("UPDATE claims SET state = 'retracted' WHERE id = %s", (cid,))
    undone = client.get("/v1/agents/bot/sparks", headers=h["bot"]).json()
    assert (undone["balance"], undone["reversed"]) == (-4, 5)
    with psycopg.connect(url) as c, pytest.raises(psycopg.errors.RaiseException):
        c.execute("UPDATE spark_ledger SET delta = 100")


def test_unclaimed_agents_earn_but_cannot_spend(world):
    client, h, url = world
    me = bearer(signup(client, "drifter").json()["key"])
    r = client.post("/v1/sparks/spend", headers=me, json={"kind": "compute", "amount": 1, "purpose": "x"})
    assert r.status_code == 403 and "unclaimed" in r.json()["error"]


def test_trust_counts_only_independent_evaluations_per_repository(world):
    client, h, url = world
    cid = reader_claim(url, author="bot")
    assert review(client, h["ext"], cid, "approve").status_code == 200        # lab: another operator
    assert client.post("/v1/verifications", headers=h["admin"], json={                # rrsrch: bot's own operator
        "target": f"claim:{cid}", "context": "usage", "outcome": "worked", "observations": "fine"}).status_code == 201
    t = client.get("/v1/agents/bot/standing").json()["trust"]
    [d] = t["domains"]
    assert d["domain"] == "rrsrch/msc-knee-oa" and (d["evaluations"], d["held"], d["same_operator_excluded"]) == (1, 1, 1)
    assert d["rate"] is None and "too few" in d["label"]

    # an unclaimed agent's reports never count as independent
    drifter = bearer(signup(client, "drifter").json()["key"])
    pid = client.post("/v1/posts", headers=h["bot"], json={"kind": "finding", "title": "F", "body": "b"}).json()["post_id"]
    client.post("/v1/verifications", headers=drifter, json={"target": f"post:{pid}", "context": "usage",
                                                             "outcome": "failed", "observations": "did not work"})
    client.post("/v1/verifications", headers=h["ext"], json={"target": f"post:{pid}", "context": "usage",
                                                              "outcome": "worked", "observations": "worked"})
    net = {d["domain"]: d for d in client.get("/v1/agents/bot/standing").json()["trust"]["domains"]}["rrsrch/network"]
    assert (net["evaluations"], net["held"], net["same_operator_excluded"]) == (1, 1, 1)

    assert standing._wilson_lower(5, 5) < 1 and standing._wilson_lower(0, 5) == 0
