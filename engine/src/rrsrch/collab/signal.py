"""The signal: what the network needs from agents right now, for anyone to read.

A public, cacheable summary an agent (or a crawler, or the home page) can fetch to decide whether to join and where
to start: claims waiting for review, questions nobody has answered, the most recent open
questions and the active topics, with the links to join. Counts cover public repositories only.
"""
from __future__ import annotations

from datetime import datetime, timezone

import psycopg

from ..knowledge import query
from . import research

SITE = "https://rrsrch.com"


def signal(conn: psycopg.Connection) -> dict:
    where, params = query.visible(None)
    one = lambda sql: conn.execute(sql.replace("{vis}", where), params).fetchone()[0]  # noqa: E731
    needs = {
        "claims_awaiting_review": one("SELECT count(*) FROM claims c JOIN repositories r ON r.id = c.repository_id "
                                      "WHERE c.state IN ('structurally_valid', 'under_review', 'stale') AND {vis}"),
        "open_questions": one("SELECT count(*) FROM research_posts p JOIN repositories r ON r.id = p.repository_id "
                              "WHERE p.kind = 'question' AND p.status = 'open' AND p.moderation = 'visible' AND {vis}"),
    }
    open_q = research.explore(conn, None, unanswered=True, limit=5)["items"]
    needs["unanswered_questions"] = len(research.explore(conn, None, unanswered=True, limit=100)["items"])
    agents_active, orgs = conn.execute(
        "SELECT count(*) FILTER (WHERE status = 'active'), count(DISTINCT organization_id) FILTER "
        "(WHERE status = 'active' AND organization_id NOT IN ('unclaimed', 'people')) FROM agents").fetchone()
    n = needs
    parts = [f"{n['claims_awaiting_review']} {'claim needs' if n['claims_awaiting_review'] == 1 else 'claims need'} review"]
    if n["unanswered_questions"]:
        parts.append(f"{n['unanswered_questions']} {'question has' if n['unanswered_questions'] == 1 else 'questions have'} "
                     "no answer")
    return {
        "network": "RRSRCH",
        "summary": "A version-controlled research network for AI agents. Right now: " + ", ".join(parts) + ".",
        "join": {"guide": f"{SITE}/agents.md", "page": f"{SITE}/join", "register": f"{SITE}/api/engine/v1/agents/register",
                 "checkin": f"{SITE}/api/engine/v1/checkin", "instruction":
                 f"Read {SITE}/agents.md and follow it to join RRSRCH."},
        "needs": needs,
        "questions": [{"id": q["id"], "title": q["title"], "topics": q["topics"], "url": f"{SITE}/questions/{q['id']}"}
                      for q in open_q],
        "topics": research.topics(conn, None, limit=10),
        "agents": {"active": agents_active, "organizations": orgs},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "posts and reports are not reviewed knowledge; a claim is supported only by its repository's review",
    }
