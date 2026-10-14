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
        root, _, _ = store.issue_key(c, admin["id"], {"agents", "read", "administer"}, days=7)
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


def test_revocation_cuts_off_keys(env):
    client, admin = env
    bot, key_id = new_agent(client, admin, "acme-bot", ["read"])
    second = client.post("/v1/agents/acme-bot/keys", headers=bot, json={"scopes": ["read"]}).json()
    assert client.post(f"/v1/keys/{key_id}/revoke", headers=bot).json()["revoked"] is True
    assert client.get("/v1/whoami", headers=bot).status_code == 401
    bot2 = {"Authorization": f"Bearer {second['key']}"}
    assert client.get("/v1/whoami", headers=bot2).status_code == 200
    r = client.post("/v1/agents/acme-bot/revoke", headers=admin).json()
    assert r["keys_revoked"] == 1
    assert client.get("/v1/whoami", headers=bot2).status_code == 401
    assert client.get("/v1/agents/acme-bot").json()["agent"]["status"] == "revoked"
    r = client.post("/v1/agents/acme-bot/keys", headers=admin, json={"scopes": ["read"]})
    assert r.status_code == 409


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
                       json={"scopes": ["read"], "days": 91}).status_code == 400
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
