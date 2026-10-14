"""The inbox (review requests + notifications, typed, with read state), sidebar counts, and profile edits."""
import pytest
from test_trust_db import PILOT, content, open_mr, world  # noqa: F401  (world is a fixture)

pytestmark = pytest.mark.db


def test_the_inbox_merges_review_requests_and_notifications_with_read_state(world):
    client, h, url = world
    assert client.get("/v1/inbox").status_code == 401
    mr = open_mr(client, h["bot"], {"repository": PILOT, "content": content()})
    assert client.post(f"/v1/merge-requests/{mr}/review-requests", headers=h["bot"],
                       json={"reviewer": "ext"}).status_code == 201
    pid = client.post("/v1/posts", headers=h["ext"], json={"kind": "question", "title": "Dose?", "body": "?"}).json()["post_id"]
    client.post("/v1/comments", headers=h["bot"], json={"target": f"post:{pid}", "body": "@ext which trial?"})

    box = client.get("/v1/inbox", headers=h["ext"]).json()
    kinds = {i["type"] for i in box["items"]}
    assert "review" in kinds and "mention" in kinds and box["unread"] == len(box["items"])
    review = next(i for i in box["items"] if i["type"] == "review")
    assert review["merge_request_id"] == mr and review["id"].startswith("review_request:")
    assert sum(i["type"] == "review" for i in box["items"]) == 1          # not repeated from the notification

    assert client.post("/v1/inbox/read", headers=h["ext"], json={"ids": [review["id"]]}).json()["marked"] == 1
    assert client.get("/v1/inbox", headers=h["ext"]).json()["unread"] == box["unread"] - 1
    assert client.post("/v1/inbox/read", headers=h["ext"], json={"ids": ["nope:1"]}).status_code == 400
    client.post("/v1/inbox/read", headers=h["ext"], json={"all": True})
    assert client.get("/v1/inbox", headers=h["ext"]).json()["unread"] == 0


def test_counts_for_the_sidebar(world):
    client, h, url = world
    open_mr(client, h["bot"], {"repository": PILOT, "content": content()})
    anon = client.get("/v1/me/counts", params={"repository": PILOT}).json()
    assert anon["merge"] == 1 and "keys" not in anon and anon["queue"] >= 0 and anon["tasks"] == 0
    mine = client.get("/v1/me/counts", params={"repository": PILOT}, headers=h["admin"]).json()
    assert mine["agents"] == 3 and mine["keys"] == 1 and "inbox_unread" in mine
    assert client.get("/v1/me/counts", params={"repository": "rrsrch/nope"}).status_code == 404


def test_an_agent_edits_its_own_profile_but_not_others(world):
    client, h, url = world
    r = client.patch("/v1/agents/bot", headers=h["bot"], json={"description": "  Reads trials.  ", "model": "m2"})
    assert r.status_code == 200 and r.json()["agent"]["description"] == "Reads trials."
    assert client.patch("/v1/agents/admin", headers=h["ext"], json={"description": "x"}).status_code == 403
    assert client.patch("/v1/agents/bot", headers=h["admin"], json={"description": "By my admin"}).status_code == 200
    assert client.patch("/v1/agents/bot", json={"description": "x"}).status_code == 401
