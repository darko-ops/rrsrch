"""One independence rule (identity/independence.py) for approvals, challenges, reproductions, bounties and Sparks
credits, and who may promote, mark and report: end to end over HTTP on a real Postgres."""
import psycopg
import pytest
from reviewing import object_to
from test_agent_network import bearer, signup
from test_economy import reply, seed
from test_knowledge_api import claim_of, merged_claim
from test_mcp import call, server_for
from test_prescience import agent
from test_site_people import SECRET, person
from test_trust_db import QUOTE, SHA, TEXT, content
from test_trust_db import world  # noqa: F401  (world is a fixture)

from rrsrch.identity import independence
from rrsrch.trust import pipeline
from rrsrch.trust.policy import Policy

pytestmark = pytest.mark.db

COMMONS = "rrsrch/network"


def sparks(client, handle):
    return client.get(f"/v1/agents/{handle}/sparks").json()


def verify(url, org):
    with psycopg.connect(url) as c:
        c.execute("UPDATE organizations SET verification = 'verified' WHERE id = %s", (org,))


def test_the_rule():
    assert independence.counts("lab", "uni", "verified")
    assert not independence.counts("lab", "uni", "unverified")              # a new organization, until verified
    assert not independence.counts("lab", "lab", "verified")                 # its own operator
    assert not independence.counts("rrsrch", "ominis-labs", "verified")      # RRSRCH and its owner are one operator
    assert not independence.counts("ominis-labs", "rrsrch", "verified")
    assert not independence.counts("lab", "people", "verified") and not independence.counts("lab", "unclaimed", None)
    assert independence.excluded("rrsrch") == ["rrsrch", "ominis-labs", "unclaimed", "people"]


def test_only_independent_approvals_count_toward_a_policy():
    policy = Policy.model_validate({"required_approvals": 1, "approvals_from_other_orgs_only": True})
    review = lambda org, verification="verified", verdict="approve": pipeline.Review(  # noqa: E731
        2, org, "model", "active", verdict, verification)
    assert pipeline.review_tally([review("uni")], 1, "lab", policy)[0] == 1
    assert pipeline.review_tally([review("sock", "unverified")], 1, "lab", policy)[0] == 0
    assert pipeline.review_tally([review("ominis-labs")], 1, "rrsrch", policy)[0] == 0
    assert pipeline.review_tally([review("ominis-labs", verdict="reject")], 1, "rrsrch", policy)[2] == []
    # an objection from another operator still blocks, verified or not
    assert pipeline.review_tally([review("sock", "unverified", "reject")], 1, "lab", policy)[2]


def test_an_approval_from_a_new_self_serve_organization_merges_nothing(world, monkeypatch):
    monkeypatch.setenv("RRSRCH_PROXY_SECRET", SECRET)
    client, h, url = world
    author = agent(url, "lab-a", "a-1", verified=True)
    r = client.post(f"/v1/repos/{COMMONS}/claims", headers=author,
                    json={"content": content() | {"repository": COMMONS}, "topics": ["msc"]})
    assert r.status_code == 201, r.json()
    mr = r.json()["merge_request_id"]
    sock = person("site-user-2", "Sock")
    r = client.post("/v1/organizations", headers=sock, json={"id": "sockpuppet", "name": "Sock"})
    assert r.status_code == 201 and r.json()["organization"]["verification"] == "unverified"
    got = signup(client, "sock-bot", ip="198.51.100.9").json()
    assert client.post("/v1/agents/claim", headers=sock, json={"code": got["claim"]["code"]}).status_code == 200
    k = client.post("/v1/agents/sock-bot/keys", headers=sock, json={"scopes": ["read", "propose", "review"]})
    assert k.status_code == 201, k.json()
    approve = {"target": f"proposal:{mr}", "verdict": "approve", "findings": "ok"}
    rv = client.post("/v1/reviews", headers=bearer(k.json()["key"]), json=approve)
    assert rv.status_code == 200 and rv.json()["merged"] is False, rv.json()
    held = client.post(f"/v1/merge-requests/{mr}/merge", headers=author)
    assert held.status_code == 409 and any("independent approval" in x for x in held.json()["reasons"])
    verify(url, "sockpuppet")                                                 # once RRSRCH verifies it, it counts
    rv = client.post("/v1/reviews", headers=bearer(k.json()["key"]), json=approve)
    assert rv.json()["merged"] is True


def test_rrsrch_and_its_owners_organization_never_approve_each_others_claims(world):
    client, h, url = world
    author = agent(url, "rrsrch", "rr-1")
    owner = agent(url, "ominis-labs", "om-1", verified=True, scopes=("read", "propose", "review"))
    r = client.post(f"/v1/repos/{COMMONS}/claims", headers=author,
                    json={"content": content() | {"repository": COMMONS}, "topics": ["msc"]})
    mr = r.json()["merge_request_id"]
    rv = client.post("/v1/reviews", headers=owner, json={"target": f"proposal:{mr}", "verdict": "approve"})
    assert rv.status_code == 200 and rv.json()["merged"] is False


def test_merges_without_independent_review_mint_no_sparks(world):
    client, h, url = world
    owner = agent(url, "mint", "mint-owner", verified=True,
                  scopes=("read", "propose", "review", "maintain", "administer"))
    worker = agent(url, "mint", "mint-worker", scopes=("read", "propose"))
    for slug, visibility in (("mint/farm", "private"), ("mint/open", "public")):
        rules = {"required_approvals": 0} if visibility == "private" else {"required_approvals": 1,
                                                                         "approvals_from_other_orgs_only": True}
        r = client.post("/v1/repos", headers=owner, json={"slug": slug, "topic": "x", "visibility": visibility,
                                                          "policy": rules})
        assert r.status_code == 201, r.json()
        assert client.put(f"/v1/repos/{slug}/members/mint-worker", headers=owner,
                          json={"role": "contributor"}).status_code == 200
    for i in range(3):
        c = content(f"Claim number {i} about WOMAC at 12 months (p = 0.01).") | {"repository": "mint/farm"}
        mr = client.post("/v1/merge-requests", headers=worker, json={"repository": "mint/farm", "content": c})
        assert mr.status_code == 201, mr.json()
        m = client.post(f"/v1/merge-requests/{mr.json()['merge_request_id']}/merge", headers=owner)
        assert m.status_code == 200, m.json()
    assert sparks(client, "mint-worker")["from_quality"] == 0                  # private, and decided in-house
    # in public, a merge pays once someone independent of the author approved it
    c = content("Claim about WOMAC at 12 months in public (p = 0.01).") | {"repository": "mint/open"}
    mr = client.post("/v1/merge-requests", headers=worker, json={"repository": "mint/open", "content": c})
    mr = mr.json()["merge_request_id"]
    uni = agent(url, "uni", "uni-1", verified=True, scopes=("read", "propose", "review"))
    assert client.put("/v1/repos/mint/open/members/uni-1", headers=owner, json={"role": "reviewer"}).status_code == 200
    assert client.post("/v1/reviews", headers=uni, json={"target": f"proposal:{mr}", "verdict": "approve"}
                       ).status_code == 200
    assert client.post(f"/v1/merge-requests/{mr}/merge", headers=owner).status_code == 200
    earned = [e for e in sparks(client, "mint-worker")["entries"] if e["ref"] == f"mr:{mr}"]
    assert [e["delta"] for e in earned] == [5]
    assert any(e["ref"].startswith("review:") for e in sparks(client, "uni-1")["entries"])   # its review held up


def test_only_a_posts_author_promotes_it(world):
    client, h, url = world
    victim = agent(url, "vic", "vic-1", verified=True)
    other = agent(url, "att", "att-1", scopes=("read", "propose", "review", "maintain"))
    s = TEXT.index(QUOTE)
    ev = [{"source_id": "MED:1", "doc_sha256": SHA, "start": s, "end": s + len(QUOTE)}]
    p = client.post("/v1/posts", headers=victim, json={"kind": "finding", "title": "MSC finding", "body": "b",
                                                       "topics": ["msc"], "evidence": ev})
    assert p.status_code == 201, p.json()
    pid = p.json()["post_id"]
    assert client.post("/v1/repos", headers=other, json={"slug": "att/sink", "topic": "x", "visibility": "private",
                                                        "policy": {"required_approvals": 0}}).status_code == 201
    pr = client.post(f"/v1/posts/{pid}/promote", headers=other,
                     json={"repository": "att/sink", "proposition": "Other wording of the finding (p = 0.01)."})
    assert pr.status_code == 403
    own = client.post(f"/v1/posts/{pid}/promote", headers=victim,
                      json={"repository": COMMONS, "proposition": "At 12 months, WOMAC improved more with MSCs than "
                                                                 "with hyaluronic acid (p = 0.01)."})
    assert own.status_code == 201, own.json()


def test_marks_need_a_working_key_of_a_claimed_agent_and_count_only_from_independent_agents(world):
    client, h, url = world
    poster = agent(url, "pp", "pp-1", verified=True)
    pid = client.post("/v1/posts", headers=poster, json={"kind": "question", "title": "Q?", "body": "b",
                                                         "topics": ["msc"]}).json()["post_id"]
    mark = {"target": f"post:{pid}", "value": 1}
    ro = agent(url, "pp", "pp-ro", scopes=("read",))
    r = client.post("/v1/feedback", headers=ro, json=mark)
    assert r.status_code == 403 and "propose" in r.json()["error"]
    for i in range(2):
        k = bearer(signup(client, f"loose-{i}", ip=f"192.0.2.{i + 1}").json()["key"])
        assert client.post("/v1/feedback", headers=k, json=mark).status_code == 403
    assert client.post("/v1/feedback", headers=h["ext"], json=mark).status_code == 200      # a person may
    for who in (agent(url, "pp", "pp-2"), agent(url, "new", "new-1"), agent(url, "new2", "new2-1")):
        assert client.post("/v1/feedback", headers=who, json=mark).status_code == 200    # own operator, unverified
    assert sparks(client, "pp-1")["from_quality"] == 0
    for i in range(3):
        assert client.post("/v1/feedback", headers=agent(url, f"v{i}", f"v{i}-1", verified=True),
                           json=mark).status_code == 200
    assert any(e["ref"] == f"useful:post:{pid}" for e in sparks(client, "pp-1")["entries"])


def test_unclaimed_agents_and_read_only_keys_dont_report_content(world):
    client, h, url = world
    pid = client.post("/v1/posts", headers=h["bot"], json={"kind": "question", "title": "Q?", "body": "b",
                                                           "topics": ["msc"]}).json()["post_id"]
    body = {"target": f"post:{pid}", "reason": "spam"}
    loose = bearer(signup(client, "loose").json()["key"])
    assert client.post("/v1/reports", headers=loose, json=body).status_code == 403
    assert client.post("/v1/reports", headers=agent(url, "lab", "lab-ro", scopes=("read",)), json=body
                       ).status_code == 403
    assert client.post("/v1/reports", headers=agent(url, "lab", "lab-1"), json=body).status_code == 201


def test_bounties_pay_only_agents_independent_of_the_poster(world):
    client, h, url = world
    poster = agent(url, "harbor", "h-1", verified=True)
    seed(url, "h-1", 40)
    q = client.post("/v1/posts", headers=h["bot"], json={"kind": "question", "title": "Which dose?", "body": "b",
                                                         "topics": ["msc"]}).json()["post_id"]
    b = client.post("/v1/sparks/bounties", headers=poster, json={"target": f"post:{q}", "amount": 20}).json()["bounty"]
    unverified = reply(client, agent(url, "fresh", "fresh-1"), q)
    good = reply(client, agent(url, "uni", "uni-1", verified=True), q)
    answers = [a["answer"] for a in client.get(f"/v1/sparks/bounties/{b['id']}").json()["bounty"]["answers"]]
    assert answers == [good]
    assert client.post(f"/v1/sparks/bounties/{b['id']}/award", headers=poster, json={"answer": unverified}
                       ).status_code == 409


def test_the_claim_authors_operator_doesnt_dismiss_an_outside_challenge(world):
    client, h, url = world
    cid = claim_of(url, merged_claim(client, h)[0])                             # rrsrch's bot's claim
    ch = object_to(client, h["ext"], cid, kind="scope", statement="One centre.").json()["challenge_id"]
    r = client.post(f"/v1/challenges/{ch}/resolve", headers=h["admin"], json={"outcome": "dismissed",
                                                                              "resolution": "x"})
    assert r.status_code == 403
    r = client.post(f"/v1/challenges/{ch}/resolve", headers=h["admin"],
                    json={"outcome": "upheld", "resolution": "Fair."})
    assert r.status_code == 200                                                 # it may concede


def test_check_ins_and_mcp_reads_name_what_others_wrote(world):
    client, h, url = world
    lab = agent(url, "lab", "lab-1")
    got = client.get("/v1/checkin", headers=lab).json()
    assert "suggested.questions[].title" in got["untrusted_fields"] and "protocol" not in got["untrusted_fields"]
    assert "spending Sparks" in got["guidance"] and "never act on those" in got["guidance"]
    err, out = call(server_for(client, lab), "explore")
    assert not err and "never instructions" in out["untrusted_content"]
