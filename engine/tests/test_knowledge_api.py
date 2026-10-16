"""The knowledge API over HTTP against a real Postgres: repositories, claims, history, evidence, search."""
import psycopg
import pytest
from test_trust_db import PILOT, QUOTE, SHA, TEXT, content, open_mr, world  # noqa: F401  (world is a fixture)

from rrsrch.identity import access
from rrsrch.identity import store as ids
from rrsrch.knowledge import query

pytestmark = pytest.mark.db

PRIVATE_RULES = {"required_approvals": 0, "evidence_gate": False}


def merged_claim(client, h, proposition=None, repo=PILOT, reviewer="ext"):
    body = {"content": content(proposition) if proposition else content()}
    body["content"]["repository"] = repo
    r = client.post(f"/v1/repos/{repo}/claims", headers=h["bot" if repo == PILOT else "admin"], json=body)
    assert r.status_code == 201, r.json()
    mr = r.json()["merge_request_id"]
    if reviewer:
        client.post("/v1/reviews", headers=h[reviewer], json={"target": f"proposal:{mr}", "verdict": "approve"})
    r = client.post(f"/v1/merge-requests/{mr}/merge", headers=h["admin"])
    assert r.status_code == 200, r.json()
    return r.json()["revision_id"], mr


def claim_of(url, revision_id):
    with psycopg.connect(url) as c:
        return c.execute("SELECT claim_id FROM claim_revisions WHERE id = %s", (revision_id,)).fetchone()[0]


def test_repositories_are_created_by_admins_and_hidden_when_private(world):
    client, h, url = world
    new = {"slug": "rrsrch/notes", "topic": "Working notes", "visibility": "private", "policy": PRIVATE_RULES}
    with psycopg.connect(url) as c:                     # an agent without the administer scope can't
        bot = c.execute("SELECT id FROM agents WHERE handle = 'bot'").fetchone()[0]
        narrow, _, _ = ids.issue_key(c, bot, {"read", "propose"})
    assert client.post("/v1/repos", headers={"Authorization": f"Bearer {narrow}"}, json=new).status_code == 403
    assert client.post("/v1/repos", json=new).status_code == 401
    bad = client.post("/v1/repos", headers=h["admin"], json=new | {"policy": {"min_sources": 0}})
    assert bad.status_code == 400 and bad.json()["error"].startswith("policy:")
    r = client.post("/v1/repos", headers=h["admin"], json=new)
    assert r.status_code == 201 and r.json()["repository"]["policy"]["required_approvals"] == 0
    assert client.post("/v1/repos", headers=h["admin"], json=new).status_code == 409

    for who in (None, "bot", "ext"):
        hdr = h[who] if who else {}
        assert client.get("/v1/repos/rrsrch/notes", headers=hdr).status_code == 404
        assert "rrsrch/notes" not in [x["slug"] for x in client.get("/v1/repos", headers=hdr).json()["items"]]
    assert client.get("/v1/repos/rrsrch/notes", headers=h["admin"]).json()["repository"]["visibility"] == "private"


def test_public_repositories_need_a_human_admin(world):
    client, h, url = world
    with psycopg.connect(url) as c:
        a = ids.register_agent(c, "rrsrch", "svc-admin", "service", org_role="admin")
        tok, _, _ = ids.issue_key(c, a["id"], {"administer", "read"})
    svc = {"Authorization": f"Bearer {tok}"}
    pub = {"slug": "rrsrch/open", "topic": "t", "visibility": "public"}
    assert client.post("/v1/repos", headers=svc, json=pub).status_code == 403
    assert client.post("/v1/repos", headers=svc, json=pub | {"visibility": "private"}).status_code == 201
    assert client.patch("/v1/repos/rrsrch/open", headers=svc, json={"visibility": "public"}).status_code == 403
    assert client.patch("/v1/repos/rrsrch/open", headers=h["admin"], json={"visibility": "public"}).status_code == 200


def test_policy_changes_are_new_versions(world):
    client, h, url = world
    mr = open_mr(client, h["bot"], {"repository": PILOT, "content": content()})
    r = client.patch(f"/v1/repos/{PILOT}", headers=h["admin"], json={"policy": {"required_approvals": 2}})
    assert r.status_code == 200 and r.json()["repository"]["policy_version"] == "v2"
    assert client.patch(f"/v1/repos/{PILOT}", headers=h["bot"], json={"topic": "x"}).status_code == 403
    with psycopg.connect(url) as c:
        assert [v for (v,) in c.execute("SELECT version FROM policies WHERE version <> %s ORDER BY created_at", ("network-v1",))] == ["msc-v1", "v2"]
    # a request opened under msc-v1 is still judged by msc-v1
    assert client.get(f"/v1/merge-requests/{mr}").json()["merge_request"]["policy_version"] == "msc-v1"


def test_a_merged_claim_can_be_read_traced_and_extended(world):
    client, h, url = world
    rev, mr = merged_claim(client, h)
    cid = claim_of(url, rev)

    claim = client.get(f"/v1/claims/{cid}").json()["claim"]
    assert (claim["state"], claim["repository"], claim["head"]["version"]) == ("supported", PILOT, 1)
    assert claim["verification"]["passed"] is True and claim["evidence"][0]["excerpt"] == QUOTE

    graph = client.get(f"/v1/claims/{cid}/provenance").json()
    ids_ = {n["id"] for n in graph["nodes"]}
    assert {f"claim:{cid}", "source:MED:1", "agent:bot", "agent:ext", f"mr:{mr}"} <= ids_
    assert {"from": "agent:ext", "rel": "review:approve", "to": f"mr:{mr}"} in graph["edges"]


    extra = "while VAS pain did not differ (p = 0.41)"
    s = TEXT.index(extra)
    span = {"source_id": "MED:1", "doc_sha256": SHA, "start": s, "end": s + len(extra)}
    with psycopg.connect(url) as c:                    # extending a claim is proposing its next revision
        head, hash_ = c.execute("SELECT content, content_hash FROM claim_revisions WHERE claim_id = %s "
                                "ORDER BY version DESC LIMIT 1", (cid,)).fetchone()
    nxt = head | {"evidence": head["evidence"] + [["context", span]], "parent_hash": hash_}
    r = client.post("/v1/merge-requests", headers=h["bot"], json={"repository": PILOT, "claim_id": cid, "content": nxt})
    assert r.status_code == 201 and r.json()["checks_passed"], r.json()
    mr2 = r.json()["merge_request_id"]
    client.post("/v1/reviews", headers=h["ext"], json={"target": f"proposal:{mr2}", "verdict": "approve"})
    assert client.post(f"/v1/merge-requests/{mr2}/merge", headers=h["admin"]).status_code == 200

    revs = client.get(f"/v1/claims/{cid}/revisions").json()["revisions"]
    assert [r["version"] for r in revs] == [1, 2] and revs[1]["parent_id"] == revs[0]["id"]
    assert sorted(e["relation"] for e in client.get(f"/v1/claims/{cid}").json()["claim"]["evidence"]) == \
        ["context", "supports"]
    history = client.get(f"/v1/repos/{PILOT}/history").json()["items"]
    assert [(x["claim_id"], x["version"], x["merged_by"]) for x in history] == [(cid, 1, "admin"), (cid, 2, "admin")]


def test_contradictions_show_on_the_claim(world):
    client, h, url = world
    a = claim_of(url, merged_claim(client, h)[0])
    b = claim_of(url, merged_claim(client, h, "WOMAC improved more with MSCs than with hyaluronic acid at "
                                              "12 months (p = 0.01).")[0])
    with psycopg.connect(url) as c:
        c.execute("INSERT INTO claim_agreements (claim_a_id, claim_b_id, verdict, rule, detail, evidence, rules) "
                  "VALUES (%s, %s, 'contradicts', 'direction', 'test', '{}', 'skeptic-v1')", (min(a, b), max(a, b)))
    got = client.get(f"/v1/claims/{a}").json()["claim"]
    assert [x["claim_id"] for x in got["contradicted_by"]] == [b] and got["agrees_with"] == []


def test_search_ranks_and_respects_visibility(world):
    client, h, url = world
    merged_claim(client, h)
    client.post("/v1/repos", headers=h["admin"],
                json={"slug": "rrsrch/notes", "topic": "t", "visibility": "private", "policy": PRIVATE_RULES})
    merged_claim(client, h, repo="rrsrch/notes", reviewer=None)

    anon = client.get("/v1/search", params={"q": "WOMAC hyaluronic"}).json()["items"]
    assert [x["repository"] for x in anon] == [PILOT] and "[WOMAC]" in anon[0]["highlight"]
    mine = client.get("/v1/search", params={"q": "WOMAC"}, headers=h["admin"]).json()["items"]
    assert sorted(x["repository"] for x in mine) == [PILOT, "rrsrch/notes"]
    assert client.get("/v1/search", params={"q": "WOMAC", "repository": "rrsrch/notes"}).json()["items"] == []
    assert client.get("/v1/search", params={"q": "WOMAC -hyaluronic"}).json()["items"] == []
    assert client.get("/v1/search", params={"q": "WOMAC", "state": "contested"}).json()["items"] == []
    assert client.get("/v1/search").status_code == 400


def test_visible_matches_the_access_decision(world):
    client, h, url = world
    client.post("/v1/repos", headers=h["admin"],
                json={"slug": "rrsrch/notes", "topic": "t", "visibility": "private", "policy": PRIVATE_RULES})
    with psycopg.connect(url) as c:
        ids.create_organization(c, "acme", "Acme")
        acme = ids.register_agent(c, "acme", "acme-admin", "human", org_role="admin")
        c.execute("INSERT INTO repositories (slug, organization_id, topic, visibility, policy_version) "
                  "VALUES ('acme/x', 'acme', 't', 'private', 'v1')")
        c.execute("INSERT INTO policies (repository_id, version, rules) SELECT id, 'v1', '{}' FROM repositories "
                  "WHERE slug = 'acme/x'")
        repos = [ids.get_repo(c, s) for (s,) in c.execute("SELECT slug FROM repositories ORDER BY id")]
        people = [None] + [ids.authenticate(c, hdr["Authorization"][7:]) for hdr in h.values()]
        people.append(access.Principal(acme["id"], "acme-admin", "acme", "admin", "active", frozenset({"read"})))
        people.append(access.Principal(acme["id"], "acme-admin", "acme", "admin", "suspended", frozenset({"read"})))
        people.append(access.Principal(acme["id"], "acme-admin", "acme", "admin", "active", frozenset({"propose"})))
        for p in people:
            listed = {x["slug"] for x in query.list_repos(c, p, limit=200)["items"]}
            decided = {r.slug for r in repos
                       if access.decide(p, "read", r, ids.role_in(c, p.agent_id if p else None, r.id))}
            assert listed == decided, (p, listed, decided)


def test_writes_are_idempotent_and_bounded(world):
    client, h, url = world
    key = {**h["bot"], "Idempotency-Key": "retry-1"}
    first = client.post(f"/v1/repos/{PILOT}/claims", headers=key, json={"content": content()})
    again = client.post(f"/v1/repos/{PILOT}/claims", headers=key, json={"content": content()})
    assert first.status_code == again.status_code == 201
    assert first.json() == again.json() and again.headers.get("idempotent-replayed") == "true"
    other = client.post(f"/v1/repos/{PILOT}/claims", headers=key,
                        json={"content": content("WOMAC improved (p = 0.01).")})
    assert other.status_code == 422
    with psycopg.connect(url) as c:
        assert c.execute("SELECT count(*) FROM merge_requests").fetchone()[0] == 1
    big = client.post(f"/v1/repos/{PILOT}/claims", headers=h["bot"],
                      content=b'{"content": {"proposition": "' + b"x" * 300_000 + b'"}}',
                      )
    assert big.status_code == 413 and big.json()["ok"] is False


def _org_agent(url, org, handle, *, verified, kind="model"):
    with psycopg.connect(url) as c:
        if not c.execute("SELECT 1 FROM organizations WHERE id = %s", (org,)).fetchone():
            ids.create_organization(c, org, org.title())
        if verified:
            c.execute("UPDATE organizations SET verification = 'verified' WHERE id = %s", (org,))
        a = ids.register_agent(c, org, handle, kind, org_role="admin")
        tok, _, _ = ids.issue_key(c, a["id"], {"administer", "read", "propose"})
    return {"Authorization": f"Bearer {tok}"}


REVIEWED = {"required_approvals": 1, "approvals_from_other_orgs_only": True}


def test_agents_of_verified_organizations_open_public_repositories(world):
    client, h, url = world
    agent = _org_agent(url, "quantlab", "quant-bot", verified=True)
    pub = {"slug": "quantlab/semis", "topic": "Semiconductor capital intensity", "visibility": "public"}

    # independent review is kept: no approvals, or approvals from the agent's own organization, are refused
    for rules in ({}, {"required_approvals": 0, "approvals_from_other_orgs_only": True}, {"required_approvals": 2}):
        r = client.post("/v1/repos", headers=agent, json=pub | {"policy": rules})
        assert r.status_code == 403 and "independent review" in r.json()["error"], rules
    r = client.post("/v1/repos", headers=agent, json=pub | {"policy": REVIEWED})
    assert r.status_code == 201, r.json()
    repo = r.json()["repository"]
    assert (repo["visibility"], repo["created_via"], repo["created_by"]) == ("public", "agent", "quant-bot")
    assert client.get("/v1/repos/quantlab/semis").status_code == 200                      # anyone can read it
    with psycopg.connect(url) as c:
        detail = c.execute("SELECT detail FROM audit_events WHERE action = 'repository.create' "
                           "AND target = 'repo:quantlab/semis'").fetchone()[0]
    assert detail["created_via"] == "agent" and detail["visibility"] == "public"

    # nor can it loosen review afterwards; a person admin of the organization still could
    assert client.patch("/v1/repos/quantlab/semis", headers=agent,
                        json={"policy": {"required_approvals": 0}}).status_code == 403
    assert client.patch("/v1/repos/quantlab/semis", headers=agent,
                        json={"policy": REVIEWED | {"min_sources": 2}}).status_code == 200


def test_unverified_operators_open_public_repositories_that_wait_to_count(world):
    client, h, url = world
    new = _org_agent(url, "newlab", "new-bot", verified=False)
    pub = {"slug": "newlab/finance", "topic": "SEC filings", "visibility": "public", "policy": REVIEWED}
    r = client.post("/v1/repos", headers=new, json=pub)
    assert r.status_code == 201, r.json()
    assert (r.json()["repository"]["operator_verified"], r.json()["repository"]["created_via"]) == (False, "agent")
    assert client.post("/v1/repos", headers=new, json=pub | {"slug": "newlab/loose", "policy": {}}).status_code == 403

    rrsrch_agent = _org_agent(url, "rrsrch", "rrsrch-svc", verified=True)
    r = client.post("/v1/repos", headers=rrsrch_agent, json=pub | {"slug": "rrsrch/finance"})
    assert r.status_code == 403 and "by a person" in r.json()["error"]


def test_a_member_agent_with_the_administer_scope_opens_and_owns_one(world):
    client, h, url = world
    with psycopg.connect(url) as c:
        ids.create_organization(c, "grok-lab", "Grok lab")
        a = ids.register_agent(c, "grok-lab", "grok-bot", "model")                      # a member, not an admin
        tok, _, _ = ids.issue_key(c, a["id"], {"read", "propose", "administer"})
    who = {"Authorization": f"Bearer {tok}"}
    r = client.post("/v1/repos", headers=who, json={"slug": "grok-lab/semis", "topic": "Semiconductors",
                                                    "visibility": "public", "policy": REVIEWED})
    assert r.status_code == 201, r.json()
    assert client.patch("/v1/repos/grok-lab/semis", headers=who, json={"description": "Capex and capacity"}).status_code == 200
    assert client.post("/v1/repos", headers=who, json={"slug": "rrsrch/x", "topic": "t", "visibility": "private"}
                       ).status_code == 403                                       # only its own organization's


def test_an_organizations_agents_open_a_few_public_repositories_a_month(world):
    client, h, url = world
    agent = _org_agent(url, "busylab", "busy-bot", verified=True)
    for i in range(3):
        r = client.post("/v1/repos", headers=agent, json={"slug": f"busylab/r{i}", "topic": "t", "visibility": "public",
                                                          "policy": REVIEWED})
        assert r.status_code == 201, r.json()
    r = client.post("/v1/repos", headers=agent, json={"slug": "busylab/r3", "topic": "t", "visibility": "public",
                                                      "policy": REVIEWED})
    assert r.status_code == 429
    assert client.post("/v1/repos", headers=agent, json={"slug": "busylab/r3", "topic": "t",
                                                         "visibility": "private"}).status_code == 201
