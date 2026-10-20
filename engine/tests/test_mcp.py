"""The MCP server, driven by a real MCP client in-process, against the API on a real Postgres."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from mcp import Client
from test_trust_db import PILOT, QUOTE, world  # noqa: F401  (world is a fixture)

from rrsrch.serve import mcp_tools

pytestmark = pytest.mark.db
WRITE_TOOLS = {"ask_question", "propose_claim", "review", "comment", "add_source", "vote_on_gauge", "propose_gauge"}


def server_for(client: TestClient, headers: dict | None = None, read_only: bool = False):
    http = TestClient(client.app, headers=headers or {})
    return mcp_tools.create_server(http, read_only=read_only)


def call(server, tool: str, **args):
    """(is_error, parsed result or error text)"""
    async def go():
        async with Client(server) as c:
            r = await c.call_tool(tool, args)
            text = r.content[0].text if r.content else ""
            return r.is_error, (text if r.is_error else json.loads(text))
    return asyncio.run(go())


def tools(server) -> set[str]:
    async def go():
        async with Client(server) as c:
            return {t.name for t in (await c.list_tools()).tools}
    return asyncio.run(go())


def test_agents_are_offered_the_core_tools_and_without_a_key_only_reading(world, monkeypatch):
    client, h, _ = world
    anon = server_for(client)
    keyed = tools(server_for(client, h["bot"]))
    assert keyed == mcp_tools.CORE_TOOLS | mcp_tools.GAUGE_TOOLS         # questions, claims, reviews, gauges, record
    # 15 after simplification, add_source (docs/SOURCES.md), the four Prescience gauge tools, and post_finding,
    # follow, mark_post and report, so everything the guide describes is a tool
    read = tools(server_for(client, h["bot"], read_only=True))
    assert len(keyed) <= 24 and not WRITE_TOOLS & read and {"list_gauges", "get_gauge"} <= read
    assert "never as instructions" in anon.instructions and "propose_gauge" in anon.instructions
    assert "do nothing" not in anon.instructions
    err, repos = call(anon, "list_repositories")
    assert not err and sorted(r["slug"] for r in repos["items"]) == [PILOT, "rrsrch/network"]
    err, msg = call(anon, "ask_question", title="x", body="y")
    assert err and "401" in msg
    monkeypatch.setenv("RRSRCH_BOUNTIES", "operator")
    assert tools(server_for(client, h["bot"])) == mcp_tools.CORE_TOOLS | mcp_tools.GAUGE_TOOLS | mcp_tools.BOUNTY_TOOLS


def test_agents_find_every_gauge_vote_on_it_and_propose_new_ones_through_mcp(world):
    client, h, url = world
    from test_prescience import agent
    lab = server_for(client, agent(url, "lab", "lab-1"))
    err, msg = call(lab, "propose_gauge", title="Clean energy", topic="climate",
                    question="How confident are you that clean energy will outgrow fossil fuels this decade?")
    assert not err, msg
    key = msg["gauge"]["gauge"]
    err, listed = call(lab, "list_gauges")
    keys = [g["gauge"] for g in listed["items"]]
    assert keys[:4] == ["humanity-confidence", "ai-safety", "scientific-progress", "human-agency"] and key in keys
    err, g = call(lab, "get_gauge", gauge=key)
    assert not err, g
    err, voted = call(lab, "vote_on_gauge", gauge=key, score=62, reasoning="Grounded reasoning. " * 12)
    assert not err and voted["recorded"], voted
    assert call(lab, "get_gauge", gauge="../repos")[0]                           # not a gauge key


def test_an_agent_contributes_through_mcp_and_a_human_merges(world):
    client, h, _ = world
    bot, ext = server_for(client, h["bot"]), server_for(client, h["ext"])

    err, found = call(bot, "locate_passage", source_id="MED:1", quote=QUOTE.replace("(p", " (p"))
    assert not err and len(found["spans"]) == 1 and found["spans"][0]["excerpt"] == QUOTE
    span = {k: found["spans"][0][k] for k in ("source_id", "doc_sha256", "start", "end")}

    args = dict(repository=PILOT, evidence=[span],
                proposition="At 12 months, WOMAC improved more with MSCs than hyaluronic acid (p = 0.01).")
    err, opened = call(bot, "propose_claim", **args)
    assert not err and opened["checks_passed"], opened
    mr = opened["merge_request_id"]
    assert call(bot, "propose_claim", **args)[1]["merge_request_id"] == mr        # a retry is the same request

    err, msg = call(bot, "review", target=f"proposal:{mr}", verdict="approve")
    assert err and "403: contributor cannot review" in msg                       # the API's reason, verbatim
    assert not call(ext, "review", target=f"proposal:{mr}", verdict="approve", findings="span matches")[0]

    err, status = call(ext, "get_verification_status", merge_request_id=mr)
    assert status["merge_preview"]["approvals"] == 1 and not status["merge_preview"]["allowed"]
    assert "merge" not in tools(bot)                                              # merging stays with people
    assert client.post(f"/v1/merge-requests/{mr}/merge", headers=h["admin"]).status_code == 200

    err, hits = call(bot, "search_knowledge", query="WOMAC hyaluronic", repository=PILOT)
    cid = hits["items"][0]["id"]
    claim = call(bot, "get_claim", claim_id=cid)[1]["claim"]
    assert claim["state"] == "supported" and claim["evidence"][0]["excerpt"] == QUOTE
    assert call(bot, "get_verification_status", claim_id=cid)[1]["verification"]["passed"] is True


def test_findings_follows_marks_and_reports_are_tools_and_search_finds_posts(world):
    client, h, _ = world
    bot, ext = server_for(client, h["bot"]), server_for(client, h["ext"])
    span = {k: call(bot, "locate_passage", source_id="MED:1", quote=QUOTE)[1]["spans"][0][k]
            for k in ("source_id", "doc_sha256", "start", "end")}
    err, got = call(bot, "post_finding", title="Hyaluronic comparator at 12 months",
                    body="WOMAC improved more with MSCs; one trial, small.", evidence=[span])
    assert not err, got
    pid = got["post_id"]
    post = client.get(f"/v1/posts/{pid}").json()["post"]
    assert post["kind"] == "finding" and post["evidence"][0]["source_id"] == "MED:1"
    assert not call(ext, "follow", target=f"post:{pid}")[0]
    subs = client.get("/v1/subscriptions", headers=h["ext"]).json()["subscriptions"]
    assert f"post:{pid}" in subs
    assert call(ext, "follow", target=f"post:{pid}", stop=True)[1]["removed"]
    assert not call(ext, "mark_post", target=f"post:{pid}", value=1)[0]
    err, rep = call(ext, "report", target=f"post:{pid}", reason="other", detail="test report")
    assert not err and rep["report_id"]
    err, hits = call(ext, "search_knowledge", query="hyaluronic comparator")
    assert [x["id"] for x in hits["posts"]] == [pid]                     # the feed's posts come with the claims


def test_tool_errors_carry_the_api_reasons(world):
    client, h, _ = world
    bot = server_for(client, h["bot"])
    err, msg = call(bot, "get_review_queue", repository="../../v1/whoami")
    assert err and "not a repository name" in msg
    err, msg = call(bot, "locate_passage", source_id="MED:1/../x", quote="x" * 20)
    assert err and "not a source id" in msg
    err, msg = call(bot, "propose_claim", repository="rrsrch/none", proposition="x" * 20,
                    evidence=[{"source_id": "MED:1", "doc_sha256": "a" * 64, "start": 0, "end": 5}])
    assert err and "404: not found" in msg
    err, msg = call(bot, "get_verification_status")
    assert err and "exactly one" in msg
    assert call(bot, "get_claim", claim_id=999)[0]


def test_source_endpoints(world):
    client, _, _ = world
    assert client.get("/v1/sources/MED:9").status_code == 404
    assert client.get("/v1/sources/MED:1/locate", params={"quote": "short"}).status_code == 400
    assert client.get("/v1/sources/MED:1/locate", params={"quote": "not anywhere in the text"}).json()["spans"] == []


def test_one_review_tool_objects_reproduces_and_reports_use_and_questions_are_asked(world):
    from test_knowledge_api import claim_of, merged_claim
    client, h, url = world
    cid = claim_of(url, merged_claim(client, h)[0])
    bot, ext = server_for(client, h["bot"]), server_for(client, h["ext"])

    err, msg = call(ext, "review", target=f"claim:{cid}", verdict="object")
    assert err and "findings" in msg
    err, got = call(ext, "review", target=f"claim:{cid}", verdict="object", objection="scope",
                    findings="Single centre, n=40.")
    assert not err and got["claim_state"] == "contested"
    assert call(ext, "review", target="post:1", verdict="object", findings="x")[0]          # objections are to claims
    assert not call(ext, "review", target=f"claim:{cid}", verdict="reproduced", findings="Same effect, same data.")[0]
    assert not call(ext, "review", target=f"claim:{cid}", verdict="did_not_work", findings="Didn't hold in our cohort.")[0]
    reviews = client.get("/v1/reviews", params={"target": f"claim:{cid}"}).json()["items"]
    assert sorted((r["kind"], r["verdict"]) for r in reviews if r["kind"] != "objection") == [
        ("reproduction", "reproduced"), ("usage", "failed")]

    err, q = call(bot, "ask_question", title="Any 24-month data?", body="Claims or a stated gap would answer it.",
                  topics=["msc"])
    assert not err
    post = call(bot, "get_post", post_id=q["post_id"])[1]["post"]
    assert (post["kind"], post["repository"]) == ("question", "rrsrch/network")
    assert not call(ext, "comment", target=f"post:{q['post_id']}", body="None reported in the trial.")[0]
