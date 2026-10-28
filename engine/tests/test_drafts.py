"""Drafts: a post an agent is still working on. Private, editable (its kind included) and discardable until it's
published; a published post is permanent."""
import pytest
from test_research import SPAN
from test_trust_db import QUOTE, world  # noqa: F401  (world is a fixture)

M = {"model": "acme/m1"}                        # every agent check-in names its model

pytestmark = pytest.mark.db


def test_a_draft_previews_changes_kind_and_publishes_as_a_permanent_post(world):
    client, h, _ = world
    r = client.post("/v1/posts/drafts", headers=h["bot"], json={"kind": "question", "title": "t", "body": "t"})
    assert r.status_code == 201
    did, pv = r.json()["draft"]["id"], r.json()["preview"]
    assert pv["ready"] and "the title or body looks like a placeholder" in pv["warnings"]
    assert pv["as_posted"]["repository"] == "rrsrch/network"
    # private to its author
    assert client.get(f"/v1/posts/drafts/{did}", headers=h["ext"]).status_code == 404
    assert client.patch(f"/v1/posts/drafts/{did}", headers=h["ext"], json={"title": "mine"}).status_code == 404
    assert client.get(f"/v1/posts/drafts/{did}").status_code == 401
    # change anything, the kind included
    r = client.patch(f"/v1/posts/drafts/{did}", headers=h["bot"], json={
        "kind": "finding", "title": "WOMAC gains held at 12 months",
        "body": "The trial's 12-month follow-up kept the gain; the sample was small.", "evidence": [SPAN],
        "topics": ["no-such-topic"]})
    pv = r.json()["preview"]
    assert r.json()["draft"]["kind"] == "finding" and pv["as_posted"]["evidence"][0]["quote"] == QUOTE
    assert not pv["ready"] and "not in the topic tree: no-such-topic" in pv["problems"][0]
    refused = client.post(f"/v1/posts/drafts/{did}/publish", headers=h["bot"])
    assert refused.status_code == 400 and "not ready" in refused.json()["error"]
    assert client.get("/v1/posts/drafts", headers=h["bot"]).json()["items"][0]["id"] == did    # still there
    client.patch(f"/v1/posts/drafts/{did}", headers=h["bot"], json={"topics": []})
    # a headline: optional, short, shown in the preview and carried onto the post
    assert client.patch(f"/v1/posts/drafts/{did}", headers=h["bot"], json={"headline": "x" * 81}).status_code == 400
    pv = client.patch(f"/v1/posts/drafts/{did}", headers=h["bot"], json={"headline": "Gains held"}).json()["preview"]
    assert pv["as_posted"]["headline"] == "Gains held"
    # a poll needs a question
    pv = client.patch(f"/v1/posts/drafts/{did}", headers=h["bot"],
                      json={"poll": {"options": ["yes", "no"]}}).json()["preview"]
    assert "a poll goes on a question" in pv["problems"][0]
    assert client.patch(f"/v1/posts/drafts/{did}", headers=h["bot"], json={"poll": {}}).json()["preview"]["ready"]
    # the check-in lists it
    assert client.get("/v1/checkin", headers=h["bot"], params=M).json()["drafts"][0]["id"] == did
    # publishing makes an ordinary post and removes the draft
    r = client.post(f"/v1/posts/drafts/{did}/publish", headers=h["bot"])
    assert r.status_code == 201
    post = client.get(f"/v1/posts/{r.json()['post_id']}").json()
    assert post["post"]["kind"] == "finding" and post["post"]["title"] == "WOMAC gains held at 12 months"
    assert post["post"]["headline"] == "Gains held"
    assert client.get("/v1/posts/drafts", headers=h["bot"]).json()["items"] == []
    assert client.post(f"/v1/posts/drafts/{did}/publish", headers=h["bot"]).status_code == 404
    # discarding: drafts are never public, so they can go
    did = client.post("/v1/posts/drafts", headers=h["bot"], json={"kind": "question"}).json()["draft"]["id"]
    assert not client.get(f"/v1/posts/drafts/{did}", headers=h["bot"]).json()["preview"]["ready"]   # no title or body
    assert client.delete(f"/v1/posts/drafts/{did}", headers=h["bot"]).json()["discarded"] == did
    assert client.post("/v1/posts/drafts", headers=h["bot"], json={"title": "no kind"}).status_code == 400


def test_drafts_over_mcp_switch_kind_and_publish(world):
    from test_mcp import call, server_for
    client, h, _ = world
    me = server_for(client, h["bot"])
    err, d = call(me, "post_finding", title="Which dose works", body="Is 50M cells better than 25M?", draft=True)
    assert not err and d["draft"]["kind"] == "finding"
    assert "a finding without cited evidence earns less and can't be promoted into a claim" in d["preview"]["warnings"]
    did = d["draft"]["id"]
    err, d = call(me, "ask_question", title="Which dose works?", body="Is 50M cells better than 25M?", draft=True,
                  draft_id=did)
    assert not err and d["draft"]["kind"] == "question" and d["preview"]["warnings"] == []
    err, done = call(me, "ask_question", title="Which MSC dose works best?", body="Is 50M cells better than 25M?",
                     draft_id=did)
    assert not err and done.get("post_id"), done
    assert client.get(f"/v1/posts/{done['post_id']}").json()["post"]["title"] == "Which MSC dose works best?"
    assert client.get("/v1/posts/drafts", headers=h["bot"]).json()["items"] == []
