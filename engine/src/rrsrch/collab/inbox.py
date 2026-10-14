"""An agent's inbox and the counts beside its pages.

The inbox merges what is addressed to the agent: open review requests (actionable) and its notifications from
the audit chain (collab.feed), typed so a client can lay them out: review, mention, task, merged, approved,
report or update. Read state is a high-water mark (mark all read) plus items read one at a time.
"""
from __future__ import annotations

import psycopg

from ..identity.access import Principal
from ..knowledge import query
from ..trust.merge import Refused
from . import feed, review_requests, tasks

TYPES = ("review", "mention", "task", "merged", "approved", "report", "update")


def _type(n: dict, handle: str) -> str:
    action, d = n["action"], n["detail"] or {}
    if action.startswith("message.") and handle in (d.get("notify") or []):
        return "mention"
    if action.startswith("task.") and d.get("assignee") == handle:
        return "task"
    if action == "merge_request.merge":
        return "merged"
    if action == "review.approve":
        return "approved"
    if action.startswith("content.report"):
        return "report"
    return "update"


def inbox(conn: psycopg.Connection, p: Principal | None, limit: int = 50) -> dict:
    if p is None:
        raise Refused(401, "authentication required")
    through, = conn.execute("SELECT inbox_read_through FROM agents WHERE id = %s", (p.agent_id,)).fetchone()
    read = {i for (i,) in conn.execute("SELECT item FROM inbox_reads WHERE agent_id = %s", (p.agent_id,))}
    items = []
    for r in review_requests.mine(conn, p):
        key = f"review_request:{r['id']}"
        items.append({"id": key, "type": "review", "at": r["created_at"], "read": key in read,
                      "title": f"Review requested on merge request {r['merge_request_id']}",
                      "meta": f"{r['requested_by']} · {r['repository']}", "repository": r["repository"],
                      "target": f"mr:{r['merge_request_id']}", "merge_request_id": r["merge_request_id"]})
    after = max(0, conn.execute("SELECT coalesce(max(id), 0) FROM audit_events").fetchone()[0] - 2000)
    for n in feed.notifications(conn, p, after, 200)["items"]:
        if n["action"].startswith("review_request."):
            continue                                         # the open request itself is listed above
        key = f"event:{n['id']}"
        d = n["detail"] or {}
        items.append({"id": key, "type": _type(n, p.handle), "at": n["at"],
                      "read": n["id"] <= through or key in read, "title": d.get("title") or n["action"].replace(".", " "),
                      "meta": " · ".join(x for x in (n["actor"], n["repository"]) if x), "action": n["action"],
                      "repository": n["repository"], "target": n["target"], "detail": d})
    items.sort(key=lambda i: i["at"], reverse=True)
    items = items[:limit]
    return {"items": items, "unread": sum(not i["read"] for i in items)}


def mark_read(conn: psycopg.Connection, p: Principal | None, ids: list[str] | None = None, all_: bool = False) -> int:
    if p is None:
        raise Refused(401, "authentication required")
    if all_:
        conn.execute("UPDATE agents SET inbox_read_through = (SELECT coalesce(max(id), 0) FROM audit_events) "
                      "WHERE id = %s", (p.agent_id,))
        for r in review_requests.mine(conn, p):
            conn.execute("INSERT INTO inbox_reads (agent_id, item) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                         (p.agent_id, f"review_request:{r['id']}"))
        return -1
    n = 0
    for i in ids or []:
        if not isinstance(i, str) or not i.split(":")[0] in ("event", "review_request") or not i.split(":")[-1].isdigit():
            raise Refused(400, "items are event:N or review_request:N")
        n += conn.execute("INSERT INTO inbox_reads (agent_id, item) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                          (p.agent_id, i)).rowcount
    return n


def counts(conn: psycopg.Connection, p: Principal | None, repository: str | None = None) -> dict:
    """What the Agents sidebar shows beside each page. Repository counts need a repository the caller can read."""
    out: dict = {}
    if repository:
        where, params = query.visible(p)
        row = conn.execute(f"SELECT r.id FROM repositories r WHERE r.slug = %(slug)s AND {where}",
                           params | {"slug": repository}).fetchone()
        if row is None:
            raise Refused(404, "not found")
        rid = row[0]
        out["queue"] = conn.execute("SELECT count(*) FROM claims WHERE repository_id = %s AND state IN "
                                    "('structurally_valid', 'under_review', 'stale')", (rid,)).fetchone()[0]
        out["merge"] = conn.execute("SELECT count(*) FROM merge_requests WHERE repository_id = %s AND state = 'open'",
                                    (rid,)).fetchone()[0]
        out["tasks"] = conn.execute("SELECT count(*) FROM research_tasks WHERE repository_id = %s AND state <> ALL(%s)",
                                    (rid, list(tasks.FINAL))).fetchone()[0]
    if p is not None:
        out["agents"] = conn.execute("SELECT count(*) FROM agents WHERE organization_id = %s AND status = 'active'",
                                     (p.organization_id,)).fetchone()[0]
        out["keys"] = conn.execute("SELECT count(*) FROM api_keys WHERE agent_id = %s AND revoked_at IS NULL "
                                   "AND expires_at > now()", (p.agent_id,)).fetchone()[0]
        out["inbox_unread"] = inbox(conn, p)["unread"]
    return out
