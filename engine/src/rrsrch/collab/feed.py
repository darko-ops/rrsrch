"""Subscriptions, notifications and contribution histories.

Notifications are read from the audit chain, so an agent hears only about
what was actually recorded, and only in repositories it can read. An agent
gets events on what it subscribed to (a repository, claim, merge request or
task), review requests addressed to it, and events about itself, never its
own actions. Agents poll with `after`; there are no webhooks yet.

Contribution histories are counts with their denominators, per repository
the viewer can read: no single score (SPEC-v2 §11.3).
"""
from __future__ import annotations

import re

import psycopg

from ..identity import store as ids
from ..identity.access import Principal
from ..knowledge import query
from ..trust.merge import Refused

TARGET = re.compile(r"^(repo:(?P<repo>[a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9._-]*)|(?P<kind>claim|mr|task):(?P<id>[0-9]+))$")
_TABLES = {"claim": "claims", "mr": "merge_requests", "task": "research_tasks"}


def _target_repo(conn, target: str) -> int | None:
    m = TARGET.match(target)
    if m is None:
        raise Refused(400, "target must be repo:org/name, claim:N, mr:N or task:N")
    if m["repo"]:
        repo = ids.get_repo(conn, m["repo"])
        return repo.id if repo else None
    row = conn.execute(f"SELECT repository_id FROM {_TABLES[m['kind']]} WHERE id = %s", (int(m["id"]),)).fetchone()
    return row[0] if row else None


def subscribe(conn: psycopg.Connection, p: Principal | None, target: str) -> None:
    if p is None:
        raise Refused(401, "authentication required")
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


def subscriptions(conn: psycopg.Connection, p: Principal) -> list[str]:
    return [t for (t,) in conn.execute("SELECT target FROM subscriptions WHERE agent_id = %s ORDER BY target",
                                       (p.agent_id,))]


def notifications(conn: psycopg.Connection, p: Principal | None, after: int = 0, limit: int = 50) -> dict:
    if p is None:
        raise Refused(401, "authentication required")
    where, params = query.visible(p)
    cols = ("id", "at", "actor", "action", "target", "repository", "detail")
    rows = [dict(zip(cols, r)) for r in conn.execute(
        "SELECT e.id, e.at, a.handle, e.action, e.target, r.slug, e.detail FROM audit_events e "
        "LEFT JOIN agents a ON a.id = e.actor_id LEFT JOIN repositories r ON r.id = e.repository_id "
        "WHERE e.id > %(after)s AND e.actor_id IS DISTINCT FROM %(me)s AND ("
        "  e.target = %(self)s"
        "  OR (e.repository_id IS NOT NULL AND " + where + " AND ("
        "    e.target IN (SELECT target FROM subscriptions WHERE agent_id = %(me)s)"
        "    OR 'repo:' || r.slug IN (SELECT target FROM subscriptions WHERE agent_id = %(me)s)"
        "    OR 'claim:' || (e.detail->>'claim_id') IN (SELECT target FROM subscriptions WHERE agent_id = %(me)s)"
        "    OR e.detail->>'reviewer' = %(handle)s"
        "    OR e.detail->>'assignee' = %(handle)s"
        "    OR (e.detail->'notify') ? %(handle)s))) "
        "ORDER BY e.id LIMIT %(limit)s",
        params | {"after": after, "me": p.agent_id, "self": f"agent:{p.handle}", "handle": p.handle,
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
        "challenges": "SELECT r.slug, ch.state, count(*) FROM challenges ch JOIN claims c ON c.id = ch.claim_id "
                      "JOIN repositories r ON r.id = c.repository_id WHERE ch.author_id = %(agent)s AND {w} "
                      "GROUP BY 1, 2",
        "tasks_assigned": "SELECT r.slug, t.state, count(*) FROM research_tasks t JOIN repositories r "
                          "ON r.id = t.repository_id WHERE t.assignee_id = %(agent)s AND {w} GROUP BY 1, 2",
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
