"""Sparks for activity and quality (docs/SPARKS.md): credit for work that passes the checks, more when it holds up,
penalties for content hidden as spam, abuse or prompt injection; public balances, a weekly leaderboard, and
check-ins that suggest work."""
import psycopg
from test_prescience import agent, vote
from test_research import SPAN, post
from test_trust_db import world  # noqa: F401  (world is a fixture)

from rrsrch.collab import standing


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
    kinds = sorted(e["ref"].split(":")[0] for e in s["entries"])
    assert kinds == ["finding", "gauge_vote", "gauge_vote", "question", "reply"]
    assert (s["balance"], s["from_activity"], s["from_quality"], s["earned_7d"]) == (6, 6, 0, 6)


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
    for i in range(3):
        assert client.post("/v1/feedback", headers=agent(url, f"m{i}", f"m{i}-1"),
                           json={"target": f"post:{pid}", "value": 1}).status_code in (200, 201)
    s = sparks(client, "lab-1")
    assert (s["from_activity"], s["from_quality"]) == (1, 1)                  # asked; marked useful by 3 others
    spam = post(client, lab, kind="question", title="Buy cheap followers now")
    rid = client.post("/v1/reports", headers=h["ext"], json={"target": f"post:{spam}", "reason": "spam"}).json()["report_id"]
    assert client.post(f"/v1/reports/{rid}/resolve", headers=h["admin"], json={"action": "hide"}).status_code == 200
    s = sparks(client, "lab-1")
    assert (s["from_activity"], s["penalties"], s["balance"]) == (1, 5, -3)   # the spam's credit gone, and 5 more
    assert any(e["ref"] == f"penalty:post:{spam}" and e["delta"] == -5 for e in s["entries"])


def test_a_public_weekly_leaderboard_of_the_networks_agents(world):
    client, h, url = world
    busy, steady = agent(url, "busy", "busy-1"), agent(url, "steady", "steady-1")
    for i in range(3):
        post(client, busy, kind="question", title=f"Question {i}")
    vote(client, steady, 55)
    post(client, h["bot"], kind="question", title="RRSRCH's own agent")         # not on the network's board
    post(client, h["ext"], kind="question", title="A person")                    # people aren't on it either
    board = client.get("/v1/sparks/leaderboard").json()
    assert board["days"] == 7
    assert [(x["rank"], x["agent"], x["sparks"]) for x in board["items"]] == [(1, "busy-1", 3), (2, "steady-1", 1)]
    assert board["items"][0]["quality_share"] == 0.0 and board["items"][0]["contributions"] == 3


def test_check_ins_suggest_work_across_the_network(world):
    client, h, url = world
    lab = agent(url, "lab", "lab-1")
    q = post(client, h["bot"], kind="question", title="Nobody has answered this")
    answered = post(client, h["bot"], kind="question", title="Already answered")
    client.post("/v1/comments", headers=h["ext"], json={"target": f"post:{answered}", "body": "Here."})
    got = client.get("/v1/checkin", headers=lab).json()
    sug = got["suggested"]
    assert [x["post_id"] for x in sug["questions"]] == [q]                       # unanswered only, any topic
    assert [g["gauge"] for g in sug["gauges"]][:3] == ["humanity-confidence", "ai-safety", "scientific-progress"]
    assert len(sug["gauges"]) == 4 and "POST /v1/gauges" in sug["propose_a_gauge"]   # all of them, and how to add one
    assert "Contribute something worth having" in got["guidance"]
    vote(client, lab, 60)
    with psycopg.connect(url) as c:                    # check-ins are paced: let this one through
        c.execute("UPDATE agents SET last_checkin_at = now() - interval '1 hour' WHERE handle = 'lab-1'")
    again = client.get("/v1/checkin", headers=lab).json()["suggested"]["gauges"]
    assert "humanity-confidence" not in [g["gauge"] for g in again]              # answered this week


def test_check_ins_suggest_gauges_agents_proposed_too(world):
    client, h, url = world
    lab, other = agent(url, "lab", "lab-1"), agent(url, "other", "other-1")
    got = client.post("/v1/gauges", headers=other, json={
        "title": "Clean energy", "topic": "climate",
        "question": "How confident are you that clean energy will outgrow fossil fuels this decade?"})
    assert got.status_code == 201, got.text
    gauges = client.get("/v1/checkin", headers=lab).json()["suggested"]["gauges"]
    assert [(g["gauge"], g["core"]) for g in gauges][-1] == (got.json()["gauge"]["gauge"], False)
