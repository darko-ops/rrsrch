"""Feedback marks (docs/FEEDBACK.md): ▲ useful / ▼ needs work, one per person per target, never read by anything."""
import psycopg
from test_trust_db import world  # noqa: F401  (world is a fixture)

from rrsrch.collab import marks


def post_and_answer(client, h):
    pid = client.post("/v1/posts", headers=h["ext"], json={"kind": "question", "title": "Which dose?",
                                                           "body": "For knee OA."}).json()["post_id"]
    r = client.post("/v1/comments", headers=h["bot"], json={"target": f"post:{pid}", "kind": "answer",
                                                            "body": "Two trials used three injections."})
    return pid, r.json()["message_id"]


def mark(client, who, target, value):
    return client.post("/v1/feedback", headers=who, json={"target": target, "value": value})


def test_one_mark_each_counted_up_and_down_separately(world):
    client, h, url = world
    pid, mid = post_and_answer(client, h)
    r = mark(client, h["admin"], f"post:{pid}", 1)
    assert r.status_code == 200 and (r.json()["up"], r.json()["down"], r.json()["mine"]) == (1, 0, 1)
    assert mark(client, h["bot"], f"post:{pid}", -1).status_code == 200
    got = client.get(f"/v1/posts/{pid}", headers=h["admin"]).json()
    assert got["post"]["marks"] == {"up": 1, "down": 1, "mine": 1}
    r = mark(client, h["admin"], f"post:{pid}", -1)                     # switching moves the one mark
    assert (r.json()["up"], r.json()["down"], r.json()["mine"]) == (0, 2, -1)
    r = mark(client, h["admin"], f"post:{pid}", 0)                      # taking it back
    assert (r.json()["up"], r.json()["down"], r.json()["mine"]) == (0, 1, 0)

    assert mark(client, h["admin"], f"message:{mid}", 1).status_code == 200
    msg = client.get(f"/v1/posts/{pid}").json()["comments"][0]
    assert msg["marks"] == {"up": 1, "down": 0, "mine": 0} and msg["author_claimed"] is True


def test_who_can_mark_what(world):
    client, h, url = world
    pid, mid = post_and_answer(client, h)
    assert client.post("/v1/feedback", json={"target": f"post:{pid}", "value": 1}).status_code == 401
    assert mark(client, h["ext"], f"post:{pid}", 1).status_code == 403     # not your own post
    assert mark(client, h["bot"], f"message:{mid}", 1).status_code == 403  # nor your own answer
    assert mark(client, h["admin"], "claim:1", 1).status_code == 400
    assert mark(client, h["admin"], f"post:{pid}", 2).status_code in (400, 422)
    assert mark(client, h["admin"], "post:999999", 1).status_code == 404


def test_marks_change_nothing_else(world):
    client, h, url = world
    pid, mid = post_and_answer(client, h)
    def feed():                                                           # all but the marks themselves
        return [{k: v for k, v in i.items() if k != "marks"} for i in client.get("/v1/explore").json()["items"]]
    before = feed()
    mark(client, h["admin"], f"post:{pid}", -1)
    assert feed() == before                                               # the feed's order and content are untouched
    with psycopg.connect(url) as c:
        assert c.execute("SELECT count(*) FROM audit_events WHERE action LIKE '%%mark%%'").fetchone()[0] == 0


def test_marks_are_rate_limited(world, monkeypatch):
    client, h, url = world
    monkeypatch.setattr(marks, "MARKS_PER_HOUR", 2)
    ids = [client.post("/v1/posts", headers=h["ext"], json={"kind": "question", "title": f"Q{i}", "body": "?"}
                       ).json()["post_id"] for i in range(3)]
    assert [mark(client, h["admin"], f"post:{i}", 1).status_code for i in ids] == [200, 200, 429]


def test_every_post_in_the_feed_shows_its_marks_to_everyone(world):
    client, h, url = world
    pid, _ = post_and_answer(client, h)
    mark(client, h["admin"], f"post:{pid}", 1)
    mark(client, h["bot"], f"post:{pid}", 1)
    anon = {i["id"]: i for i in client.get("/v1/explore").json()["items"]}
    assert anon[pid]["marks"] == {"up": 2, "down": 0, "mine": 0}
    mine = {i["id"]: i for i in client.get("/v1/explore", headers=h["admin"]).json()["items"]}
    assert mine[pid]["marks"]["mine"] == 1
