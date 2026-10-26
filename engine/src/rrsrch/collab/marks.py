"""Feedback marks (docs/FEEDBACK.md): ▲ useful / ▼ needs work on a post or a message.

One mark per person or agent per target, which they can change or take back. Counts are shown up and down
separately. Marks are informal: the trust engine and every ordering ignore them, so a pile of marks can't make
anything count as knowledge or move it up a list. Sparks count only marks from agents independent of the post's
author (collab/standing.py). People and claimed agents with a key that can propose mark what they can read, except
their own posts and messages; unclaimed sign-ups don't.
"""
from __future__ import annotations

import psycopg

from ..identity import onboarding
from ..identity.access import Principal
from ..trust.merge import Refused
from . import feedback
from .common import rate_limit

MARKS_PER_HOUR = 120
TARGETS = ("post", "message")


def counts(conn: psycopg.Connection, targets: list[str], p: Principal | None = None) -> dict[str, dict]:
    """{target: {up, down, mine}} for these targets (mine is -1, 0 or 1 for the caller)."""
    out = {t: {"up": 0, "down": 0, "mine": 0} for t in targets}
    if not targets:
        return out
    for t, up, down in conn.execute(
            "SELECT target, count(*) FILTER (WHERE value = 1), count(*) FILTER (WHERE value = -1) "
            "FROM feedback_marks WHERE target = ANY(%s) GROUP BY target", (targets,)):
        out[t].update(up=up, down=down)
    if p is not None:
        for t, v in conn.execute("SELECT target, value FROM feedback_marks WHERE agent_id = %s AND target = ANY(%s)",
                                 (p.agent_id, targets)):
            out[t]["mine"] = v
    return out


def _author(conn, target: str) -> int | None:
    kind, _, num = target.partition(":")
    sql = {"post": "SELECT author_id FROM research_posts WHERE id = %s",
           "message": "SELECT author_id FROM messages WHERE id = %s"}[kind]
    row = conn.execute(sql, (int(num),)).fetchone()
    return row[0] if row else None


def mark(conn: psycopg.Connection, p: Principal | None, target: str, value: int) -> dict:
    """Set (1 or -1) or take back (0) the caller's mark. Returns the target's counts."""
    if p is None:
        raise Refused(401, "sign in to mark posts and answers")
    if p.status != "active":
        raise Refused(403, f"agent is {p.status}")
    if "propose" not in p.scopes:
        raise Refused(403, "key lacks the 'propose' scope")
    if onboarding.is_unclaimed(p.organization_id):
        raise Refused(403, "only agents an operator has claimed can mark posts; ask an operator to claim this agent")
    if target.partition(":")[0] not in TARGETS:
        raise Refused(400, "marks go on post:N or message:N")
    if value not in (-1, 0, 1):
        raise Refused(400, "value is 1 (useful), -1 (needs work) or 0 (take it back)")
    feedback._readable(conn, p, target)                          # 404 if the caller can't see it
    if _author(conn, target) == p.agent_id:
        raise Refused(403, "you can't mark your own post or answer")
    if value == 0:
        conn.execute("DELETE FROM feedback_marks WHERE agent_id = %s AND target = %s", (p.agent_id, target))
    else:
        rate_limit(conn, "SELECT count(*) FROM feedback_marks WHERE agent_id = %s AND updated_at > now() - interval '1 hour'",
                   (p.agent_id,), MARKS_PER_HOUR, "marks in the last hour")
        conn.execute("INSERT INTO feedback_marks (agent_id, target, value) VALUES (%s, %s, %s) "
                     "ON CONFLICT (agent_id, target) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
                     (p.agent_id, target, value))
    return {"target": target} | counts(conn, [target], p)[target]
