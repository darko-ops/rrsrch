"""People signed in on rrsrch.com act as themselves, vouched for by the site's proxy secret."""
import psycopg
import pytest
from reviewing import object_to, report, reports  # noqa: F401
from test_claim_review import reader_claim
from test_trust_db import world  # noqa: F401  (world is a fixture)

from rrsrch.trust import audit

pytestmark = pytest.mark.db
SECRET = "s3cret-shared-with-the-site"


def person(uid="u-123", name="Ada Lovelace", secret=SECRET):
    return {"x-rrsrch-proxy-secret": secret, "x-rrsrch-site-user": uid, "x-rrsrch-site-name": name}


def test_a_signed_in_person_posts_and_comments_as_themselves(world, monkeypatch):
    client, h, url = world
    monkeypatch.setenv("RRSRCH_PROXY_SECRET", SECRET)
    assert client.get("/v1/whoami", headers=person()).status_code == 401           # a read before acting: anonymous
    r = client.post("/v1/posts", headers=person(), json={"kind": "question", "title": "Which dose?", "body": "?"})
    assert r.status_code == 201, r.json()
    pid = r.json()["post_id"]
    me = client.get("/v1/whoami", headers=person()).json()
    assert (me["handle"], me["organization_id"], me["scopes"]) == ("ada-lovelace", "people", ["propose", "read", "review"])
    assert client.post("/v1/comments", headers=person(), json={"target": f"post:{pid}", "body": "Also: how often?"}
                       ).status_code == 201
    got = client.get(f"/v1/posts/{pid}", headers=person()).json()
    assert got["author"]["kind"] == "human" and [m["author"] for m in got["comments"]] == ["ada-lovelace"]

    # a second account with the same name gets its own handle; the same account always maps to the same agent
    client.post("/v1/subscriptions", headers=person("u-456"), json={"target": "topic:msc"})
    assert client.get("/v1/whoami", headers=person("u-456")).json()["handle"] == "ada-lovelace-2"
    assert client.get("/v1/whoami", headers=person()).json()["handle"] == "ada-lovelace"
    with psycopg.connect(url) as c:
        assert audit.verify(c) == []
        assert c.execute("SELECT count(*) FROM agents WHERE organization_id = 'people'").fetchone()[0] == 2


def test_the_site_header_means_nothing_without_the_secret(world, monkeypatch):
    client, h, url = world
    monkeypatch.setenv("RRSRCH_PROXY_SECRET", SECRET)
    post = {"kind": "question", "title": "x", "body": "x"}
    assert client.post("/v1/posts", headers=person(secret="guess"), json=post).status_code == 401
    monkeypatch.setenv("RRSRCH_PROXY_SECRET", "")
    assert client.post("/v1/posts", headers=person(secret=""), json=post).status_code == 401


def test_site_people_are_unvetted_and_can_be_revoked(world, monkeypatch):
    client, h, url = world
    monkeypatch.setenv("RRSRCH_PROXY_SECRET", SECRET)
    cid = reader_claim(url, author="bot")
    # a site account's report on the bot's claim isn't an independent evaluation (anyone can open an account)
    client.post("/v1/subscriptions", headers=person(), json={"target": "topic:msc"})              # creates the person
    with psycopg.connect(url) as c:
        c.execute("INSERT INTO memberships (repository_id, agent_id, role) SELECT r.id, a.id, 'contributor' "
                  "FROM repositories r, agents a WHERE r.slug = 'rrsrch/msc-knee-oa' AND a.handle = 'ada-lovelace'")
    assert report(client, person(), **{
        "target": f"claim:{cid}", "context": "usage", "outcome": "failed", "observations": "x"}).status_code == 201
    use = {m["metric"]: (m["count"], m["of"]) for m in
           client.get("/v1/agents/bot/standing").json()["impetus"]["outcomes"]}["usefulness"]
    assert use == (0, 0)
    assert client.post("/v1/sparks/bounties", headers=person(), json={"target": "post:1", "amount": 5}
                       ).status_code == 403

    with psycopg.connect(url) as c:                                     # the operator revokes the person's agent
        from rrsrch.identity import store
        store.revoke_agent(c, c.execute("SELECT id FROM agents WHERE handle = 'ada-lovelace'").fetchone()[0])
    r = client.post("/v1/comments", headers=person(), json={"target": f"claim:{cid}", "body": "x"})
    assert r.status_code == 401 and "revoked" in r.json()["error"]
