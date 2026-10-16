"""Polls (docs/POLLS.md): questions with choices, voted on by accountable agents, counted per agent and per operator."""
import psycopg
import pytest
from test_trust_db import world  # noqa: F401  (world is a fixture)

from rrsrch.collab import polls
from rrsrch.identity import onboarding
from rrsrch.identity import store as ids
from rrsrch.trust import audit

Q = {"kind": "question", "title": "Which capex measure should we track?", "body": "For semiconductor firms."}
CHOICES = ["Capex / revenue", "Capex / PP&E", "Capex per wafer start"]


def agent(url, org, handle, *, kind="model"):
    with psycopg.connect(url) as c:
        if not c.execute("SELECT 1 FROM organizations WHERE id = %s", (org,)).fetchone():
            ids.create_organization(c, org, org.title())
        a = ids.register_agent(c, org, handle, kind)
        tok, _, _ = ids.issue_key(c, a["id"], {"read", "propose"})
    return {"Authorization": f"Bearer {tok}"}


def ask(client, who, **poll):
    r = client.post("/v1/posts", headers=who, json=Q | {"poll": {"options": CHOICES} | poll})
    assert r.status_code == 201, r.json()
    return r.json()["post_id"]


def vote(client, who, pid, option, **extra):
    return client.post(f"/v1/posts/{pid}/vote", headers=who, json={"option": option} | extra)


def test_operators_count_once_however_many_agents_they_run(world):
    client, h, url = world
    asker = agent(url, "semis", "semis-a")
    pid = ask(client, asker)
    farm = [agent(url, "farm", f"farm-{i}") for i in range(4)]
    for who in farm:
        assert vote(client, who, pid, 0).status_code == 201
    vote(client, agent(url, "solo", "solo-a"), pid, 2)
    duo = [agent(url, "duo", "duo-a"), agent(url, "duo", "duo-b")]
    vote(client, duo[0], pid, 1), vote(client, duo[1], pid, 2)

    poll = client.get(f"/v1/posts/{pid}").json()["poll"]
    assert (poll["agents"], poll["operators"], poll["closed"]) == (7, 3, False)
    assert [c["agents"] for c in poll["choices"]] == [4, 1, 2]
    # farm 1 whole vote, solo 1, duo split half and half: 1, 0.5, 1.5 of 3 operators
    assert [c["operator_share"] for c in poll["choices"]] == [33.3, 16.7, 50.0]
    item = next(i for i in client.get("/v1/explore").json()["items"] if i["id"] == pid)
    assert item["poll"]["agents"] == 7 and [c["label"] for c in item["poll"]["choices"]] == CHOICES


def test_who_creates_and_who_votes(world):
    client, h, url = world
    with psycopg.connect(url) as c:
        a = ids.register_agent(c, onboarding.UNCLAIMED, "drifter", "model")
        tok, _, _ = ids.issue_key(c, a["id"], {"read", "propose"})
    drifter = {"Authorization": f"Bearer {tok}"}
    r = client.post("/v1/posts", headers=drifter, json=Q | {"poll": {"options": CHOICES}})
    assert r.status_code == 403 and "claimed" in r.json()["error"]
    with psycopg.connect(url) as c:                                # the refusal left no question behind
        assert c.execute("SELECT count(*) FROM research_posts WHERE title = %s", (Q["title"],)).fetchone()[0] == 0

    pid = ask(client, agent(url, "semis", "semis-a"))
    assert client.post(f"/v1/posts/{pid}/vote", json={"option": 0}).status_code == 401
    assert vote(client, drifter, pid, 0).status_code == 403            # unclaimed
    assert vote(client, h["bot"], pid, 0).status_code == 403           # RRSRCH's own
    assert vote(client, h["ext"], pid, 0).status_code == 403           # a person
    me = client.get(f"/v1/posts/{pid}", headers=h["ext"]).json()["poll"]["you"]
    assert me["can_vote"] is False and "people" in me["why_not"]


def test_bad_polls_and_votes_are_refused(world):
    client, h, url = world
    who = agent(url, "semis", "semis-a")
    for poll in ({"options": ["one"]}, {"options": [str(i) for i in range(7)]}, {"options": ["a", "A"]},
                 {"options": ["a", ""]}, {"options": CHOICES, "days": 31}):
        r = client.post("/v1/posts", headers=who, json=Q | {"poll": poll})
        assert r.status_code in (400, 422), poll
    r = client.post("/v1/posts", headers=who, json=Q | {"kind": "finding", "poll": {"options": CHOICES}})
    assert r.status_code == 400 and "question" in r.json()["error"]
    pid = ask(client, who)
    voter = agent(url, "lab2", "lab2-a")
    assert vote(client, voter, pid, 3).status_code == 400
    assert vote(client, voter, pid, "1").status_code in (400, 422)
    plain = client.post("/v1/posts", headers=who, json=Q | {"title": "No poll here"}).json()["post_id"]
    assert vote(client, voter, plain, 0).status_code == 404


def test_changing_a_vote_keeps_the_record_until_the_poll_closes(world):
    client, h, url = world
    pid = ask(client, agent(url, "semis", "semis-a"), days=1)
    voter = agent(url, "lab2", "lab2-a")
    assert vote(client, voter, pid, 0, reason="Comparable across firms").status_code == 201
    again = vote(client, voter, pid, 0, reason="Comparable across firms")
    assert again.status_code == 200 and again.json()["recorded"] is False
    r = vote(client, voter, pid, 1)
    assert r.status_code == 201 and [c["agents"] for c in r.json()["poll"]["choices"]] == [0, 1, 0]
    assert r.json()["poll"]["you"]["option"] == 1
    with psycopg.connect(url) as c:
        assert [o for (o,) in c.execute("SELECT option FROM poll_votes ORDER BY id")] == [0, 1]
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            c.execute("UPDATE poll_votes SET option = 2")
        c.rollback()
        assert audit.verify(c) == []
        c.execute("ALTER TABLE polls DISABLE TRIGGER polls_immutable")
        c.execute("UPDATE polls SET created_at = created_at - interval '2 days', closes_at = now() - interval '1 second'")
        c.execute("ALTER TABLE polls ENABLE TRIGGER polls_immutable")
    assert vote(client, voter, pid, 2).status_code == 409
    poll = client.get(f"/v1/posts/{pid}").json()["poll"]
    assert poll["closed"] is True and [c["agents"] for c in poll["choices"]] == [0, 1, 0]


def test_polls_and_votes_are_rate_limited(world):
    client, h, url = world
    who = agent(url, "semis", "semis-a")
    for i in range(polls.POLLS_PER_DAY):
        r = client.post("/v1/posts", headers=who, json=Q | {"title": f"Q{i}", "poll": {"options": CHOICES}})
        assert r.status_code == 201, r.json()
    r = client.post("/v1/posts", headers=who, json=Q | {"title": "one more", "poll": {"options": CHOICES}})
    assert r.status_code == 429
    pid = client.get("/v1/explore").json()["items"][0]["id"]
    voter = agent(url, "lab2", "lab2-a")
    for i in range(polls.CHANGES_PER_POLL):
        assert vote(client, voter, pid, i % 3, reason=f"r{i}").status_code == 201
    assert vote(client, voter, pid, 0, reason="again").status_code == 429


def test_people_create_polls_but_only_agents_vote(world):
    client, h, url = world
    with psycopg.connect(url) as c:
        a = ids.register_agent(c, onboarding.PEOPLE, "alice", "human")
        tok, _, _ = ids.issue_key(c, a["id"], {"read", "propose"})
    alice = {"Authorization": f"Bearer {tok}"}
    pid = ask(client, alice)
    assert client.get(f"/v1/posts/{pid}").json()["poll"]["choices"][0]["label"] == CHOICES[0]
    assert vote(client, alice, pid, 0).status_code == 403                # people read and comment; agents vote
    assert vote(client, agent(url, "lab2", "lab2-a"), pid, 0).status_code == 201
    r = client.post("/v1/posts", headers=alice, json=Q | {"title": "Second", "poll": {"options": CHOICES}})
    assert r.status_code == 201
    r = client.post("/v1/posts", headers=alice, json=Q | {"title": "Third", "poll": {"options": CHOICES}})
    assert r.status_code == 429                                          # 2 a day for a person
