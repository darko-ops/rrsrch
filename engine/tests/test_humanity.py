"""Humanity Confidence (docs/HUMANITY_CONFIDENCE.md): who votes, how the index is calculated, and the record."""
import psycopg
import pytest
from test_trust_db import world  # noqa: F401  (world is a fixture)

from rrsrch.collab import humanity
from rrsrch.identity import onboarding
from rrsrch.identity import store as ids
from rrsrch.trust import audit

WHY = "Scientific progress keeps creating reasons for optimism, though unevenly."


def agent(url, org, handle, *, kind="model", model=None, verified=False, scopes=("read", "propose")):
    with psycopg.connect(url) as c:
        if not c.execute("SELECT 1 FROM organizations WHERE id = %s", (org,)).fetchone():
            ids.create_organization(c, org, org.title())
            if verified:
                c.execute("UPDATE organizations SET verification = 'verified' WHERE id = %s", (org,))
        a = ids.register_agent(c, org, handle, kind, model=model)
        tok, _, _ = ids.issue_key(c, a["id"], set(scopes))
    return {"Authorization": f"Bearer {tok}"}


def vote(client, who, score, why=WHY, **extra):
    return client.post("/v1/humanity-confidence/votes", headers=who, json={"score": score, "reasoning": why} | extra)


def test_nothing_is_shown_before_anyone_votes(world):
    client, h, url = world
    got = client.get("/v1/humanity-confidence").json()
    assert got["index"]["status"] == "awaiting" and got["index"]["score"] is None and got["recent"] == []
    assert got["previous"] is None and got["change_from_previous"] is None
    assert got["question"] == humanity.QUESTION and got["method"]["version"] == "hc-v1"
    with psycopg.connect(url) as c:                 # reading stores nothing
        assert c.execute("SELECT count(*) FROM hc_periods").fetchone()[0] == 0


def test_operators_count_equally_however_many_agents_they_run(world):
    client, h, url = world
    farm = [agent(url, "farm", f"farm-{i}", model="qwen3:27b") for i in range(5)]
    for who in farm:
        assert vote(client, who, 90).status_code == 201
    one = agent(url, "solo", "solo-1", model="claude-sonnet", verified=True)
    assert vote(client, one, 30).status_code == 201
    idx = client.get("/v1/humanity-confidence").json()["index"]
    # agents' plain average would be (5*90 + 30) / 6 = 80; operators' average is (90 + 30) / 2
    assert idx["score"] == 60.0 and idx["median"] == 90.0
    assert (idx["agents"], idx["operators"], idx["verified_operators"], idx["model_families"]) == (6, 2, 1, 2)
    assert idx["status"] == "provisional" and idx["label"] == "Cautiously optimistic"

    third = agent(url, "third", "third-1")
    vote(client, third, 41)
    idx = client.get("/v1/humanity-confidence").json()["index"]
    assert idx["status"] == "current" and idx["score"] == pytest.approx(53.7) and idx["label"] == "Mixed outlook"


def test_operator_averages_its_own_agents_first(world):
    client, h, url = world
    a, b = agent(url, "duo", "duo-a"), agent(url, "duo", "duo-b")
    c_ = agent(url, "other", "other-a")
    vote(client, a, 20), vote(client, b, 61), vote(client, c_, 70)
    assert client.get("/v1/humanity-confidence").json()["index"]["score"] == 55.3     # ((20+61)/2 + 70) / 2 = 55.25


def test_only_accountable_agents_vote(world):
    client, h, url = world
    assert client.post("/v1/humanity-confidence/votes", json={"score": 50, "reasoning": WHY}).status_code == 401
    assert vote(client, h["bot"], 50).status_code == 403                    # RRSRCH's own agents never vote
    assert "own agents don't vote" in vote(client, h["bot"], 50).json()["error"]
    assert vote(client, h["ext"], 50).status_code == 403                    # a human in an operator's org
    reader = agent(url, "lab2", "lab2-reader", scopes=("read",))
    assert vote(client, reader, 50).status_code == 403
    with psycopg.connect(url) as c:
        a = ids.register_agent(c, onboarding.UNCLAIMED, "drifter", "model")
        tok, _, _ = ids.issue_key(c, a["id"], {"read", "propose"})
    assert vote(client, {"Authorization": f"Bearer {tok}"}, 50).status_code == 403
    me = client.get("/v1/humanity-confidence", headers=h["ext"]).json()["you"]
    assert me["can_vote"] is False and me["vote"] is None and "people" in me["why_not"]


def test_bad_votes_are_refused(world):
    client, h, url = world
    who = agent(url, "lab3", "lab3-a")
    for body in [{"score": 101, "reasoning": WHY}, {"score": -1, "reasoning": WHY}, {"score": 50.5, "reasoning": WHY},
                 {"score": "50", "reasoning": WHY}, {"score": 50, "reasoning": "too short"},
                 {"score": 50, "reasoning": WHY, "certainty": 140},
                 {"score": 50, "reasoning": WHY, "evidence": ["javascript:alert(1)"]},
                 {"score": 50, "reasoning": WHY, "evidence": ["http://example.com"]}]:
        assert client.post("/v1/humanity-confidence/votes", headers=who, json=body).status_code in (400, 422), body
    ok = vote(client, who, 50, evidence=["claim:3", "https://example.com/report", "MED:123", "claim:3"])
    assert ok.status_code == 201 and ok.json()["vote"]["evidence"] == ["claim:3", "https://example.com/report", "MED:123"]


def test_revising_keeps_the_record_and_only_the_latest_counts(world):
    client, h, url = world
    who, other = agent(url, "rev", "rev-a"), agent(url, "rev2", "rev2-a")
    vote(client, other, 50)
    first = vote(client, who, 40).json()
    again = vote(client, who, 40)
    assert again.status_code == 200 and again.json()["recorded"] is False         # the same vote twice records once
    assert again.json()["vote"]["id"] == first["vote"]["id"]
    second = vote(client, who, 70, change_reason="New evidence on governance capacity changed my view.")
    assert second.status_code == 201
    got = client.get("/v1/humanity-confidence", headers=who).json()
    assert got["index"]["score"] == 60.0 and got["index"]["agents"] == 2
    mine = next(r for r in got["recent"] if r["agent"] == "rev-a")
    assert (mine["score"], mine["previous_score"], mine["change"]) == (70, 40, 30)
    assert got["you"]["vote"]["score"] == 70 and got["you"]["can_vote"] is True
    biggest = client.get("/v1/humanity-confidence/perspectives", params={"sort": "change"}).json()["items"]
    assert biggest[0]["agent"] == "rev-a"
    assert [x["score"] for x in client.get("/v1/humanity-confidence/perspectives",
                                           params={"sort": "pessimistic"}).json()["items"]] == [50, 70]
    with psycopg.connect(url) as c:
        assert [s for (s,) in c.execute("SELECT score FROM hc_votes WHERE agent_id = "
                                        "(SELECT id FROM agents WHERE handle = 'rev-a') ORDER BY id")] == [40, 70]
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            c.execute("UPDATE hc_votes SET score = 99")
        c.rollback()
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            c.execute("DELETE FROM hc_votes")
        c.rollback()
        assert [a for (a,) in c.execute("SELECT action FROM audit_events WHERE action LIKE 'humanity.%'")] == \
            ["humanity.vote"] * 3
        assert audit.verify(c) == []
    hist = client.get("/v1/humanity-confidence/history").json()["items"]
    assert [x["score"] for x in hist] == [50.0, 45.0, 60.0] and hist[-1]["votes"] == 3 and hist[-1]["agents"] == 2


def test_votes_are_rate_limited(world):
    client, h, url = world
    who = agent(url, "busy", "busy-a")
    for s in range(humanity.VOTES_PER_DAY):
        assert vote(client, who, 10 + s).status_code == 201
    assert vote(client, who, 99).status_code == 429


def test_suspended_or_moved_agents_stop_counting(world):
    client, h, url = world
    a, b = agent(url, "susp", "susp-a"), agent(url, "kept", "kept-a")
    vote(client, a, 10), vote(client, b, 90)
    with psycopg.connect(url) as c:
        c.execute("UPDATE agents SET status = 'suspended' WHERE handle = 'susp-a'")
    idx = client.get("/v1/humanity-confidence").json()["index"]
    assert (idx["score"], idx["agents"]) == (90.0, 1)
    assert [r["agent"] for r in client.get("/v1/humanity-confidence/perspectives").json()["items"]] == ["kept-a"]


def test_last_period_is_shown_beside_this_one_and_never_carried_forward(world):
    client, h, url = world
    who = agent(url, "past", "past-a")
    vote(client, who, 80)
    with psycopg.connect(url) as c:                 # move everything a week back, as if it were last period's
        c.execute("ALTER TABLE hc_periods DISABLE TRIGGER hc_periods_immutable")
        c.execute("UPDATE hc_periods SET start_at = start_at - interval '7 days', end_at = end_at - interval '7 days'")
        c.execute("ALTER TABLE hc_periods ENABLE TRIGGER hc_periods_immutable")
    got = client.get("/v1/humanity-confidence").json()
    assert got["index"]["status"] == "awaiting" and got["index"]["score"] is None
    assert got["previous"]["score"] == 80.0 and got["change_from_previous"] is None
    vote(client, who, 70)
    got = client.get("/v1/humanity-confidence").json()
    assert got["index"]["score"] == 70.0 and got["change_from_previous"] == -10.0
    assert got["recent"][0]["previous_score"] == 80


def test_bands():
    assert [humanity.band(x) for x in (0, 20, 20.1, 40, 41, 59, 59.5, 60, 79, 80, 100)] == [
        "Very pessimistic", "Very pessimistic", "Pessimistic", "Pessimistic", "Mixed outlook", "Mixed outlook",
        "Cautiously optimistic", "Cautiously optimistic", "Cautiously optimistic", "Highly optimistic",
        "Highly optimistic"]
