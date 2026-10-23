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


def test_an_admin_signed_in_on_the_site_works_the_report_queue(world, monkeypatch):
    client, h, url = world
    monkeypatch.setenv("RRSRCH_PROXY_SECRET", SECRET)
    r = client.post("/v1/posts", headers=h["bot"], json={"kind": "finding", "title": "t", "body": "t"})
    pid = r.json()["post_id"]
    client.post("/v1/subscriptions", headers=person("u-9", "Owner"), json={"target": "topic:msc"})   # signs them up
    with psycopg.connect(url) as c:
        c.execute("UPDATE agents SET organization_id = 'rrsrch', org_role = 'admin' WHERE site_user_id = 'u-9'")
    owner = person("u-9", "Owner")
    assert "maintain" in client.get("/v1/whoami", headers=owner).json()["scopes"]
    # nothing reported yet, but they could act on reports; someone without a role can't, and sees nothing
    assert client.get("/v1/reports", headers=owner).json() == {"ok": True, "items": [], "maintains": True}
    rid = client.post("/v1/reports", headers=h["ext"], json={"target": f"post:{pid}", "reason": "other",
                                                             "detail": "a test post"}).json()["report_id"]
    assert client.get("/v1/reports", headers=h["ext"]).json() == {"ok": True, "items": [], "maintains": False}
    item = client.get("/v1/reports", headers=owner).json()["items"][0]
    assert (item["id"], item["target"], item["repository"], item["reason"], item["reporter"]) == \
        (rid, f"post:{pid}", "rrsrch/network", "other", "ext")
    assert (item["author"], item["excerpt"], item["detail"]) == ("bot", "finding: t", "a test post")
    hid = client.post(f"/v1/reports/{rid}/resolve", headers=owner, json={"action": "hide"})
    assert hid.json()["state"] == "actioned"
    assert client.get("/v1/reports", headers=owner).json()["items"] == []
    assert client.get("/v1/reports", headers=owner, params={"state": "actioned"}).json()["items"][0]["id"] == rid
    with psycopg.connect(url) as c:
        assert c.execute("SELECT moderation FROM research_posts WHERE id = %s", (pid,)).fetchone()[0] == "hidden"
    # "other" costs the author nothing: only spam, abuse and prompt injection are penalized
    assert all(e["kind"] != "penalty" for e in client.get("/v1/agents/bot/sparks").json()["entries"])
    assert client.get("/v1/reports").status_code == 401


def test_a_person_picks_their_handle_and_keeps_the_old_one(world, monkeypatch):
    client, h, url = world
    monkeypatch.setenv("RRSRCH_PROXY_SECRET", SECRET)
    pid = client.post("/v1/posts", headers=person(), json={"kind": "question", "title": "Which dose?", "body": "?"}
                      ).json()["post_id"]
    assert client.post("/v1/subscriptions", headers=h["ext"], json={"target": "agent:ada-lovelace"}).status_code < 300
    assert client.post("/v1/comments", headers=h["ext"], json={"target": f"post:{pid}", "body": "@ada-lovelace see"}
                       ).status_code == 201
    me = client.get("/v1/whoami", headers=person()).json()
    assert me["handle_change"]["allowed"] is True and me["handle_change"]["previous"] == []

    for bad, status in [("ab", 400), ("-ada", 400), ("ada--l", 400), ("Ada Lovelace", 400), ("rrsrch-ada", 400),
                        ("ext", 409)]:
        assert client.post("/v1/me/handle", headers=person(), json={"handle": bad}).status_code == status, bad
    r = client.post("/v1/me/handle", headers=person(), json={"handle": "@Ada"})
    assert r.status_code == 200 and (r.json()["handle"], r.json()["previous"]) == ("ada", ["ada-lovelace"])
    assert client.get("/v1/whoami", headers=person()).json()["handle"] == "ada"
    got = client.get(f"/v1/posts/{pid}").json()
    assert got["post"]["author"] == "ada"
    assert client.get("/v1/agents/ada-lovelace").json()["agent"]["handle"] == "ada"      # an old link still finds her
    # the follow moved with her; the mention made before still reaches her
    with psycopg.connect(url) as c:
        assert c.execute("SELECT count(*) FROM subscriptions WHERE target = 'agent:ada'").fetchone()[0] == 1
        assert audit.verify(c) == []
    inbox = client.get("/v1/inbox", headers=person()).json()["items"]
    assert any(i["type"] == "mention" for i in inbox)

    # nobody else can take the old handle; she can't change again within the week; an agent can't change at all
    client.post("/v1/subscriptions", headers=person("u-9", "Grace"), json={"target": "topic:msc"})
    assert client.post("/v1/me/handle", headers=person("u-9", "Grace"), json={"handle": "ada-lovelace"}
                       ).status_code == 409
    again = client.post("/v1/me/handle", headers=person(), json={"handle": "ada-l"})
    assert again.status_code == 429 and "7 days" in again.json()["error"]
    assert client.get("/v1/whoami", headers=person()).json()["handle_change"]["allowed"] is False
    assert client.post("/v1/me/handle", headers=h["ext"], json={"handle": "ext-2"}).status_code == 403
    assert client.get("/v1/whoami", headers=h["ext"]).json()["handle_change"] is None
    # after the week, she can go back to her old handle
    with psycopg.connect(url) as c:
        c.execute("UPDATE agents SET handle_changed_at = now() - interval '8 days' WHERE handle = 'ada'")
    back = client.post("/v1/me/handle", headers=person(), json={"handle": "ada-lovelace"}).json()
    assert (back["handle"], back["previous"]) == ("ada-lovelace", ["ada"])
