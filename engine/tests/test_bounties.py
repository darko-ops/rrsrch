"""RRSRCH Bounties, phase 1 (collab/bounties.py), over HTTP on a real Postgres."""
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from test_knowledge_api import claim_of, merged_claim
from test_trust_db import PILOT, content, open_mr, world  # noqa: F401  (world is a fixture)

from rrsrch.collab import standing
from rrsrch.identity import store as ids
from rrsrch.trust import audit

pytestmark = pytest.mark.db


@pytest.fixture
def bw(world, monkeypatch):
    """The world plus: op2 (a second RRSRCH operator, human), sub (an agent of the outside lab, contributor) and
    prof (a human reviewer at another verified organization). Bounties on."""
    monkeypatch.setenv("RRSRCH_BOUNTIES", "on")
    client, h, url = world
    with psycopg.connect(url) as c:
        ids.create_organization(c, "uni", "A university")
        c.execute("UPDATE organizations SET verification = 'verified' WHERE id = 'uni'")
        repo = ids.get_repo(c, PILOT)
        for handle, org, kind, org_role, role in [("op2", "rrsrch", "human", "admin", None),
                                                  ("sub", "lab", "service", "member", "contributor"),
                                                  ("prof", "uni", "human", "member", "reviewer")]:
            a = ids.register_agent(c, org, handle, kind, org_role=org_role)
            if role:
                ids.set_member(c, repo.id, a["id"], role, granted_by=None)
            tok, _, _ = ids.issue_key(c, a["id"], {"read", "propose", "review", "maintain", "administer", "agents"})
            h[handle] = {"Authorization": f"Bearer {tok}"}
    return client, h, url


def soon(days=30):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def contract(cid, **kw):
    return {"category": "correction", "targets": [{"claim": cid}],
            "scope": {"methods": ["public_sources", "source_history"]},
            "rubric": {"criteria": "Show, with a proposal, whether the claim's version range is right.",
                       "requires": ["proposal"]},
            "closes_at": soon()} | kw


def submission(mr, **kw):
    return {"answer": "The fixed version is 1.4.2, not 1.4.0.", "verdict": "resolved",
            "method": "Read the release tags and the fix commit.", "links": {"proposals": [mr]}} | kw


def open_bounty(client, h, url):
    cid = claim_of(url, merged_claim(client, h)[0])
    r = client.post("/v1/bounties", headers=h["admin"], json={"repository": PILOT, "contract": contract(cid),
                                                               "question": "Is the claim's version range right?"})
    assert r.status_code == 201, r.json()
    bid = r.json()["bounty_id"]
    move = lambda who, to: client.post(f"/v1/bounties/{bid}/transition", headers=h[who], json={"to": to})  # noqa: E731
    assert move("admin", "pending_approval").status_code == 200
    assert move("op2", "open").status_code == 200
    return bid, cid


def test_the_switch(world, monkeypatch):
    client, h, _ = world
    monkeypatch.delenv("RRSRCH_BOUNTIES", raising=False)
    assert client.get("/v1/bounties").json() == {"ok": True, "mode": "off", "items": [], "next": None}
    assert client.post("/v1/bounties", headers=h["admin"], json={"repository": PILOT, "contract": {}}).status_code == 404
    monkeypatch.setenv("RRSRCH_BOUNTIES", "operator")
    r = client.post("/v1/bounties", headers=h["admin"], json={"repository": PILOT, "contract": contract(1),
                                                               "question": "q"})
    assert r.status_code == 403 and "private" in r.json()["error"]            # the pilot is public: not in testing


def test_a_bounty_needs_a_second_person_to_open_and_stays_hidden_until_then(bw):
    client, h, url = bw
    cid = claim_of(url, merged_claim(client, h)[0])
    body = {"repository": PILOT, "contract": contract(cid), "question": "Is the claim's version range right?"}
    assert client.post("/v1/bounties", headers=h["bot"], json=body).status_code == 403          # not the owner
    bad = [contract(cid, scope={"methods": ["port_scanning"]}), contract(cid, targets=[{"claim": 99999}]),
           contract(cid, closes_at=soon(400)), contract(cid, reward="sparks"),
           contract(cid, targets=[{"advisory": "not an id", "ecosystem": "pypi", "package": "x"}])]
    for c in bad:
        assert client.post("/v1/bounties", headers=h["admin"], json=body | {"contract": c}).status_code == 400, c
    bid = client.post("/v1/bounties", headers=h["admin"], json=body).json()["bounty_id"]
    assert client.get(f"/v1/bounties/{bid}").status_code == 404                                 # a draft: hidden
    assert client.get("/v1/bounties").json()["items"] == []
    assert client.patch(f"/v1/bounties/{bid}", headers=h["admin"],
                        json={"contract": contract(cid, category="verification")}).status_code == 200
    move = lambda who, to: client.post(f"/v1/bounties/{bid}/transition", headers=h[who], json={"to": to})  # noqa: E731
    assert move("admin", "open").status_code == 409                                             # not yet sent
    assert move("admin", "pending_approval").status_code == 200
    assert client.patch(f"/v1/bounties/{bid}", headers=h["admin"], json={"contract": contract(cid)}).status_code == 409
    assert move("admin", "open").status_code == 403                                             # its creator
    assert move("ext", "open").status_code == 404                                               # can't even see it yet
    assert move("op2", "open").status_code == 200
    got = client.get(f"/v1/bounties/{bid}").json()["bounty"]                                    # now public
    assert (got["state"], got["category"], got["approved_by"], got["pays"]) == \
        ("open", "verification", "op2", "nothing: recognition in Impetus")
    assert got["targets"][0]["claim_state"] == "supported" and "scanning or probing" in got["never"][0]
    assert got["question"]["title"] == "Is the claim's version range right?"
    assert client.get(f"/v1/posts/{got['question']['post_id']}").json()["bounty"]["state"] == "open"
    assert [b["id"] for b in client.get("/v1/bounties", params={"claim": cid}).json()["items"]] == [bid]


def test_who_may_submit_and_what_a_submission_must_carry(bw):
    client, h, url = bw
    bid, cid = open_bounty(client, h, url)
    mr = open_mr(client, h["sub"], {"repository": PILOT, "content": content(
        "At 12 months, WOMAC improved more with MSCs than with hyaluronic acid (p = 0.01).")})
    post = lambda who, c: client.post(f"/v1/bounties/{bid}/submissions", headers=h[who], json={"content": c})  # noqa: E731
    assert post("bot", submission(mr)).status_code == 403                    # the sponsor's own operator
    assert client.post(f"/v1/bounties/{bid}/submissions", json={"content": submission(mr)}).status_code == 401
    assert post("sub", submission(mr, links={})).status_code == 400         # the rubric requires a proposal
    assert post("sub", submission(99999)).status_code == 400                # not a proposal here
    assert post("sub", submission(mr, verdict="certain")).status_code == 400
    r = post("sub", submission(mr))
    assert r.status_code == 201
    sid = r.json()["submission_id"]
    assert post("sub", submission(mr)).status_code == 409                   # one per agent
    sub = client.get(f"/v1/submissions/{sid}").json()["submission"]
    assert sub["state"] == "under_review" and sub["current"]["verdict"] == "resolved" and len(sub["revisions"]) == 1
    task = client.get(f"/v1/tasks/{sub['task_id']}").json()["task"]
    assert (task["state"], task["assignee"]) == ("in_progress", "sub")
    # several agents can work on a bounty's question at once
    assert post("prof", submission(mr, answer="Same, from the changelog.")).status_code == 201


def test_independent_people_judge_and_a_judgment_never_moves_the_claim(bw):
    client, h, url = bw
    bid, cid = open_bounty(client, h, url)
    mr = open_mr(client, h["sub"], {"repository": PILOT, "content": content(
        "At 12 months, WOMAC improved more with MSCs than with hyaluronic acid (p = 0.01).")})
    sid = client.post(f"/v1/bounties/{bid}/submissions", headers=h["sub"],
                      json={"content": submission(mr)}).json()["submission_id"]
    judge = lambda who, d, why="Checked the tags.": client.post(  # noqa: E731
        f"/v1/submissions/{sid}/judgments", headers=h[who], json={"decision": d, "reasons": why})
    assert judge("ext", "accepted").status_code == 403          # the submitter's operator
    assert judge("admin", "accepted").status_code == 403        # the bounty's creator
    assert judge("bot", "accepted").status_code == 403          # no reviewer role
    assert judge("op2", "needs_info").status_code == 201
    r = client.post(f"/v1/submissions/{sid}/revisions", headers=h["sub"],
                    json={"content": submission(mr, limitations="Only the PyPI releases.")})
    assert r.status_code == 201
    assert judge("op2", "rejected", "The proposal doesn't cite the fix commit.").status_code == 201
    sub = client.get(f"/v1/submissions/{sid}").json()["submission"]
    assert sub["state"] == "rejected" and [j["decision"] for j in sub["judgments"]] == ["needs_info", "rejected"]
    assert sub["judgments"][1]["revision_id"] == sub["revisions"][1]["id"]
    assert client.get(f"/v1/tasks/{sub['task_id']}").json()["task"]["state"] == "failed"
    assert client.get(f"/v1/claims/{cid}").json()["claim"]["state"] == "supported"     # untouched
    with psycopg.connect(url) as c, pytest.raises(psycopg.errors.RaiseException):
        c.execute("UPDATE bounty_judgments SET decision = 'accepted'")

    # one appeal, to someone who hasn't judged it
    assert client.post(f"/v1/submissions/{sid}/appeal", headers=h["ext"], json={"reason": "x"}).status_code == 403
    assert client.post(f"/v1/submissions/{sid}/appeal", headers=h["sub"],
                       json={"reason": "The commit is cited in the second revision."}).status_code == 201
    assert judge("op2", "accepted").status_code == 403
    assert judge("prof", "needs_info").status_code == 400
    assert judge("prof", "accepted", "It is cited; the first judgment missed it.").status_code == 201
    sub = client.get(f"/v1/submissions/{sid}").json()["submission"]
    assert sub["state"] == "accepted" and sub["judgments"][-1]["on_appeal"] and sub["appeal"]["reason"]
    assert client.post(f"/v1/submissions/{sid}/appeal", headers=h["sub"], json={"reason": "again"}).status_code == 409
    assert client.get(f"/v1/claims/{cid}").json()["claim"]["state"] == "supported"

    # bounties pay nothing: the accepted submission's task earns no Sparks, and Impetus shows it only when enabled
    with psycopg.connect(url) as c:
        agent = c.execute("SELECT id FROM agents WHERE handle = 'sub'").fetchone()[0]
        assert [k for k, _, _ in standing._outcomes(c, agent) if k == "task_completed"] == []
        assert "bounty_results" not in [m["metric"] for m in standing.outcomes(c, None, agent)]
        assert audit.verify(c) == []


def test_bounty_results_show_in_impetus_once_enabled(bw, monkeypatch):
    client, h, url = bw
    bid, _ = open_bounty(client, h, url)
    mr = open_mr(client, h["sub"], {"repository": PILOT, "content": content()})
    sid = client.post(f"/v1/bounties/{bid}/submissions", headers=h["sub"],
                      json={"content": submission(mr, verdict="could_not_determine")}).json()["submission_id"]
    client.post(f"/v1/submissions/{sid}/judgments", headers=h["op2"],
                json={"decision": "accepted", "reasons": "The evidence doesn't settle it, and says why."})
    monkeypatch.setenv("RRSRCH_BOUNTY_IMPETUS", "on")
    with psycopg.connect(url) as c:
        agent = c.execute("SELECT id FROM agents WHERE handle = 'sub'").fetchone()[0]
        m = next(x for x in standing.outcomes(c, None, agent) if x["metric"] == "bounty_results")
    assert (m["count"], m["of"], m["detail"]["accepted_inconclusive"]) == (1, 1, 1)


def test_a_rubric_can_refuse_inconclusive_answers(bw):
    client, h, url = bw
    cid = claim_of(url, merged_claim(client, h)[0])
    c = contract(cid, rubric={"criteria": "A definite answer.", "accept_inconclusive": False})
    bid = client.post("/v1/bounties", headers=h["admin"], json={"repository": PILOT, "contract": c,
                                                                 "question": "Definitely?"}).json()["bounty_id"]
    client.post(f"/v1/bounties/{bid}/transition", headers=h["admin"], json={"to": "pending_approval"})
    client.post(f"/v1/bounties/{bid}/transition", headers=h["op2"], json={"to": "open"})
    sid = client.post(f"/v1/bounties/{bid}/submissions", headers=h["sub"], json={"content": submission(
        0, verdict="could_not_determine", links={})}).json()["submission_id"]
    r = client.post(f"/v1/submissions/{sid}/judgments", headers=h["op2"], json={"decision": "accepted", "reasons": "x"})
    assert r.status_code == 409 and "inconclusive" in r.json()["error"]


def test_an_upheld_challenge_reopens_review_and_resolving_waits_for_decisions(bw):
    client, h, url = bw
    bid, _ = open_bounty(client, h, url)
    mr = open_mr(client, h["sub"], {"repository": PILOT, "content": content()})
    sid = client.post(f"/v1/bounties/{bid}/submissions", headers=h["sub"],
                      json={"content": submission(mr)}).json()["submission_id"]
    assert client.post(f"/v1/submissions/{sid}/challenges", headers=h["ext"],
                       json={"statement": "Too early."}).status_code == 409                # nothing judged yet
    client.post(f"/v1/submissions/{sid}/judgments", headers=h["op2"], json={"decision": "accepted", "reasons": "ok"})
    assert client.post(f"/v1/submissions/{sid}/challenges", headers=h["op2"],
                       json={"statement": "x"}).status_code == 403                         # the judge
    r = client.post(f"/v1/submissions/{sid}/challenges", headers=h["ext"],
                    json={"statement": "The fix landed in 1.4.3; see the tag.", "evidence": ["https://example.org/t"]})
    assert r.status_code == 201
    ch = r.json()["challenge_id"]
    move = lambda to: client.post(f"/v1/bounties/{bid}/transition", headers=h["admin"], json={"to": to})  # noqa: E731
    assert move("in_review").status_code == 200
    assert move("resolved").status_code == 409                                 # an open challenge
    assert client.post(f"/v1/bounty-challenges/{ch}/resolve", headers=h["op2"],
                       json={"outcome": "upheld"}).status_code == 403          # the judge
    assert client.post(f"/v1/bounty-challenges/{ch}/resolve", headers=h["admin"],
                       json={"outcome": "upheld", "resolution": "Fair: re-judge."}).json()["state"] == "upheld"
    sub = client.get(f"/v1/submissions/{sid}").json()["submission"]
    assert sub["state"] == "under_review" and sub["judgments"][0]["decision"] == "accepted"   # history kept
    assert move("resolved").status_code == 409
    client.post(f"/v1/submissions/{sid}/judgments", headers=h["prof"], json={"decision": "partially_accepted",
                                                                             "reasons": "Right range, wrong tag."})
    assert move("resolved").status_code == 200 and move("closed").status_code == 200
    events = [e["action"] for e in client.get(f"/v1/bounties/{bid}/activity").json()["events"]]
    assert events[:4] == ["bounty.create", "bounty.pending_approval", "bounty.open", "bounty.submit"]
    assert events[-2:] == ["bounty.resolved", "bounty.closed"]


def test_the_window_closes_by_itself_and_caps_hold(bw):
    client, h, url = bw
    bid, _ = open_bounty(client, h, url)
    with psycopg.connect(url) as c:
        c.execute("UPDATE bounties SET closes_at = now() - interval '1 minute' WHERE id = %s", (bid,))
    assert client.get(f"/v1/bounties/{bid}").json()["bounty"]["state"] == "expired"           # nobody submitted
    bid2, _ = open_bounty(client, h, url)
    with psycopg.connect(url) as c:
        c.execute("UPDATE bounties SET max_per_operator = 1 WHERE id = %s", (bid2,))
        lab = ids.register_agent(c, "lab", "sub2", "service")
        ids.set_member(c, ids.get_repo(c, PILOT).id, lab["id"], "contributor", granted_by=None)
        tok, _, _ = ids.issue_key(c, lab["id"], {"read", "propose"})
    mr = open_mr(client, h["sub"], {"repository": PILOT, "content": content()})
    assert client.post(f"/v1/bounties/{bid2}/submissions", headers=h["sub"],
                       json={"content": submission(mr)}).status_code == 201
    r = client.post(f"/v1/bounties/{bid2}/submissions", headers={"Authorization": f"Bearer {tok}"},
                    json={"content": submission(mr)})
    assert r.status_code == 409 and "operator" in r.json()["error"]
    with psycopg.connect(url) as c:
        c.execute("UPDATE bounties SET closes_at = now() - interval '1 minute' WHERE id = %s", (bid2,))
    assert client.get(f"/v1/bounties/{bid2}").json()["bounty"]["state"] == "in_review"
    assert client.post(f"/v1/bounties/{bid2}/transition", headers=h["admin"],
                       json={"to": "canceled", "note": "Duplicate."}).status_code == 200
    subs = client.get(f"/v1/bounties/{bid2}").json()["bounty"]["submissions_detail"]
    assert subs[0]["state"] == "withdrawn"
