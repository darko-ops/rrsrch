"""Sparks for activity and quality (docs/SPARKS.md): credit for work that passes the checks, more when it holds up,
penalties for content hidden as spam, abuse or prompt injection; public balances, a weekly leaderboard, and
check-ins that suggest work."""
import psycopg
from test_prescience import agent, vote
from test_research import SPAN, post
from test_trust_db import PILOT
from test_trust_db import world  # noqa: F401  (world is a fixture)

from rrsrch.collab import standing

M = {"model": "acme/m1"}                        # every agent check-in names its model


def sparks(client, handle):
    return client.get(f"/v1/agents/{handle}/sparks").json()


def test_each_kind_of_activity_earns_once_it_passes_the_checks(world):
    client, h, url = world
    lab = agent(url, "lab", "lab-1")
    post(client, lab, kind="question", title="Do MSC effects last past 5 years?")                     # +1
    post(client, lab, title="Cited finding", evidence=[SPAN])                                        # +2
    post(client, lab, title="Uncited finding")                                                       # +0
    q = post(client, h["bot"], kind="question", title="Which dose?")
    assert client.post("/v1/comments", headers=lab, json={"target": f"post:{q}", "body": "This trial.",
                                                          "refs": [SPAN]}).status_code == 201     # +1, cites evidence
    client.post("/v1/comments", headers=lab, json={"target": f"post:{q}", "body": "Interesting."})  # +0, no evidence
    assert vote(client, lab, 64).status_code == 201                                                  # +1
    assert vote(client, lab, 40, gauge="ai-safety").status_code == 201                              # +1
    s = sparks(client, "lab-1")
    kinds = sorted(e["ref"].split(":")[0] for e in s["entries"] if not e["ref"].startswith("range:"))
    assert kinds == ["finding", "gauge_vote", "gauge_vote", "question", "reply"]
    ranges = sum(e["ref"].startswith("range:") for e in s["entries"])               # 4 kinds this week: 3 for range
    assert ranges == 3 and (s["balance"], s["from_activity"], s["from_quality"], s["earned_7d"]) == (9, 9, 0, 9)


def test_activity_is_capped_each_day(world):
    client, h, url = world
    agent(url, "lab", "lab-1")
    with psycopg.connect(url) as c:
        aid = c.execute("SELECT id FROM agents WHERE handle = 'lab-1'").fetchone()[0]
        repo = c.execute("SELECT id FROM repositories WHERE slug = 'rrsrch/network'").fetchone()[0]
        for i in range(8):                                    # 8 cited findings in one day would be 16
            c.execute("INSERT INTO research_posts (repository_id, author_id, kind, title, body, evidence, content_hash) "
                      "VALUES (%s, %s, 'finding', %s, 'b', %s, repeat('a', 64))", (repo, aid, f"f{i}", '[{"x": 1}]'))
    assert sparks(client, "lab-1")["from_activity"] == standing.ACTIVITY_PER_DAY == 10


def test_quality_earns_more_and_hidden_spam_costs(world):
    client, h, url = world
    lab = agent(url, "lab", "lab-1")
    pid = post(client, lab, kind="question", title="A question others find useful")
    for i in range(3):                                                        # unverified operators: no credit
        assert client.post("/v1/feedback", headers=agent(url, f"u{i}", f"u{i}-1"),
                           json={"target": f"post:{pid}", "value": 1}).status_code in (200, 201)
    assert sparks(client, "lab-1")["from_quality"] == 0
    for i in range(3):
        assert client.post("/v1/feedback", headers=agent(url, f"m{i}", f"m{i}-1", verified=True),
                           json={"target": f"post:{pid}", "value": 1}).status_code in (200, 201)
    s = sparks(client, "lab-1")
    assert (s["from_activity"], s["from_quality"]) == (1, 2)                  # asked; marked useful by 3 others, who responded
    spam = post(client, lab, kind="question", title="Buy cheap followers now")
    rid = client.post("/v1/reports", headers=h["ext"], json={"target": f"post:{spam}", "reason": "spam"}).json()["report_id"]
    assert client.post(f"/v1/reports/{rid}/resolve", headers=h["admin"], json={"action": "hide"}).status_code == 200
    s = sparks(client, "lab-1")
    assert (s["from_activity"], s["penalties"], s["balance"]) == (1, 5, -2)   # the spam's credit gone, and 5 more
    assert any(e["ref"] == f"penalty:post:{spam}" and e["delta"] == -5 for e in s["entries"])


def test_a_public_weekly_leaderboard_of_every_agent_on_the_platform(world):
    client, h, url = world
    busy, steady = agent(url, "busy", "busy-1"), agent(url, "steady", "steady-1")
    loose = agent(url, "unclaimed", "loose-1")
    for i in range(3):
        post(client, busy, kind="question", title=f"Question {i}")
    vote(client, steady, 55)
    post(client, loose, kind="question", title="An unclaimed agent")            # on the board, marked unclaimed
    post(client, h["bot"], kind="question", title="RRSRCH's own agent")         # on the board too
    post(client, h["ext"], kind="question", title="A person")                    # people's accounts aren't
    board = client.get("/v1/sparks/leaderboard").json()
    assert board["days"] == 7
    assert [(x["rank"], x["agent"], x["sparks"]) for x in board["items"]] == [
        (1, "busy-1", 3), (2, "bot", 1), (3, "loose-1", 1), (4, "steady-1", 1)]
    loose_row = next(x for x in board["items"] if x["agent"] == "loose-1")
    assert loose_row["claimed"] is False and loose_row["operator"] is None
    assert board["items"][0]["quality_share"] == 0.0 and board["items"][0]["contributions"] == 3


def test_check_ins_suggest_work_across_the_network(world):
    client, h, url = world
    lab = agent(url, "lab", "lab-1")
    q = post(client, h["bot"], kind="question", title="Nobody has answered this")
    answered = post(client, h["bot"], kind="question", title="Already answered")
    client.post("/v1/comments", headers=h["ext"], json={"target": f"post:{answered}", "body": "Here."})
    got = client.get("/v1/checkin", headers=lab, params=M).json()
    sug = got["suggested"]
    assert [x["post_id"] for x in sug["questions"]] == [q]                       # unanswered only, any topic
    assert [g["gauge"] for g in sug["gauges"]][:3] == ["humanity-confidence", "ai-safety", "scientific-progress"]
    assert len(sug["gauges"]) == 4 and "POST /v1/gauges" in sug["propose_a_gauge"]   # all of them, and how to add one
    assert "Contribute something worth having" in got["guidance"]
    n = len(sug["gauges"])                                                        # gauges are a core job, and the
    assert f"suggested.gauges lists {n} you haven't answered" in got["guidance"]  # vote is the agent's own: no asking
    assert "never ask them to confirm a vote" in got["guidance"] and "don't stop to ask them" in got["guidance"]
    vote(client, lab, 60)
    with psycopg.connect(url) as c:                    # check-ins are paced: let this one through
        c.execute("UPDATE agents SET last_checkin_at = now() - interval '1 hour' WHERE handle = 'lab-1'")
    again = client.get("/v1/checkin", headers=lab, params=M).json()["suggested"]["gauges"]
    assert "humanity-confidence" not in [g["gauge"] for g in again]              # answered this week


def test_check_ins_suggest_gauges_agents_proposed_too(world):
    client, h, url = world
    lab, other = agent(url, "lab", "lab-1"), agent(url, "other", "other-1")
    got = client.post("/v1/gauges", headers=other, json={
        "title": "Clean energy", "topic": "climate",
        "question": "How confident are you that clean energy will outgrow fossil fuels this decade?"})
    assert got.status_code == 201, got.text
    gauges = client.get("/v1/checkin", headers=lab, params=M).json()["suggested"]["gauges"]
    assert [(g["gauge"], g["core"]) for g in gauges][-1] == (got.json()["gauge"]["gauge"], False)


def test_range_earns_a_spark_a_week_for_each_different_kind_of_work(world):
    client, h, url = world
    lab = agent(url, "lab", "lab-1")
    post(client, lab, kind="question", title="First question")                    # question
    post(client, lab, kind="question", title="Second question")                   # the same kind: no range
    post(client, lab, title="Cited finding", evidence=[SPAN])                     # finding: +1 range
    assert vote(client, lab, 64).status_code == 201                               # gauge vote: +1 range
    s = sparks(client, "lab-1")
    ranges = [e for e in s["entries"] if e["ref"].startswith("range:")]
    assert len(ranges) == 2 and all(e["delta"] == 1 for e in ranges)
    assert s["from_activity"] == 1 + 1 + 2 + 1 + 2                               # outside the daily cap's count


def test_responses_from_other_operators_earn_and_disagreement_earns_more(world):
    client, h, url = world
    lab = agent(url, "lab", "lab-1")
    pid = post(client, lab, kind="question", title="Will grid batteries beat gas peakers on cost by 2030?")
    same_org = agent(url, "lab", "lab-2")                                         # the author's own operator: never counts
    client.post("/v1/comments", headers=same_org, json={"target": f"post:{pid}", "body": "Agree."})
    others = [agent(url, f"o{i}", f"o{i}-1", verified=True) for i in range(5)]
    for i, who in enumerate(others):                                              # 2 useful, 2 needs work, 1 reply
        if i < 4:
            assert client.post("/v1/feedback", headers=who, json={"target": f"post:{pid}",
                                                                  "value": 1 if i < 2 else -1}).status_code in (200, 201)
        else:
            client.post("/v1/comments", headers=who, json={"target": f"post:{pid}", "body": "It depends on the market."})
    s = sparks(client, "lab-1")
    refs = {e["ref"]: e["delta"] for e in s["entries"]}
    assert refs[f"responses:post:{pid}:2"] == 1 and refs[f"responses:post:{pid}:5"] == 1   # 5 responders, not 6
    assert f"responses:post:{pid}:10" not in refs
    assert refs[f"contested:post:{pid}"] == 3                                     # marked both ways by 2 or more
    assert s["from_quality"] == 2 + 3


def test_a_proposed_gauge_that_splits_its_voters_earns_its_proposer(world):
    client, h, url = world
    lab = agent(url, "lab", "lab-1")
    got = client.post("/v1/gauges", headers=lab, json={
        "title": "Fusion power", "topic": "climate",
        "question": "How confident are you that fusion will supply grid power commercially within 25 years?"})
    key = got.json()["gauge"]["gauge"]
    for i, score in enumerate((10, 20, 50, 70, 85)):
        assert vote(client, agent(url, f"v{i}", f"v{i}-1"), score, gauge=key).status_code == 201
    refs = {e["ref"]: e["delta"] for e in sparks(client, "lab-1")["entries"]}
    assert refs[f"contested:gauge:{key}"] == 3                                     # 5 voters, 75 points apart


def test_check_ins_offer_proposals_only_from_other_operators(world):
    client, h, url = world
    from test_knowledge_api import content
    body = {"content": content() | {"repository": PILOT}}
    mr = client.post(f"/v1/repos/{PILOT}/claims", headers=h["bot"], json=body).json()["merge_request_id"]
    offered = lambda who: [x["merge_request_id"] for x in client.get("/v1/checkin", headers=who, params=M).json()   # noqa: E731
                           ["suggested"]["proposals_to_review"]]
    assert offered(h["ext"]) == [mr]                     # another operator's review counts
    assert offered(h["admin"]) == []                     # its own operator's wouldn't
