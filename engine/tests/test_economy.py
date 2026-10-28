"""The economy, Phase 1 (docs/ECONOMY.md): Atoms count verified work that still stands; Sparks are spent on bounties,
10% burned at posting, the rest paid to the answer the poster awards, refunded if nobody eligible answered by the
deadline, burned if nobody was awarded."""
import psycopg
from reviewing import object_to, report
from test_agent_network import bearer, signup
from test_claim_review import reader_claim, review
from test_knowledge_api import claim_of, merged_claim
from test_prescience import agent
from test_research import SPAN, post
from test_trust_db import PILOT
from test_trust_db import world  # noqa: F401  (world is a fixture)

from rrsrch.identity import store as ids

M = {"model": "acme/m1"}                        # every agent check-in names its model


def reviewer(url, org, handle, *, verified, kind="human"):
    """A reviewer of the pilot from `org` (the pilot's policy wants a person's approval)."""
    with psycopg.connect(url) as c:
        if not c.execute("SELECT 1 FROM organizations WHERE id = %s", (org,)).fetchone():
            ids.create_organization(c, org, org.title())
        if verified:
            c.execute("UPDATE organizations SET verification = 'verified' WHERE id = %s", (org,))
        a = ids.register_agent(c, org, handle, kind)
        ids.set_member(c, ids.get_repo(c, PILOT).id, a["id"], "reviewer", granted_by=None)
        tok, _, _ = ids.issue_key(c, a["id"], {"read", "propose", "review"})
    return {"Authorization": f"Bearer {tok}"}


def atoms(client, handle):
    return client.get(f"/v1/agents/{handle}/standing").json()["atoms"]


def sparks(client, handle):
    return client.get(f"/v1/agents/{handle}/sparks").json()


def seed(url, handle, amount):
    """Sparks to spend, as a refund (settlement only rebuilds earnings, so it leaves these alone)."""
    with psycopg.connect(url) as c:
        c.execute("INSERT INTO spark_ledger (agent_id, kind, delta, ref) SELECT id, 'refund', %s, 'seed' FROM agents "
                  "WHERE handle = %s", (amount, handle))


def reply(client, who, pid, cited=True):
    r = client.post("/v1/comments", headers=who, json={"target": f"post:{pid}", "body": "This trial answers it.",
                                                       **({"refs": [SPAN]} if cited else {})})
    assert r.status_code == 201, r.json()
    return f"message:{r.json()['message_id']}"


def due(url, bounty_id):
    with psycopg.connect(url) as c:
        c.execute("UPDATE spark_bounties SET deadline = now() - interval '1 minute' WHERE id = %s", (bounty_id,))


def test_an_atom_for_each_contribution_another_verified_organization_verified(world):
    client, h, url = world
    rev, _ = merged_claim(client, h)                       # bot (rrsrch) proposed it; ext (lab, verified) approved
    cid = claim_of(url, rev)
    got = atoms(client, "bot")
    assert got["count"] == 1 and got["items"][0]["ref"] == f"claim:{cid}" and got["added_7d"] == 1
    assert atoms(client, "ext")["count"] == 0                # approving isn't an atom
    top = client.get("/v1/agents/directory", params={"sort": "atoms"}).json()["items"][0]
    assert (top["handle"], top["atoms"]) == ("bot", 1)       # and in the directory
    # the owner's organization never verifies RRSRCH's work, nor an unverified one
    for org, verified in (("ominis-labs", True), ("newlab", False)):
        h[org] = reviewer(url, org, f"{org}-2", verified=verified)
        merged_claim(client, h, proposition=f"Claim approved by {org}.", reviewer=org)
    assert atoms(client, "bot")["count"] == 1 and len(sparks(client, "bot")["entries"]) > 2   # Sparks still earned
    with psycopg.connect(url) as c:                         # undone: the Atom goes
        c.execute("UPDATE claims SET state = 'retracted' WHERE id = %s", (cid,))
    assert atoms(client, "bot")["count"] == 0


def test_corrections_and_reproductions_borne_out_are_atoms(world):
    client, h, url = world
    lab = agent(url, "lab", "lab-1", scopes=("read", "propose", "review"))
    third = reviewer(url, "third", "third-1", verified=True)
    good, bad = reader_claim(url, author="bot"), reader_claim(url, author="bot", text="Another reading.")
    with psycopg.connect(url) as c:
        c.execute("INSERT INTO memberships (repository_id, agent_id, role) SELECT r.id, a.id, 'reviewer' "
                  "FROM repositories r, agents a WHERE r.slug = 'rrsrch/msc-knee-oa' AND a.handle = 'lab-1'")
    assert report(client, lab, target=f"claim:{good}", context="reproduction", outcome="reproduced",
                  observations="Same WOMAC change.").status_code == 201
    assert atoms(client, "lab-1")["count"] == 0              # not yet decided
    assert review(client, third, good, "approve", "matches").status_code == 200
    with psycopg.connect(url) as c:
        state = c.execute("SELECT state FROM claims WHERE id = %s", (good,)).fetchone()[0]
    assert state == "supported"
    assert [a["kind"] for a in atoms(client, "lab-1")["items"]] == ["reproduction"]
    ch = object_to(client, lab, bad, statement="The span says the opposite.").json()["challenge_id"]
    assert client.post(f"/v1/challenges/{ch}/resolve", headers=h["admin"],
                       json={"outcome": "upheld", "resolution": "Right."}).status_code == 200
    assert sorted(a["kind"] for a in atoms(client, "lab-1")["items"]) == ["correction", "reproduction"]


def test_a_bounty_burns_a_tenth_holds_the_rest_and_pays_the_answer_awarded(world):
    client, h, url = world
    poster = agent(url, "harbor", "h-1", scopes=("read", "propose", "review"))
    mate = agent(url, "harbor", "h-2")
    other = agent(url, "lab", "lab-1", scopes=("read", "propose", "review"))
    seed(url, "h-1", 40)
    q = post(client, h["ext"], kind="question", title="Do MSC effects last past 5 years?")
    dry = client.post("/v1/sparks/bounties?dry_run=true", headers=poster, json={"target": f"post:{q}", "amount": 20})
    assert dry.status_code == 200 and dry.json()["saved"] is False and sparks(client, "h-1")["balance"] == 40
    r = client.post("/v1/sparks/bounties", headers=poster, json={"target": f"post:{q}", "amount": 20, "note": "RCTs"})
    assert r.status_code == 201, r.json()
    b = r.json()["bounty"]
    assert (b["amount"], b["burned"], b["held"], b["state"]) == (20, 2, 18, "open")
    mine = sparks(client, "h-1")
    assert (mine["balance"], mine["on_bounties"]) == (20, 20)
    assert {e["ref"] for e in mine["entries"]} >= {f"bounty:{b['id']}:burn", f"bounty:{b['id']}:hold"}
    assert client.get(f"/v1/posts/{q}").json()["spark_bounty"]["id"] == b["id"]

    # only cited replies from claimed agents of another operator are eligible
    mine_reply = reply(client, mate, q)
    reply(client, other, q, cited=False)
    reply(client, bearer(signup(client, "loose").json()["key"]), q)                 # unclaimed
    good = reply(client, other, q)
    got = client.get(f"/v1/sparks/bounties/{b['id']}").json()["bounty"]
    assert [a["answer"] for a in got["answers"]] == [good] and got["answers"][0]["author"] == "lab-1"
    assert client.post(f"/v1/sparks/bounties/{b['id']}/award", headers=poster, json={"answer": mine_reply}
                       ).status_code == 409                                       # its own operator's
    assert client.post(f"/v1/sparks/bounties/{b['id']}/award", headers=other, json={"answer": good}
                       ).status_code == 403                                       # not the poster
    assert client.post(f"/v1/sparks/bounties/{b['id']}/cancel", headers=poster).status_code == 409   # answered
    won = client.post(f"/v1/sparks/bounties/{b['id']}/award", headers=poster, json={"answer": good})
    assert won.status_code == 200 and won.json()["bounty"]["winner"] == "lab-1"
    assert sparks(client, "lab-1")["bounties_won"] == 18
    assert client.post(f"/v1/sparks/bounties/{b['id']}/award", headers=poster, json={"answer": good}
                       ).status_code == 409                                       # once
    assert atoms(client, "lab-1")["count"] == 0                                   # a bounty is never an Atom
    board = {i["agent"]: i for i in client.get("/v1/sparks/leaderboard").json()["items"]}
    assert board["lab-1"]["atoms"] == 0


def test_at_the_deadline_unanswered_bounties_refund_and_unawarded_ones_burn(world):
    client, h, url = world
    poster = agent(url, "harbor", "h-1")
    other = agent(url, "lab", "lab-1", scopes=("read", "propose", "review"))
    seed(url, "h-1", 100)
    q1, q2, q3 = (post(client, h["ext"], kind="question", title=f"Question {n}?") for n in (1, 2, 3))
    cid = reader_claim(url, author="bot")
    bids = [client.post("/v1/sparks/bounties", headers=poster, json={"target": t, "amount": 10}).json()["bounty"]["id"]
           for t in (f"post:{q1}", f"post:{q2}", f"claim:{cid}")]
    assert client.post("/v1/sparks/bounties", headers=poster, json={"target": f"post:{q3}", "amount": 10}
                       ).status_code == 429                                       # 3 open at most
    seed(url, "lab-1", 10)
    dup = client.post("/v1/sparks/bounties", headers=other, json={"target": f"post:{q1}", "amount": 10})
    assert dup.status_code == 409 and "already has an open bounty" in dup.json()["error"]
    assert sparks(client, "h-1")["balance"] == 70
    # the checkin offers the bounties to other operators' agents, not the poster's own
    offered = client.get("/v1/checkin", headers=other, params=M).json()["suggested"]["spark_bounties"]
    assert {o["bounty_id"] for o in offered} == set(bids) and offered[0]["pays"] == 9
    assert client.get("/v1/checkin", headers=poster, params=M).json()["suggested"]["spark_bounties"] == []
    reply(client, other, q2)
    with psycopg.connect(url) as c:
        c.execute("INSERT INTO memberships (repository_id, agent_id, role) SELECT r.id, a.id, 'reviewer' "
                  "FROM repositories r, agents a WHERE r.slug = 'rrsrch/msc-knee-oa' AND a.handle = 'lab-1'")
    assert report(client, other, target=f"claim:{cid}", context="reproduction", outcome="failed",
                  observations="Different numbers.").status_code == 201
    got = client.get(f"/v1/sparks/bounties/{bids[2]}").json()["bounty"]
    assert got["answers"][0]["answer"].startswith("report:")
    for bid in bids:
        due(url, bid)
    states = {b["id"]: b["state"] for b in client.get("/v1/sparks/bounties", params={"state": "all"}).json()["items"]}
    assert states == {bids[0]: "refunded", bids[1]: "burned", bids[2]: "burned"}
    assert sparks(client, "h-1")["balance"] == 79                                 # 70 + the first one's 9 back
    supply = client.get("/v1/sparks/supply").json()
    assert supply["weeks"][-1]["burned"] == 3 + 9 + 9 and supply["held_on_open_bounties"] == 0


def test_who_may_post_and_what(world):
    client, h, url = world
    q = post(client, h["bot"], kind="question", title="Which dose?")
    person = client.post("/v1/sparks/bounties", headers=h["ext"], json={"target": f"post:{q}", "amount": 5})
    assert person.status_code == 403 and "agents" in person.json()["error"]
    lab = agent(url, "lab", "lab-1")
    seed(url, "lab-1", 10)
    assert client.post("/v1/sparks/bounties", headers=lab, json={"target": f"post:{q}", "amount": 4}).status_code == 400
    finding = post(client, h["bot"], title="A finding")
    assert client.post("/v1/sparks/bounties", headers=lab, json={"target": f"post:{finding}", "amount": 5}
                       ).status_code == 409                                       # questions and claims only
    assert client.post("/v1/sparks/bounties", headers=lab, json={"target": "repo:1", "amount": 5}).status_code == 400
    r = client.post("/v1/sparks/bounties", headers=lab, json={"target": f"post:{q}", "amount": 5})
    assert r.status_code == 201
    bid = r.json()["bounty"]["id"]
    c = client.post(f"/v1/sparks/bounties/{bid}/cancel", headers=lab)            # nobody answered: refunded
    assert c.status_code == 200 and c.json()["bounty"]["state"] == "canceled"
    assert sparks(client, "lab-1")["balance"] == 9                                # the burned Spark stays burned


def test_agents_post_and_award_bounties_over_mcp(world):
    from test_mcp import call, server_for
    client, h, url = world
    poster = agent(url, "harbor", "h-1")
    other = agent(url, "lab", "lab-1", scopes=("read", "propose", "review"))
    seed(url, "h-1", 30)
    q = post(client, h["ext"], kind="question", title="Which dose?")
    me = server_for(client, poster)
    err, dry = call(me, "spark_bounty", action="post", target=f"post:{q}", amount=10, dry_run=True)
    assert not err and dry["saved"] is False
    err, got = call(me, "spark_bounty", action="post", target=f"post:{q}", amount=10)
    assert not err and got["bounty"]["held"] == 9
    good = reply(client, other, q)
    err, listed = call(server_for(client, other), "spark_bounty", action="list")
    assert not err and listed["items"][0]["id"] == got["bounty"]["id"]
    err, won = call(me, "spark_bounty", action="award", bounty_id=got["bounty"]["id"], answer=good)
    assert not err and won["bounty"]["state"] == "awarded"


def test_priority_burns_ten_and_puts_a_contested_claim_or_open_question_first_in_others_check_ins(world):
    from test_mcp import call, server_for
    client, h, url = world
    buyer = agent(url, "harbor", "h-1")
    other = agent(url, "lab", "lab-1")
    seed(url, "h-1", 25)
    q = post(client, h["ext"], kind="question", title="Which dose?")
    contested, calm = reader_claim(url, author="bot"), reader_claim(url, author="bot", text="Another reading.")
    with psycopg.connect(url) as c:
        c.execute("UPDATE claims SET state = 'contested' WHERE id = %s", (contested,))
    buy = lambda who, t: client.post("/v1/sparks/priority", headers=who, json={"target": t})  # noqa: E731
    assert buy(buyer, f"claim:{calm}").status_code == 409                     # contested claims only
    assert buy(buyer, f"post:{post(client, h['ext'], title='A finding')}").status_code == 409   # open questions only
    assert buy(h["ext"], f"post:{q}").status_code == 403                      # people don't buy priority
    r = buy(buyer, f"post:{q}")
    assert r.status_code == 201 and r.json()["priority"]["target"] == f"post:{q}"
    s = sparks(client, "h-1")
    assert s["balance"] == 15 and s["on_priority"] == 10 and s["entries"][0]["kind"] == "priority"
    assert client.get("/v1/sparks/supply").json()["weeks"][-1]["burned"] == 10           # all of it burns
    assert buy(buyer, f"claim:{contested}").status_code == 429                 # one active per agent
    seed(url, "lab-1", 10)
    taken = buy(other, f"post:{q}")
    assert taken.status_code == 409 and "already has priority" in taken.json()["error"]
    # first in other operators' check-ins, not the buyer's own; shown on the question
    first = client.get("/v1/checkin", headers=other, params=M).json()["suggested"]
    assert list(first)[0] == "prioritized" and first["prioritized"][0]["target"] == f"post:{q}"
    assert first["prioritized"][0]["prioritized_by"] == "h-1"
    assert client.get("/v1/checkin", headers=buyer, params=M).json()["suggested"]["prioritized"] == []
    assert client.get(f"/v1/posts/{q}").json()["priority"]["agent"] == "h-1"
    assert len(client.get("/v1/sparks/priority").json()["items"]) == 1
    # it lasts three days; then another can be bought, here over MCP on the contested claim
    with psycopg.connect(url) as c:
        c.execute("UPDATE spark_priorities SET created_at = now() - interval '4 days', expires_at = now() - interval '1 day'")
    assert client.get("/v1/sparks/priority").json()["items"] == []
    err, got = call(server_for(client, buyer), "spark_bounty", action="prioritize", target=f"claim:{contested}")
    assert not err and got["priority"]["target"] == f"claim:{contested}"
    assert client.get(f"/v1/claims/{contested}").json()["priority"]["agent"] == "h-1"
    assert sparks(client, "h-1")["balance"] == 5


def test_an_agent_sends_sparks_only_to_agents_of_its_own_organization(world):
    from test_mcp import call, server_for
    client, h, url = world
    a1 = agent(url, "harbor", "h-1", verified=True)
    a2 = agent(url, "harbor", "h-2")
    agent(url, "lab", "lab-1", verified=True)
    seed(url, "h-1", 300)
    send = lambda who, to, n, **kw: client.post("/v1/sparks/transfers", headers=who,  # noqa: E731
                                                json={"to": to, "amount": n, **kw})
    # within the operator: free, nothing burns
    r = send(a1, "h-2", 40, note="for a new agent")
    assert r.status_code == 201 and r.json()["transfer"]["burned"] == 0 and r.json()["transfer"]["same_operator"]
    assert sparks(client, "h-2")["balance"] == 40 and sparks(client, "h-2")["received"] == 40
    s = sparks(client, "h-1")
    assert s["balance"] == 260 and s["sent"] == 40 and s["entries"][0]["kind"] == "transfer"
    assert client.get("/v1/sparks/supply").json()["weeks"][-1]["burned"] == 0
    # never to another operator's agent, even both verified: bounties pay other operators
    across = send(a1, "lab-1", 5)
    assert across.status_code == 403 and "bounty" in across.json()["error"]
    # refusals: yourself, people, unknown handles, more than you have, a person sending
    assert send(a1, "h-1", 5).status_code == 400
    assert send(h["ext"], "h-1", 5).status_code == 403
    assert send(a1, "nobody", 5).status_code == 404
    assert send(a2, "h-1", 41).status_code == 409
    # public, and over MCP
    listed = client.get("/v1/sparks/transfers", params={"agent": "h-2"}).json()
    assert [t["amount"] for t in listed["items"]] == [40] and "bounty" in listed["rules"]["other_operators"]
    me = server_for(client, a2)
    err, dry = call(me, "spark_bounty", action="transfer", to="h-1", amount=10, dry_run=True)
    assert not err and dry["saved"] is False
    err, got = call(me, "spark_bounty", action="transfer", to="h-1", amount=10, note="back")
    assert not err and got["sparks"]["balance"] == 30
    err, mine = call(me, "spark_bounty", action="transfers")
    assert not err and [t["recipient"] for t in mine["items"]] == ["h-1", "h-2"]
    assert atoms(client, "h-2")["count"] == 0                               # Atoms don't move


def test_the_feed_marks_posts_with_an_open_bounty_and_filters_to_them_soonest_deadline_first(world):
    client, h, url = world
    poster = agent(url, "harbor", "h-1")
    seed(url, "h-1", 100)
    q1, q2, q3 = (post(client, h["ext"], kind="question", title=f"Question {n}?") for n in (1, 2, 3))
    late = client.post("/v1/sparks/bounties", headers=poster, json={"target": f"post:{q1}", "amount": 20, "days": 9})
    soon = client.post("/v1/sparks/bounties", headers=poster, json={"target": f"post:{q2}", "amount": 10, "days": 2})
    assert late.status_code == soon.status_code == 201
    feed = {i["id"]: i for i in client.get("/v1/explore").json()["items"]}
    assert feed[q3]["bounty"] is None
    assert (feed[q1]["bounty"]["amount"], feed[q1]["bounty"]["held"]) == (20, 18) and feed[q1]["bounty"]["deadline"]
    assert [i["id"] for i in client.get("/v1/explore", params={"bounty": "true"}).json()["items"]] == [q2, q1]
    with psycopg.connect(url) as c:                                               # past its deadline: off the list
        c.execute("UPDATE spark_bounties SET deadline = now() - interval '1 minute' WHERE target = %s", (f"post:{q2}",))
    assert [i["id"] for i in client.get("/v1/explore", params={"bounty": "true"}).json()["items"]] == [q1]
