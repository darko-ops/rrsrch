"""Identity end to end: CLI-style bootstrap, then the HTTP API against a real Postgres."""
import psycopg
import pytest
from fastapi.testclient import TestClient

from rrsrch.identity import store
from rrsrch.ledger import db
from rrsrch.serve import api

pytestmark = pytest.mark.db


@pytest.fixture
def env(db_url):
    with psycopg.connect(db_url) as c:
        db.migrate(c)
        store.create_organization(c, "acme", "Acme Research")
        admin = store.register_agent(c, "acme", "acme-admin", "human", org_role="admin")
        root, _, _ = store.issue_key(c, admin["id"], {"agents", "read", "propose", "administer"}, days=7)
        repo_id = c.execute("INSERT INTO repositories (slug, organization_id, topic, visibility, policy_version) "
                            "VALUES ('acme/internal', 'acme', 'Internal findings', 'private', 'v1') "
                            "RETURNING id").fetchone()[0]
        c.execute("INSERT INTO policies (repository_id, version, rules) VALUES (%s, 'v1', '{}')", (repo_id,))
    app = api.create_app(connect=lambda: psycopg.connect(db_url))
    return TestClient(app), {"Authorization": f"Bearer {root}"}


def new_agent(client, admin, handle, scopes, **body):
    r = client.post("/v1/agents", headers=admin, json={"handle": handle, "kind": "service", **body})
    assert r.status_code == 201, r.json()
    r = client.post(f"/v1/agents/{handle}/keys", headers=admin, json={"scopes": scopes, "days": 1})
    assert r.status_code == 201, r.json()
    return {"Authorization": f"Bearer {r.json()['key']}"}, r.json()["key_id"]


def test_whoami_needs_a_valid_key(env):
    client, admin = env
    me = client.get("/v1/whoami", headers=admin).json()
    assert (me["handle"], me["org_role"]) == ("acme-admin", "admin")
    assert client.get("/v1/whoami").status_code == 401
    for bad in ("Bearer nope", "Basic abc", "Bearer rrsrch_000000000000_" + "a" * 43):
        r = client.get("/v1/whoami", headers={"Authorization": bad})
        assert r.status_code == 401 and r.json()["ok"] is False


def test_admin_registers_agents_and_handles_are_unique(env):
    client, admin = env
    new_agent(client, admin, "acme-bot", ["read"], model="some-model")
    assert client.get("/v1/agents/acme-bot").json()["agent"]["model"] == "some-model"
    r = client.post("/v1/agents", headers=admin, json={"handle": "acme-bot", "kind": "service"})
    assert r.status_code == 409
    r = client.post("/v1/agents", headers=admin, json={"handle": "Bad Handle", "kind": "service"})
    assert r.status_code == 400 and r.json()["error"].startswith("handle:")


def test_members_cannot_register_or_escalate(env):
    client, admin = env
    bot, _ = new_agent(client, admin, "acme-bot", ["read", "propose"])
    assert client.post("/v1/agents", headers=bot, json={"handle": "x", "kind": "service"}).status_code == 403
    # an agent may issue itself a key no broader than the one it holds
    assert client.post("/v1/agents/acme-bot/keys", headers=bot, json={"scopes": ["read"]}).status_code == 201
    r = client.post("/v1/agents/acme-bot/keys", headers=bot, json={"scopes": ["read", "agents"]})
    assert r.status_code == 403 and "agents" in r.json()["error"]
    assert client.post("/v1/agents/acme-admin/keys", headers=bot, json={"scopes": ["read"]}).status_code == 403
    # so may an admin: its key bounds the keys it issues (this one has no review or maintain)
    r = client.post("/v1/agents/acme-bot/keys", headers=admin, json={"scopes": ["read", "review", "maintain"]})
    assert r.status_code == 403 and "maintain" in r.json()["error"] and "review" in r.json()["error"]


def test_people_come_from_sign_in_not_from_an_admin(env):
    client, admin = env
    r = client.post("/v1/agents", headers=admin, json={"handle": "acme-person", "kind": "human"})
    assert r.status_code == 400 and "rrsrch.com" in r.json()["error"]
    assert client.get("/v1/agents/acme-person").status_code == 404


def test_a_suspended_agents_keys_stop_working(env, db_url):
    client, admin = env
    bot, _ = new_agent(client, admin, "acme-bot", ["read", "propose"])
    assert client.get("/v1/whoami", headers=bot).status_code == 200
    with psycopg.connect(db_url) as c:
        c.execute("UPDATE agents SET status = 'suspended' WHERE handle = 'acme-bot'")
    r = client.get("/v1/whoami", headers=bot)
    assert r.status_code == 401 and "suspended" in r.json()["error"]
    assert client.post("/v1/feedback", headers=bot, json={"target": "post:1", "value": 1}).status_code == 401


def test_private_repositories_are_invisible_without_a_role(env):
    client, admin = env
    bot, _ = new_agent(client, admin, "acme-bot", ["read", "propose"])
    assert client.get("/v1/repos/acme/internal/access").status_code == 404
    assert client.get("/v1/repos/acme/internal/access", headers=bot).status_code == 404
    pub = client.get("/v1/repos/rrsrch/msc-knee-oa/access").json()
    assert pub["actions"] == {"read": True, "propose": False, "review": False, "maintain": False, "administer": False}

    r = client.put("/v1/repos/acme/internal/members/acme-bot", headers=admin, json={"role": "contributor"})
    assert r.status_code == 200
    got = client.get("/v1/repos/acme/internal/access", headers=bot).json()
    assert got["role"] == "contributor" and got["actions"]["propose"] and not got["actions"]["review"]
    # a contributor can't hand out roles
    assert client.put("/v1/repos/acme/internal/members/acme-bot", headers=bot,
                      json={"role": "owner"}).status_code == 403
    assert client.delete("/v1/repos/acme/internal/members/acme-bot", headers=admin).json()["removed"] is True
    assert client.get("/v1/repos/acme/internal/access", headers=bot).status_code == 404


def test_other_organizations_admins_have_no_reach(env, db_url):
    client, admin = env
    with psycopg.connect(db_url) as c:
        other = store.register_agent(c, "rrsrch", "rrsrch-admin", "human", org_role="admin")
        tok, _, _ = store.issue_key(c, other["id"], {"agents", "read", "administer"})
    other_h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/v1/repos/acme/internal/access", headers=other_h).status_code == 404
    assert client.post("/v1/agents/acme-admin/revoke", headers=other_h).status_code == 403
    # but it owns its own org's pilot repository
    assert client.get("/v1/repos/rrsrch/msc-knee-oa/access", headers=other_h).json()["role"] == "owner"
    # and, running the network, it can revoke an unclaimed sign-up; another org's admin can't
    r = client.post("/v1/agents/register", json={"handle": "dupe", "kind": "model", "model": "m", "description": "d"})
    dupe = {"Authorization": f"Bearer {r.json()['key']}"}
    assert client.post("/v1/agents/dupe/revoke", headers=admin).status_code == 403
    assert client.post("/v1/agents/dupe/revoke", headers=other_h).json()["keys_revoked"] == 1
    assert client.get("/v1/whoami", headers=dupe).status_code == 401


def test_revocation_cuts_off_keys(env):
    client, admin = env
    bot, key_id = new_agent(client, admin, "acme-bot", ["read"])
    second = client.post("/v1/agents/acme-bot/keys", headers=bot, json={"scopes": ["read"]}).json()
    assert client.post(f"/v1/keys/{key_id}/revoke", headers=bot).json()["revoked"] is True
    r = client.get("/v1/whoami", headers=bot)                           # a refused key says why
    assert r.status_code == 401 and "this key was revoked" in r.json()["error"]
    wrong = {"Authorization": bot["Authorization"][:-2] + "zz"}         # only to someone holding the whole key
    assert client.get("/v1/whoami", headers=wrong).json()["error"].startswith("invalid key")
    bot2 = {"Authorization": f"Bearer {second['key']}"}
    assert client.get("/v1/whoami", headers=bot2).status_code == 200
    r = client.post("/v1/agents/acme-bot/revoke", headers=admin).json()
    assert r["keys_revoked"] == 1
    r2 = client.get("/v1/whoami", headers=bot2)
    assert r2.status_code == 401 and "agent was deactivated" in r2.json()["error"]
    assert r["handle_released"] == "acme-bot" and r["handle"].startswith("deactivated-")
    gone = client.get("/v1/agents/acme-bot").json()["agent"]          # the old name still finds it until it's taken
    assert gone["status"] == "revoked" and gone["handle"] == r["handle"]
    r = client.post("/v1/agents/acme-bot/keys", headers=admin, json={"scopes": ["read"]})
    assert r.status_code == 409
    # the name is free: a new agent takes it, and the old one stays on the record under deactivated-<id>
    new_agent(client, admin, "acme-bot", ["read"])
    assert client.get("/v1/agents/acme-bot").json()["agent"]["status"] == "active"
    assert client.get(f"/v1/agents/{gone['handle']}").json()["agent"]["status"] == "revoked"
    # and nobody can register a deactivated-<id> name
    assert client.post("/v1/agents/register", json={"handle": "deactivated-999", "kind": "model", "model": "m",
                                                    "description": "d"}).status_code == 409


def test_expired_keys_are_refused(env, db_url):
    client, admin = env
    bot, key_id = new_agent(client, admin, "acme-bot", ["read"])
    with psycopg.connect(db_url) as c:
        c.execute("UPDATE api_keys SET created_at = now() - interval '2 days', "
                  "expires_at = now() - interval '1 second' WHERE id = %s", (key_id,))
    assert client.get("/v1/whoami", headers=bot).status_code == 401


def test_keys_are_stored_hashed_and_bounded(env, db_url):
    client, admin = env
    r = client.post("/v1/agents", headers=admin, json={"handle": "acme-bot", "kind": "service"})
    key = client.post("/v1/agents/acme-bot/keys", headers=admin, json={"scopes": ["read"]}).json()["key"]
    with psycopg.connect(db_url) as c:
        stored = c.execute("SELECT prefix, secret_hash FROM api_keys ORDER BY id DESC LIMIT 1").fetchone()
    assert key.split("_")[1] == stored[0] and key.split("_", 2)[2] not in stored[1]
    assert client.post("/v1/agents/acme-bot/keys", headers=admin,
                       json={"scopes": ["read"], "days": 366}).status_code == 400
    assert client.post("/v1/agents/acme-bot/keys", headers=admin,
                       json={"scopes": ["root"]}).status_code == 400


def test_cli_bootstraps_an_admin_whose_key_works(db_url, monkeypatch, capsys):
    from rrsrch import cli
    monkeypatch.setenv("RRSRCH_DATABASE_URL", db_url)
    assert cli.main(["org", "add", "lab", "A Lab"]) == 0
    assert cli.main(["agent", "add", "lab-admin", "--org", "lab", "--kind", "human", "--admin"]) == 0
    assert cli.main(["agent", "add", "lab-admin", "--org", "lab"]) == 1             # taken
    capsys.readouterr()
    assert cli.main(["agent", "key", "lab-admin", "--scope", "agents", "--scope", "read", "--days", "3"]) == 0
    token = capsys.readouterr().out.strip().splitlines()[-1]
    client = TestClient(api.create_app(connect=lambda: psycopg.connect(db_url)))
    me = client.get("/v1/whoami", headers={"Authorization": f"Bearer {token}"}).json()
    assert (me["handle"], me["scopes"]) == ("lab-admin", ["agents", "read"])
    assert cli.main(["repo", "member", "rrsrch/msc-knee-oa", "lab-admin", "reviewer"]) == 0
    assert cli.main(["agent", "revoke", "lab-admin"]) == 0
    assert client.get("/v1/whoami", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def _expiry(url, key_id):
    with psycopg.connect(url) as c:
        return c.execute("SELECT expires_at, idle_days, max_expires_at FROM api_keys WHERE id = %s", (key_id,)).fetchone()


def test_keys_stay_alive_while_used_and_die_when_idle(env, db_url):
    client, admin = env
    client.post("/v1/agents", headers=admin, json={"handle": "acme-loop", "kind": "service"})
    r = client.post("/v1/agents/acme-loop/keys", headers=admin, json={"scopes": ["read"]})
    assert r.status_code == 201 and r.json()["idle_days"] == 90 and "while used" in r.json()["lifetime"]
    key, kid = {"Authorization": f"Bearer {r.json()['key']}"}, r.json()["key_id"]
    with psycopg.connect(db_url) as c:      # as if issued long ago and last used 80 days ago: 10 days left
        c.execute("UPDATE api_keys SET created_at = now() - interval '200 days', "
                  "expires_at = now() + interval '10 days' WHERE id = %s", (kid,))
    assert client.get("/v1/whoami", headers=key).status_code == 200          # using it pushes the end out again
    expires, idle, cap = _expiry(db_url, kid)
    with psycopg.connect(db_url) as c:
        left = c.execute("SELECT %s - now()", (expires,)).fetchone()[0]
    assert idle == 90 and cap is None and left.days >= 89
    with psycopg.connect(db_url) as c:      # 90 days with no use: gone
        c.execute("UPDATE api_keys SET expires_at = now() - interval '1 second' WHERE id = %s", (kid,))
    assert client.get("/v1/whoami", headers=key).status_code == 401

    fixed = client.post("/v1/agents/acme-loop/keys", headers=admin, json={"scopes": ["read"], "days": 7}).json()
    assert fixed["idle_days"] is None and fixed["lifetime"] == "fixed: 7 days"
    before = _expiry(db_url, fixed["key_id"])[0]
    client.get("/v1/whoami", headers={"Authorization": f"Bearer {fixed['key']}"})
    assert _expiry(db_url, fixed["key_id"])[0] == before                      # a fixed key doesn't slide


def test_an_unclaimed_agents_key_slides_only_until_30_days_after_signing_up(env, db_url):
    client, admin = env
    r = client.post("/v1/agents/register", json={"handle": "drifter", "kind": "model", "model": "m",
                                                 "description": "a test agent"})
    assert r.status_code == 201, r.json()
    key, code = {"Authorization": f"Bearer {r.json()['key']}"}, r.json()["claim"]["code"]
    with psycopg.connect(db_url) as c:
        kid = c.execute("SELECT k.id FROM api_keys k JOIN agents a ON a.id = k.agent_id "
                        "WHERE a.handle = 'drifter'").fetchone()[0]
    expires, idle, cap = _expiry(db_url, kid)
    assert idle == 30 and cap is not None and expires <= cap
    with psycopg.connect(db_url) as c:      # signed up 29 days ago: use can't carry it past day 30
        c.execute("UPDATE agents SET created_at = now() - interval '29 days' WHERE handle = 'drifter'")
        c.execute("UPDATE api_keys SET created_at = now() - interval '29 days', max_expires_at = now() + interval '1 day', "
                  "expires_at = now() + interval '1 day' WHERE id = %s", (kid,))
    assert client.get("/v1/whoami", headers=key).status_code == 200
    expires, _, cap = _expiry(db_url, kid)
    assert expires == cap

    # claiming takes the cap away: from then on it lives while used, like any operator's key
    assert client.post("/v1/agents/claim", headers=admin, json={"code": code}).status_code in (200, 201)
    client.get("/v1/whoami", headers=key)
    expires, idle, cap = _expiry(db_url, kid)
    with psycopg.connect(db_url) as c:
        left = c.execute("SELECT %s - now()", (expires,)).fetchone()[0]
    assert cap is None and idle == 30 and left.days >= 29
