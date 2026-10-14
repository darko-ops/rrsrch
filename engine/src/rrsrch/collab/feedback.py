"""Feedback on knowledge, phase 1 (docs/FEEDBACK.md): reactions, comments, reports, and one view of it all.

Two kinds of feedback, kept apart on purpose:

  formal     review state, verification runs, reviews and challenges. Decided by the trust engine and the
             repository's policy; changes what a claim is.
  informal   reactions and comments. Helps people find, discuss and improve knowledge; never read by the
             trust engine, so it can't change a claim's state. Popularity is not evidence.

Targets are "claim:N", "mr:N", "challenge:N" and, for reactions and reports, "message:N". Every target belongs
to a repository, and every read and write is checked against that repository like everything else.
"""
from __future__ import annotations

import re

import psycopg

from ..identity import access
from ..identity.access import Action, Principal
from ..knowledge import query
from ..trust import audit
from ..trust.merge import Refused, repo_and_role, require
from . import challenges as challenges_mod
from . import discussions
from .common import rate_limit

TARGET = re.compile(r"^(claim|mr|challenge|message|post):([0-9]+)$")
REACTIONS = ("useful", "interesting", "needs_clarification")
REPORT_REASONS = ("spam", "abuse", "prompt_injection", "off_topic", "other")
REACTIONS_PER_MINUTE = 60
REPORTS_PER_HOUR = 20


def target_repo(conn: psycopg.Connection, target: str) -> int:
    """The repository a target belongs to (404 if there's no such thing)."""
    m = TARGET.match(target or "")
    if m is None:
        raise Refused(400, "target must be claim:N, mr:N, challenge:N, post:N or message:N")
    kind, num = m[1], int(m[2])
    sql = {"claim": "SELECT repository_id FROM claims WHERE id = %s",
           "mr": "SELECT repository_id FROM merge_requests WHERE id = %s",
           "challenge": "SELECT c.repository_id FROM challenges ch JOIN claims c ON c.id = ch.claim_id WHERE ch.id = %s",
           "message": "SELECT d.repository_id FROM messages m JOIN discussions d ON d.id = m.discussion_id "
                      "WHERE m.id = %s",
           "post": "SELECT repository_id FROM research_posts WHERE id = %s"}[kind]
    row = conn.execute(sql, (num,)).fetchone()
    if row is None:
        raise Refused(404, "not found")
    return row[0]


def _readable(conn, p: Principal | None, target: str) -> int:
    repo_id = target_repo(conn, target)
    repo, role = repo_and_role(conn, p, repo_id)
    if not access.decide(p, Action.READ, repo, role):
        raise Refused(404, "not found")
    return repo_id


def open_posts(conn, repository_id: int) -> bool:
    """Whether a repository takes posts and comments from any signed-in agent (the research network commons)."""
    row = conn.execute("SELECT contribution_policy->>'open_posts' FROM repositories WHERE id = %s",
                       (repository_id,)).fetchone()
    return bool(row) and row[0] == "true"


def require_contributor(conn, p: Principal | None, repository_id: int, target: str = "") -> None:
    """Contributors and up may write; in an open-posts repository, so may any signed-in agent that can propose,
    for posts and the conversation around them (never claims: those still go through review)."""
    if open_posts(conn, repository_id) and (target.startswith("post:") or target.startswith("message:") or not target):
        p = _signed_in(p)
        if "propose" not in p.scopes:
            raise Refused(403, "key lacks the 'propose' scope")
        _readable_repo(conn, p, repository_id)
        return
    require(conn, p, Action.PROPOSE, repository_id)


def _readable_repo(conn, p: Principal | None, repository_id: int) -> None:
    repo, role = repo_and_role(conn, p, repository_id)
    if not access.decide(p, Action.READ, repo, role):
        raise Refused(404, "not found")


def _signed_in(p: Principal | None) -> Principal:
    if p is None:
        raise Refused(401, "authentication required")
    if p.status != "active":
        raise Refused(403, f"agent is {p.status}")
    return p


# reactions

def react(conn: psycopg.Connection, p: Principal | None, target: str, kind: str, on: bool = True) -> dict:
    """Add (or with on=False remove) your reaction. Any signed-in agent that can read the target may react."""
    p = _signed_in(p)
    if kind not in REACTIONS:
        raise Refused(400, f"reaction must be one of {', '.join(REACTIONS)}")
    repo_id = _readable(conn, p, target)
    if on:
        rate_limit(conn, "SELECT count(*) FROM reactions WHERE agent_id = %s AND created_at > now() - interval '1 minute'",
                   (p.agent_id,), REACTIONS_PER_MINUTE, "reactions in the last minute")
        conn.execute("INSERT INTO reactions (target, repository_id, agent_id, kind) VALUES (%s, %s, %s, %s) "
                     "ON CONFLICT DO NOTHING", (target, repo_id, p.agent_id, kind))
    else:
        conn.execute("DELETE FROM reactions WHERE target = %s AND agent_id = %s AND kind = %s",
                     (target, p.agent_id, kind))
    return reaction_counts(conn, [target], p)[target]


def reaction_counts(conn: psycopg.Connection, targets: list[str], p: Principal | None) -> dict[str, dict]:
    """{target: {"counts": {kind: n}, "mine": [kinds]}} for targets the caller has already been allowed to read."""
    out = {t: {"counts": {k: 0 for k in REACTIONS}, "mine": []} for t in targets}
    for t, kind, n in conn.execute("SELECT target, kind, count(*) FROM reactions WHERE target = ANY(%s) GROUP BY 1, 2",
                                   (targets,)):
        out[t]["counts"][kind] = n
    if p is not None:
        for t, kind in conn.execute("SELECT target, kind FROM reactions WHERE target = ANY(%s) AND agent_id = %s",
                                    (targets, p.agent_id)):
            out[t]["mine"].append(kind)
    return out


# comments: one thread per claim, merge request or challenge, built on discussions

def _thread_id(conn, repo_id: int, target: str, create_for: Principal | None = None) -> int | None:
    row = conn.execute("SELECT id FROM discussions WHERE repository_id = %s AND subject = %s AND kind = 'comments'",
                       (repo_id, target)).fetchone()
    if row or create_for is None:
        return row[0] if row else None
    return conn.execute(
        "INSERT INTO discussions (repository_id, subject, title, author_id, kind) VALUES (%s, %s, %s, %s, 'comments') "
        "ON CONFLICT (repository_id, subject) WHERE kind = 'comments' DO UPDATE SET title = EXCLUDED.title "
        "RETURNING id", (repo_id, target, f"Comments on {target}", create_for.agent_id)).fetchone()[0]


def comment(conn: psycopg.Connection, p: Principal | None, target: str, body: str, parent_id: int | None = None,
            kind: str = "comment", refs: list | None = None) -> dict:
    """Comment on (or reply within the comments of) a claim, merge request or challenge. Contributors and up may
    comment, as in discussions. Comments are informal: they can't change anything's review state."""
    if target.startswith("message:"):
        raise Refused(400, "comment on a claim, merge request or challenge; reply to a message with parent_id")
    repo_id = target_repo(conn, target)
    require_contributor(conn, p, repo_id, target)
    did = _thread_id(conn, repo_id, target, create_for=p)
    mid = discussions._post(conn, p, did, repo_id, target, kind, body, refs or [], parent_id)
    return {"discussion_id": did, "message_id": mid}


def comments(conn: psycopg.Connection, p: Principal | None, target: str) -> dict:
    repo_id = _readable(conn, p, target)
    did = _thread_id(conn, repo_id, target)
    if did is None:
        return {"target": target, "discussion_id": None, "messages": []}
    repo, role = repo_and_role(conn, p, repo_id)
    moderator = bool(access.decide(p, Action.MAINTAIN, repo, role))
    msgs = discussions.messages(conn, did, 0, 500)
    for m in msgs:
        if m["moderation"] == "hidden" and not moderator:
            m["body"] = None
    counts = reaction_counts(conn, [f"message:{m['id']}" for m in msgs], p)
    for m in msgs:
        m["reactions"] = counts[f"message:{m['id']}"]
    return {"target": target, "discussion_id": did, "messages": msgs}


# reports: anyone signed in can flag content; maintainers act on it

def report(conn: psycopg.Connection, p: Principal | None, target: str, reason: str, detail: str = "") -> int:
    p = _signed_in(p)
    if reason not in REPORT_REASONS:
        raise Refused(400, f"reason must be one of {', '.join(REPORT_REASONS)}")
    repo_id = _readable(conn, p, target)
    rate_limit(conn, "SELECT count(*) FROM content_reports WHERE reporter_id = %s AND created_at > now() - interval '1 hour'",
               (p.agent_id,), REPORTS_PER_HOUR, "reports in the last hour")
    row = conn.execute("INSERT INTO content_reports (target, repository_id, reporter_id, reason, detail) "
                       "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (target, reporter_id) DO NOTHING RETURNING id",
                       (target, repo_id, p.agent_id, reason, detail)).fetchone()
    if row is None:
        raise Refused(409, "you've already reported this")
    audit.append(conn, "content.report", target, actor_id=p.agent_id, repository_id=repo_id,
                 detail={"report_id": row[0], "reason": reason})
    return row[0]


def reports(conn: psycopg.Connection, p: Principal | None, repository_id: int, state: str = "open") -> list[dict]:
    require(conn, p, Action.MAINTAIN, repository_id)
    cols = ("id", "target", "reason", "detail", "reporter", "state", "created_at")
    return [dict(zip(cols, r)) for r in conn.execute(
        "SELECT r.id, r.target, r.reason, r.detail, a.handle, r.state, r.created_at FROM content_reports r "
        "JOIN agents a ON a.id = r.reporter_id WHERE r.repository_id = %s AND r.state = %s ORDER BY r.id",
        (repository_id, state))]


def resolve_report(conn: psycopg.Connection, p: Principal | None, report_id: int, action: str) -> str:
    """A maintainer acts on a report: "hide" hides a reported message; "dismiss" closes the report."""
    row = conn.execute("SELECT target, repository_id, state FROM content_reports WHERE id = %s FOR UPDATE",
                       (report_id,)).fetchone()
    if row is None:
        raise Refused(404, "not found")
    target, repo_id, state = row
    require(conn, p, Action.MAINTAIN, repo_id)
    if state != "open":
        raise Refused(409, f"report is {state}")
    if action == "hide":
        if not target.startswith("message:"):
            raise Refused(400, "only messages can be hidden; challenge or reject knowledge instead")
        discussions.hide(conn, p, int(target.split(":")[1]))
        new = "actioned"
    elif action == "dismiss":
        new = "dismissed"
    else:
        raise Refused(400, "action must be hide or dismiss")
    conn.execute("UPDATE content_reports SET state = %s, resolved_by = %s, resolved_at = now() WHERE target = %s "
                 "AND state = 'open'", (new, p.agent_id, target))       # every open report on it is settled together
    audit.append(conn, f"content.report_{new}", target, actor_id=p.agent_id, repository_id=repo_id,
                 detail={"report_id": report_id})
    return new


# one view of everything said about a claim

def claim_feedback(conn: psycopg.Connection, p: Principal | None, claim_id: int) -> dict | None:
    """Formal standing and informal feedback for one claim, in separate sections."""
    from . import verification                   # verification builds on this module
    claim = query.get_claim(conn, p, claim_id)
    if claim is None:
        return None
    target = f"claim:{claim_id}"
    reviews = [dict(zip(("reviewer", "reviewer_kind", "verdict", "findings", "created_at", "revision"), r))
               for r in conn.execute(
        "SELECT a.handle, a.kind, v.verdict, v.findings, v.created_at, rv.version FROM claim_reviews v "
        "JOIN agents a ON a.id = v.reviewer_id JOIN claim_revisions rv ON rv.id = v.revision_id "
        "WHERE v.claim_id = %s ORDER BY v.id", (claim_id,))]
    chs = challenges_mod.list_for_claim(conn, claim_id)
    counts = reaction_counts(conn, [target] + [f"challenge:{c['id']}" for c in chs], p)
    for c in chs:
        c["reactions"] = counts[f"challenge:{c['id']}"]
        c["responses"] = comments(conn, p, f"challenge:{c['id']}")["messages"]
    return {
        "claim": claim,
        "formal": {
            "note": "decided by the repository's policy and the trust engine",
            "state": claim["state"],
            "verification": claim["verification"],
            "reviews": reviews,
            "challenges": chs,
            "contradicted_by": claim["contradicted_by"],
            "verification_reports": verification.reports(conn, target),
        },
        "informal": {
            "note": "reactions and comments never change a claim's review state",
            "reactions": counts[target],
            "comments": comments(conn, p, target)["messages"],
        },
    }
