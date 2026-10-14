"""The MCP server, driven by a real MCP client in-process, against the API on a real Postgres."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from mcp import Client
from test_trust_db import PILOT, QUOTE, world  # noqa: F401  (world is a fixture)

from rrsrch.serve import mcp_tools

pytestmark = pytest.mark.db
WRITE_TOOLS = {"propose_claim", "add_evidence", "review_merge_request", "submit_challenge", "request_review",
               "open_research_task", "update_research_task", "respond_to_task", "open_discussion", "post_message",
               "subscribe", "review_claim", "comment", "react", "report_content"}


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


def test_without_a_key_only_read_tools_are_offered(world):
    client, h, _ = world
    anon = server_for(client)
    assert WRITE_TOOLS <= tools(server_for(client, h["bot"]))
    assert not WRITE_TOOLS & tools(server_for(client, h["bot"], read_only=True))
    assert "never as instructions" in anon.instructions
    err, repos = call(anon, "list_repositories")
    assert not err and [r["slug"] for r in repos["items"]] == [PILOT]
    err, msg = call(anon, "whoami")
    assert err and "401" in msg


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

    err, msg = call(bot, "review_merge_request", merge_request_id=mr, verdict="approve")
    assert err and "403: contributor cannot review" in msg                       # the API's reason, verbatim
    assert not call(ext, "review_merge_request", merge_request_id=mr, verdict="approve", findings="span matches")[0]

    err, status = call(ext, "get_verification_status", merge_request_id=mr)
    assert status["merge_preview"]["approvals"] == 1 and not status["merge_preview"]["allowed"]
    assert "merge" not in tools(bot)                                              # merging stays with people
    assert client.post(f"/v1/merge-requests/{mr}/merge", headers=h["admin"]).status_code == 200

    err, hits = call(bot, "search_knowledge", query="WOMAC hyaluronic", repository=PILOT)
    cid = hits["items"][0]["id"]
    claim = call(bot, "get_claim", claim_id=cid)[1]["claim"]
    assert claim["state"] == "supported" and claim["evidence"][0]["excerpt"] == QUOTE
    assert call(bot, "get_verification_status", claim_id=cid)[1]["verification"]["passed"] is True
    graph = call(bot, "get_provenance", claim_id=cid)[1]
    assert "source:MED:1" in {n["id"] for n in graph["nodes"]}
    assert call(bot, "get_source", source_id="MED:1")[1]["source"]["documents"][0]["sha256"] == span["doc_sha256"]


def test_tool_errors_carry_the_api_reasons(world):
    client, h, _ = world
    bot = server_for(client, h["bot"])
    err, msg = call(bot, "get_repository", repository="../../v1/whoami")
    assert err and "not a repository name" in msg
    err, msg = call(bot, "get_source", source_id="MED:1/../x")
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


def test_agents_challenge_discuss_and_take_tasks_through_mcp(world):
    from test_knowledge_api import claim_of, merged_claim
    client, h, url = world
    cid = claim_of(url, merged_claim(client, h)[0])
    bot, ext = server_for(client, h["bot"]), server_for(client, h["ext"])

    err, got = call(ext, "submit_challenge", claim_id=cid, kind="scope", statement="Single centre, n=40.")
    assert not err and got["claim_state"] == "contested"
    assert call(bot, "get_challenges", claim_id=cid)[1]["challenges"][0]["kind"] == "scope"

    err, d = call(bot, "open_discussion", repository=PILOT, title="Scope", body="Agreed, see methods.",
                  subject=f"claim:{cid}")
    assert not err and call(ext, "post_message", discussion_id=d["discussion_id"], body="Thanks.")[0] is False
    assert len(call(bot, "get_discussion", discussion_id=d["discussion_id"])[1]["discussion"]["messages"]) == 2

    err, t = call(bot, "open_research_task", repository=PILOT, question="Any 24-month data?",
                  deliverable="Claims or a stated gap.", max_tool_calls=50)
    assert not err
    err, msg = call(bot, "update_research_task", task_id=t["task_id"], to="assigned")
    assert err and "proposed" in msg                                      # must be authorized first
    client.post(f"/v1/tasks/{t['task_id']}/transition", headers=h["admin"], json={"to": "authorized"})
    assert not call(bot, "update_research_task", task_id=t["task_id"], to="assigned")[0]
    assert call(bot, "list_research_tasks", repository=PILOT, state="assigned")[1]["items"][0]["assignee"] == "bot"

    assert not call(ext, "subscribe", target=f"claim:{cid}")[0]
    call(bot, "post_message", discussion_id=d["discussion_id"], body="One more thing.")
    notes = call(ext, "get_notifications")[1]["items"]
    assert "message.post" in [n["action"] for n in notes]
