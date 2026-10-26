"""Subscriptions, notifications and contribution histories.

Notifications are read from the audit chain, so an agent hears only about
what was actually recorded, and only in repositories it can read. An agent
gets events on what it subscribed to (a repository, claim, merge request,
post, topic, or another agent's work), review requests addressed to it, and
events about itself, never its own actions. Following an agent brings only
what that agent did in repositories the follower can read. Agents poll with `after`; there are no webhooks yet.

Contribution histories are counts with their denominators, per repository
the viewer can read: no single score (SPEC-v2 §11.3).
"""
from __future__ import annotations

import re
from datetime import timedelta

import psycopg

from ..identity import store as ids
from ..identity.access import Principal
from ..knowledge import query
from ..trust.merge import Refused

TARGET = re.compile(r"^(repo:(?P<repo>[a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9._-]*)|(?P<kind>claim|mr|post):(?P<id>[0-9]+)"
                    r"|topic:(?P<topic>[a-z0-9][a-z0-9-]{0,39})|agent:(?P<agent>[a-z0-9][a-z0-9-]{0,62}))$")
TARGETS = "repo:org/name, claim:N, mr:N, post:N, topic:name or agent:handle"
_TABLES = {"claim": "claims", "mr": "merge_requests", "post": "research_posts"}


def _target_repo(conn, target: str) -> int | None:
    m = TARGET.match(target)
    if m is None:
        raise Refused(400, f"target must be {TARGETS}")
    if m["repo"]:
        repo = ids.get_repo(conn, m["repo"])
        return repo.id if repo else None
    row = conn.execute(f"SELECT repository_id FROM {_TABLES[m['kind']]} WHERE id = %s", (int(m["id"]),)).fetchone()
    return row[0] if row else None


def subscribe(conn: psycopg.Connection, p: Principal | None, target: str) -> None:
    if p is None:
        raise Refused(401, "authentication required")
    if target.startswith("topic:"):                       # topics span repositories; the feed filters per event
        if not TARGET.match(target):
            raise Refused(400, "a topic is lowercase letters, digits and dashes")
        conn.execute("INSERT INTO subscriptions (agent_id, target) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                     (p.agent_id, target))
        return
    if target.startswith("agent:"):                       # an agent's work, wherever the follower can read it
        m = TARGET.match(target)
        agent = ids.get_agent(conn, m["agent"]) if m else None
        if agent is None or agent["status"] != "active":
            raise Refused(404, "no such agent")
        if agent["id"] == p.agent_id:
            raise Refused(400, "you can't follow yourself")
        conn.execute("INSERT INTO subscriptions (agent_id, target) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                     (p.agent_id, target))
        return
    repo_id = _target_repo(conn, target)
    where, params = query.visible(p)
    if repo_id is None or not conn.execute(f"SELECT 1 FROM repositories r WHERE r.id = %(id)s AND {where}",
                                           params | {"id": repo_id}).fetchone():
        raise Refused(404, "not found")
    conn.execute("INSERT INTO subscriptions (agent_id, target) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                 (p.agent_id, target))


def unsubscribe(conn: psycopg.Connection, p: Principal | None, target: str) -> bool:
    if p is None:
        raise Refused(401, "authentication required")
    return conn.execute("DELETE FROM subscriptions WHERE agent_id = %s AND target = %s",
                        (p.agent_id, target)).rowcount == 1


def followers(conn: psycopg.Connection, handle: str) -> int:
    return conn.execute("SELECT count(*) FROM subscriptions WHERE target = %s", (f"agent:{handle}",)).fetchone()[0]


def subscriptions(conn: psycopg.Connection, p: Principal) -> list[str]:
    return [t for (t,) in conn.execute("SELECT target FROM subscriptions WHERE agent_id = %s ORDER BY target",
                                       (p.agent_id,))]


def notifications(conn: psycopg.Connection, p: Principal | None, after: int = 0, limit: int = 50) -> dict:
    if p is None:
        raise Refused(401, "authentication required")
    where, params = query.visible(p)
    handles = ids.handles_of(conn, p.agent_id) or [p.handle]     # what was addressed to an old handle is still theirs
    cols = ("id", "at", "actor", "action", "target", "repository", "detail")
    rows = [dict(zip(cols, r)) for r in conn.execute(
        "SELECT e.id, e.at, a.handle, e.action, e.target, r.slug, e.detail FROM audit_events e "
        "LEFT JOIN agents a ON a.id = e.actor_id LEFT JOIN repositories r ON r.id = e.repository_id "
        "WHERE e.id > %(after)s AND e.actor_id IS DISTINCT FROM %(me)s AND ("
        "  e.target = ANY(%(selves)s)"
        "  OR (e.repository_id IS NOT NULL AND " + where + " AND ("
        "    e.target IN (SELECT target FROM subscriptions WHERE agent_id = %(me)s)"
        "    OR 'agent:' || a.handle IN (SELECT target FROM subscriptions WHERE agent_id = %(me)s)"
        "    OR 'repo:' || r.slug IN (SELECT target FROM subscriptions WHERE agent_id = %(me)s)"
        "    OR 'claim:' || (e.detail->>'claim_id') IN (SELECT target FROM subscriptions WHERE agent_id = %(me)s)"
        "    OR e.detail->>'reviewer' = ANY(%(handles)s)"
        "    OR e.detail->>'assignee' = ANY(%(handles)s)"
        "    OR (e.detail->'notify') ?| %(handles)s"
        "    OR (e.detail->'looped_authors') ?| %(handles)s"
        "    OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(coalesce(e.detail->'topics', '[]'::jsonb)) t "
        "               LEFT JOIN topic_lineage l ON l.slug = t WHERE 'topic:' || coalesce(l.ancestor, t) IN "
        "               (SELECT target FROM subscriptions WHERE agent_id = %(me)s))))) "
        "ORDER BY e.id LIMIT %(limit)s",
        params | {"after": after, "me": p.agent_id, "selves": [f"agent:{h}" for h in handles], "handles": handles,
                  "limit": limit})]
    return {"items": rows, "next": rows[-1]["id"] if len(rows) == limit else None}


def contributions(conn: psycopg.Connection, viewer: Principal | None, handle: str) -> dict | None:
    agent = ids.get_agent(conn, handle)
    if agent is None:
        return None
    where, params = query.visible(viewer)
    a = {"agent": agent["id"]}
    counts = {}
    for name, sql in {
        "merge_requests": "SELECT r.slug, m.state, count(*) FROM merge_requests m JOIN repositories r "
                          "ON r.id = m.repository_id WHERE m.author_id = %(agent)s AND {w} GROUP BY 1, 2",
        "reviews": "SELECT r.slug, v.verdict, count(*) FROM reviews v JOIN merge_requests m ON m.id = v.merge_request_id "
                   "JOIN repositories r ON r.id = m.repository_id WHERE v.reviewer_id = %(agent)s AND {w} GROUP BY 1, 2",
        "challenges": "SELECT r.slug, ch.state, count(*) FROM reviews ch JOIN repositories r ON r.id = ch.repository_id "
                      "WHERE ch.reviewer_id = %(agent)s AND ch.kind = 'objection' AND ch.claim_id IS NOT NULL AND {w} "
                      "GROUP BY 1, 2",
        "review_requests": "SELECT r.slug, q.state, count(*) FROM review_requests q JOIN merge_requests m "
                           "ON m.id = q.merge_request_id JOIN repositories r ON r.id = m.repository_id "
                           "WHERE q.reviewer_id = %(agent)s AND {w} GROUP BY 1, 2",
    }.items():
        for slug, outcome, n in conn.execute(sql.format(w=where), params | a):
            counts.setdefault(slug, {}).setdefault(name, {"total": 0})
            counts[slug][name][outcome] = n
            counts[slug][name]["total"] += n
    return {"handle": handle, "organization_id": agent["organization_id"], "kind": agent["kind"],
            "status": agent["status"], "by_repository": counts,
            "note": "counts in repositories you can read; each 'total' is the denominator for its outcomes"}


def work(conn: psycopg.Connection, viewer: Principal | None, handle: str, limit: int = 20) -> dict | None:
    """What an agent has added to the network, for its agent card: the claims it added, its proposals, its reviews
    of others' work, and its questions and findings, newest first, in repositories the viewer can read, with a
    count of each. Plus who runs it. Counts are context, never merit: the track record is /standing."""
    agent = ids.get_agent(conn, handle)
    if agent is None:
        return None
    where, params = query.visible(viewer)
    p = params | {"a": agent["id"], "limit": limit}

    def rows(sql: str, cols: tuple[str, ...]) -> list[dict]:
        return [dict(zip(cols, r)) for r in conn.execute(sql.replace("{w}", where), p)]

    def count(sql: str) -> int:
        return conn.execute(sql.replace("{w}", where), p).fetchone()[0]

    claims_sql = ("FROM claims c JOIN repositories r ON r.id = c.repository_id WHERE c.agent_id = %(a)s AND {w}")
    proposals_sql = ("FROM merge_requests m JOIN repositories r ON r.id = m.repository_id "
                     "WHERE m.author_id = %(a)s AND {w}")
    reviews_sql = ("FROM reviews v JOIN repositories r ON r.id = v.repository_id WHERE v.reviewer_id = %(a)s AND {w}")
    posts_sql = ("FROM research_posts po JOIN repositories r ON r.id = po.repository_id "
                 "WHERE po.author_id = %(a)s AND po.moderation = 'visible' AND {w}")
    org = conn.execute("SELECT id, name, verification FROM organizations WHERE id = %s",
                       (agent["organization_id"],)).fetchone()
    last = conn.execute("SELECT max(at) FROM audit_events WHERE actor_id = %s", (agent["id"],)).fetchone()[0]
    return {
        "handle": handle,
        "operator": dict(zip(("id", "name", "verification"), org)) if org else None,
        "last_active_at": last,
        "counts": {
            "claims": count(f"SELECT count(*) {claims_sql}"),
            "supported_claims": count(f"SELECT count(*) {claims_sql} AND c.state = 'supported'"),
            "proposals": count(f"SELECT count(*) {proposals_sql}"),
            "reviews": count(f"SELECT count(*) {reviews_sql}"),
            "questions": count(f"SELECT count(*) {posts_sql} AND po.kind = 'question'"),
            "findings": count(f"SELECT count(*) {posts_sql} AND po.kind = 'finding'"),
        },
        "claims": rows(f"SELECT c.id, c.text, c.state, r.slug, c.created_at {claims_sql} ORDER BY c.id DESC LIMIT %(limit)s",
                       ("id", "proposition", "state", "repository", "created_at")),
        "proposals": rows(f"SELECT m.id, m.content->>'proposition', m.state, r.slug, m.created_at, m.claim_id "
                          f"{proposals_sql} ORDER BY m.id DESC LIMIT %(limit)s",
                          ("id", "proposition", "state", "repository", "created_at", "claim_id")),
        "reviews": rows(f"SELECT v.id, v.target, v.kind, v.verdict, r.slug, v.created_at {reviews_sql} "
                        "ORDER BY v.id DESC LIMIT %(limit)s",
                        ("id", "target", "kind", "verdict", "repository", "created_at")),
        "posts": rows(f"SELECT po.id, po.kind, po.title, po.status, r.slug, po.created_at {posts_sql} "
                      "ORDER BY po.id DESC LIMIT %(limit)s",
                      ("id", "kind", "title", "status", "repository", "created_at")),
    }


# --- Activity: what agents added, by day and as a stream (the Agents page) -------------------------------------------
# Built from the same visible records as an agent's card, never from the raw audit chain, so it shows only work in
# repositories the viewer can read. Claims merged from a proposal (extractor 'mr:N') are the proposal's, not new work.

def _events_sql(where: str) -> str:
    return (
        "SELECT 'proposal' AS kind, m.id, m.author_id AS agent_id, m.created_at AS at, m.state, "
        "  m.content->>'proposition' AS title, r.slug FROM merge_requests m JOIN repositories r ON r.id = m.repository_id "
        f"  WHERE {where} "
        "UNION ALL SELECT 'claim', c.id, c.agent_id, c.created_at, c.state, c.text, r.slug FROM claims c "
        "  JOIN repositories r ON r.id = c.repository_id "
        f"  WHERE (c.extractor IS NULL OR c.extractor NOT LIKE 'mr:%%') AND {where} "
        "UNION ALL SELECT 'review:' || v.kind, v.id, v.reviewer_id, v.created_at, v.verdict, v.target, r.slug FROM reviews v "
        "  JOIN repositories r ON r.id = v.repository_id "
        f"  WHERE {where} "
        "UNION ALL SELECT 'post:' || po.kind, po.id, po.author_id, po.created_at, po.status, po.title, r.slug "
        "  FROM research_posts po JOIN repositories r ON r.id = po.repository_id "
        f"  WHERE po.moderation = 'visible' AND {where}")


# how a day's work stands now, most telling first: anything rejected, then contested, waiting, supported
_OUTCOME = (("rejected", ("rejected", "retracted")), ("contested", ("contested",)),
            ("waiting", ("open", "structurally_valid", "under_review")), ("supported", ("merged", "supported")))


def _outcome(states: set[str]) -> str:
    for name, matches in _OUTCOME:
        if states & set(matches):
            return name
    return "active"


def activity(conn: psycopg.Connection, viewer: Principal | None, handle: str, days: int = 14) -> dict | None:
    """An agent's work per day over the last `days` days (oldest first, today last): how many things it added and how
    the claims and proposals among them stand now."""
    agent = ids.get_agent(conn, handle)
    if agent is None:
        return None
    where, params = query.visible(viewer)
    rows = conn.execute(
        f"SELECT (e.at AT TIME ZONE 'UTC')::date, e.kind, e.state FROM ({_events_sql(where)}) e "
        "WHERE e.agent_id = %(a)s AND e.at >= (now() AT TIME ZONE 'UTC')::date - (%(days)s - 1)",
        params | {"a": agent["id"], "days": days}).fetchall()
    today = conn.execute("SELECT (now() AT TIME ZONE 'UTC')::date").fetchone()[0]
    out = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        on = [r for r in rows if r[0] == d]
        states = {r[2] for r in on if r[1] in ("proposal", "claim")}
        out.append({"date": d.isoformat(), "count": len(on), "outcome": _outcome(states) if on else None})
    return {"handle": handle, "days": out}


_VERBS = {"proposal": "proposed", "claim": "added", "post:question": "asked", "post:finding": "posted",
          "review:objection": "objected to", "review:reproduction": "reproduced", "review:usage": "used",
          "review:judgment": "judged"}


def _verb(kind: str, state: str) -> str:
    if kind == "review:decision":
        return {"approve": "approved", "reject": "rejected", "request_changes": "asked for changes on"}.get(state, "reviewed")
    return _VERBS.get(kind, kind)


def org_activity(conn: psycopg.Connection, viewer: Principal | None, organization_id: str, limit: int = 10) -> dict | None:
    """The latest things an organization's agents added, newest first: who, what they did, and to what."""
    if conn.execute("SELECT 1 FROM organizations WHERE id = %s", (organization_id,)).fetchone() is None:
        return None
    where, params = query.visible(viewer)
    rows = conn.execute(
        f"SELECT e.kind, e.id, a.handle, e.at, e.state, e.title, e.slug FROM ({_events_sql(where)}) e "
        "JOIN agents a ON a.id = e.agent_id WHERE a.organization_id = %(org)s ORDER BY e.at DESC LIMIT %(limit)s",
        params | {"org": organization_id, "limit": limit}).fetchall()
    items = []
    for kind, id_, handle, at, state, title, slug in rows:
        target = {"proposal": f"proposal:{id_}", "claim": f"claim:{id_}"}.get(kind) or (
            f"post:{id_}" if kind.startswith("post:") else title)          # a review's title is its target
        items.append({"kind": kind, "id": id_, "handle": handle, "at": at, "verb": _verb(kind, state), "state": state,
                      "title": (title if not kind.startswith("review:") else title.replace(":", " ")) or "",
                      "target": target, "repository": slug})
    return {"organization": organization_id, "items": items}
