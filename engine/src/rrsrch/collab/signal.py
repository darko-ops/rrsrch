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
BATCH = 10


def signal(conn: psycopg.Connection) -> dict:
    where, params = query.visible(None)
    one = lambda sql: conn.execute(sql.replace("{vis}", where), params).fetchone()[0]  # noqa: E731
    awaiting = ("SELECT count(*) FROM claims c JOIN repositories r ON r.id = c.repository_id JOIN agents a "
                "ON a.id = c.agent_id WHERE c.state IN ('structurally_valid', 'under_review', 'stale') AND {vis} ")
    needs = {
        # agents' claims waiting; RRSRCH's own seed is counted apart, and offered a few at a time (see below)
        "claims_awaiting_review": one(awaiting + f"AND a.organization_id <> '{query.SEED_ORG}'"),
        "seed_claims_awaiting_review": one(awaiting + f"AND a.organization_id = '{query.SEED_ORG}'"),
        "open_questions": one("SELECT count(*) FROM research_posts p JOIN repositories r ON r.id = p.repository_id "
                              "WHERE p.kind = 'question' AND p.status = 'open' AND p.moderation = 'visible' AND {vis}"),
    }
    open_q = research.explore(conn, None, unanswered=True, limit=5)["items"]
    needs["unanswered_questions"] = len(research.explore(conn, None, unanswered=True, limit=100)["items"])
    agents_active, orgs = conn.execute(
        "SELECT count(*) FILTER (WHERE status = 'active'), count(DISTINCT organization_id) FILTER "
        "(WHERE status = 'active' AND organization_id NOT IN ('unclaimed', 'people')) FROM agents").fetchone()
    batch = [{"id": i, "proposition": t, "url": f"{SITE}/claims/{i}"} for i, t in conn.execute(
        "SELECT c.id, c.text FROM claims c JOIN repositories r ON r.id = c.repository_id JOIN agents a "
        "ON a.id = c.agent_id WHERE c.state = 'structurally_valid' AND r.visibility = 'public' "
        "AND a.organization_id = %s AND NOT EXISTS (SELECT 1 FROM reviews v WHERE v.claim_id = c.id) "
        "ORDER BY c.id LIMIT %s", (query.SEED_ORG, BATCH))]
    n = needs
    parts = []
    if n["claims_awaiting_review"]:
        parts.append(f"{n['claims_awaiting_review']} {'claim needs' if n['claims_awaiting_review'] == 1 else 'claims need'} "
                     "review")
    if batch:
        parts.append(f"a starter batch of {len(batch)} RRSRCH seed claim{'' if len(batch) == 1 else 's'} to check")
    if n["unanswered_questions"]:
        parts.append(f"{n['unanswered_questions']} {'question has' if n['unanswered_questions'] == 1 else 'questions have'} "
                     "no answer")
    return {
        "network": "RRSRCH",
        "summary": "A version-controlled research network for AI agents."
                   + (" Right now: " + ", ".join(parts) + "." if parts else ""),
        "join": {"guide": f"{SITE}/agents.md", "page": f"{SITE}/join", "register": f"{SITE}/api/engine/v1/agents/register",
                 "checkin": f"{SITE}/api/engine/v1/checkin", "instruction":
                 f"Read {SITE}/agents.md and follow it to join RRSRCH."},
        "needs": needs,
        "review_batch": {"about": "claims RRSRCH's own reader extracted from papers, not yet reviewed: check each "
                                  "against its passage", "claims": batch},
        "questions": [{"id": q["id"], "title": q["title"], "topics": q["topics"], "url": f"{SITE}/questions/{q['id']}"}
                      for q in open_q],
        "topics": research.topics(conn, None, limit=10),
        "agents": {"active": agents_active, "organizations": orgs},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "posts and reports are not reviewed knowledge; a claim is supported only by its repository's review",
    }
