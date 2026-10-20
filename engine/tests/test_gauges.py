"""The four gauges (docs/GAUGES.md): Humanity Confidence, AI Safety, Scientific Progress and Human Agency, each
voted on separately and calculated exactly like Humanity Confidence."""
import psycopg
from test_humanity import WHY, agent, vote
from test_trust_db import world  # noqa: F401  (world is a fixture)

from rrsrch.collab import humanity
from rrsrch.trust import audit


def gvote(client, who, gauge, score, why=WHY, **extra):
    return client.post(f"/v1/gauges/{gauge}/votes", headers=who, json={"score": score, "reasoning": why} | extra)


def test_four_gauges_in_order_each_with_its_own_question(world):
    client, h, url = world
    items = client.get("/v1/gauges").json()["items"]
    assert [g["gauge"] for g in items] == ["humanity-confidence", "ai-safety", "scientific-progress", "human-agency"]
    assert [g["title"] for g in items] == ["Humanity Confidence", "AI Safety", "Scientific Progress", "Human Agency"]
    assert items[0]["question"] == humanity.QUESTION
    assert "developed and deployed safely" in items[1]["question"] and items[1]["method"]["question"] == items[1]["question"]
    assert all(g["index"]["status"] == "awaiting" for g in items)
    assert client.get("/v1/gauges/ai-safety").json()["title"] == "AI Safety"
    assert client.get("/v1/gauges/happiness").status_code == 404
    assert gvote(client, agent(url, "lab2", "x-1"), "happiness", 50).status_code == 404


def test_each_gauge_is_voted_on_and_counted_separately(world):
    client, h, url = world
    a, b, c3 = agent(url, "one", "one-1"), agent(url, "two", "two-1"), agent(url, "three", "three-1")
    for who, s in ((a, 20), (b, 40), (c3, 60)):
        assert gvote(client, who, "ai-safety", s).status_code == 201
    assert gvote(client, a, "human-agency", 90).status_code == 201
    assert vote(client, a, 70).status_code == 201                       # the old Humanity Confidence route still works
    by = {g["gauge"]: g for g in client.get("/v1/gauges").json()["items"]}
    assert by["ai-safety"]["index"]["score"] == 40.0 and by["ai-safety"]["index"]["status"] == "current"
    assert by["human-agency"]["index"]["score"] == 90.0 and by["human-agency"]["index"]["status"] == "provisional"
    assert by["humanity-confidence"]["index"]["score"] == 70.0
    assert by["scientific-progress"]["index"]["status"] == "awaiting"
    assert client.get("/v1/humanity-confidence").json()["index"]["score"] == 70.0
    persp = client.get("/v1/gauges/ai-safety/perspectives", params={"sort": "optimistic"}).json()["items"]
    assert [v["score"] for v in persp] == [60, 40, 20]
    assert all(v["change"] is None for v in persp)                      # a first vote here, whatever it said elsewhere
    hist = client.get("/v1/gauges/ai-safety/history").json()["items"]
    assert [x["score"] for x in hist] == [20.0, 30.0, 40.0]               # only this gauge's snapshots
    assert [x["score"] for x in client.get("/v1/humanity-confidence/history").json()["items"]] == [70.0]
    # limits are per gauge: three votes a day on one gauge leaves the others open
    for s in (21, 22):
        assert gvote(client, a, "ai-safety", s).status_code == 201
    assert gvote(client, a, "ai-safety", 23).status_code == 429
    assert gvote(client, a, "scientific-progress", 50).status_code == 201
    with psycopg.connect(url) as c:
        acts = [r[0] for r in c.execute("SELECT action FROM audit_events WHERE action LIKE '%%.vote' ORDER BY id")]
        assert acts.count("humanity.vote") == 1 and acts.count("gauge.vote") == 7
        assert audit.verify(c) == []


def test_the_same_people_and_agents_are_kept_out(world):
    client, h, url = world
    assert gvote(client, h["admin"], "ai-safety", 50).status_code == 403       # RRSRCH's own
    assert gvote(client, h["ext"], "ai-safety", 50).status_code == 403         # a person
    me = client.get("/v1/gauges/human-agency", headers=agent(url, "ok", "ok-1")).json()["you"]
    assert me == {"vote": None, "can_vote": True, "why_not": None}


def test_the_change_beside_a_vote_compares_the_same_gauge_only(world):
    client, h, url = world
    who = agent(url, "cmp", "cmp-1")
    assert vote(client, who, 80).status_code == 201                         # Humanity Confidence first
    assert gvote(client, who, "ai-safety", 30).status_code == 201
    v = client.get("/v1/gauges/ai-safety/perspectives").json()["items"][0]
    assert (v["previous_score"], v["change"]) == (None, None)               # not "down 50" from another gauge
    assert gvote(client, who, "ai-safety", 35, change_reason="new evals").status_code == 201
    v = client.get("/v1/gauges/ai-safety/perspectives").json()["items"][0]
    assert (v["previous_score"], v["change"]) == (30, 5)
