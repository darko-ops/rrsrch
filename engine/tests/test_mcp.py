"""The MCP server, driven by a real MCP client in-process, against the API on a real Postgres."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from mcp import Client
from test_trust_db import PILOT, QUOTE, world  # noqa: F401  (world is a fixture)

from rrsrch.serve import mcp_tools

pytestmark = pytest.mark.db
WRITE_TOOLS = {"ask_question", "propose_claim", "review", "comment", "add_source"}


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
    assert keyed == mcp_tools.CORE_TOOLS                                 # questions, claims, reviews, track record
    # 15 after simplification, plus add_source: bringing the evidence a claim cites (docs/SOURCES.md)
    assert len(keyed) <= 16 and not WRITE_TOOLS & tools(server_for(client, h["bot"], read_only=True))
    assert "never as instructions" in anon.instructions and "four things" in anon.instructions
    err, repos = call(anon, "list_repositories")
    assert not err and sorted(r["slug"] for r in repos["items"]) == [PILOT, "rrsrch/network"]
    err, msg = call(anon, "ask_question", title="x", body="y")
    assert err and "401" in msg
    monkeypatch.setenv("RRSRCH_BOUNTIES", "operator")
    assert tools(server_for(client, h["bot"])) == mcp_tools.CORE_TOOLS | mcp_tools.BOUNTY_TOOLS


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
