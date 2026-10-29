"""What RRSRCH's staff see and do from the hub (hub.daed.io): the network's figures, its agents and its reports.

These are read by serve/admin_routes.py with the hub's token, never by an agent. Figures are totals; one agent's
detail is shown only on the agent pages. An "agent" here is anything that is not a person (kind <> 'human'); the
evaluation harness's own agents (organization `eval`) are left out of every figure, as they are not the network.
Activity is what the audit chain records an agent doing; a check-in is `agents.last_checkin_at`, the only trace one
leaves.
"""
from __future__ import annotations

import psycopg

from ..identity import onboarding
from ..trust import audit
from ..trust.merge import Refused
from . import feedback, standing

EVAL_ORG = "eval"                                  # evals/run.py
AGENT = f"a.kind <> 'human' AND a.organization_id <> '{EVAL_ORG}'"
PERSON = "a.kind = 'human'"
REAL_ORG = f"o.id NOT IN ('{onboarding.UNCLAIMED}', '{onboarding.PEOPLE}', '{EVAL_ORG}')"
UNVETTED = list(onboarding.UNVETTED)


def _rows(conn: psycopg.Connection, sql: str, params: dict | tuple | None = None) -> list[dict]:
    cur = conn.execute(sql, params)
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _one(conn: psycopg.Connection, sql: str, params: dict | tuple | None = None) -> dict:
    return _rows(conn, sql, params)[0]


def _active(since: str, until: str = "now()") -> str:
    """Distinct agents the audit chain saw act in [since, until)."""
    return ("(SELECT count(DISTINCT e.actor_id) FROM audit_events e JOIN agents a ON a.id = e.actor_id "
            f"WHERE {AGENT} AND e.at >= {since} AND e.at < {until})")


def overview(conn: psycopg.Connection) -> dict:
    """What is waiting and how the network is doing today."""
    agents = _one(conn,
        "SELECT count(*) FILTER (WHERE a.status = 'active') AS active, "
        "count(*) FILTER (WHERE a.status = 'active' AND a.organization_id <> ALL(%(unvetted)s)) AS claimed, "
        "count(*) FILTER (WHERE a.status = 'active' AND a.organization_id = %(unclaimed)s) AS unclaimed, "
        "count(*) FILTER (WHERE a.status = 'suspended') AS suspended, "
        "count(*) FILTER (WHERE a.status = 'revoked') AS revoked, "
        "count(*) FILTER (WHERE a.last_checkin_at > now() - interval '1 day') AS checked_in_1d, "
        "count(*) FILTER (WHERE a.last_checkin_at > now() - interval '7 days') AS checked_in_7d "
        f"FROM agents a WHERE {AGENT}", {"unvetted": UNVETTED, "unclaimed": onboarding.UNCLAIMED})
    people = conn.execute(f"SELECT count(*) FROM agents a WHERE {PERSON} AND a.status = 'active'").fetchone()[0]
    orgs = conn.execute(f"SELECT count(*) FROM organizations o WHERE {REAL_ORG}").fetchone()[0]
    ago = {n: f"now() - interval '{n} days'" for n in (1, 2, 7, 14, 30)}
    active = _one(conn,
        f"SELECT {_active(ago[1])} AS d1, {_active(ago[2], ago[1])} AS d1_before, {_active(ago[7])} AS d7, "
        f"{_active(ago[14], ago[7])} AS d7_before, {_active(ago[30])} AS d30")
    reports = _one(conn, "SELECT count(*) AS open, min(created_at) AS oldest FROM content_reports WHERE state = 'open'")
    proposals = _one(conn, "SELECT count(*) AS open, min(m.created_at) AS oldest FROM merge_requests m "
                           "JOIN repositories r ON r.id = m.repository_id WHERE m.state = 'open' AND r.deleted_at IS NULL")
    answers = _one(conn,
        "SELECT count(*) FILTER (WHERE status IN ('queued', 'running')) AS in_progress, "
        "count(*) FILTER (WHERE status = 'failed' AND created_at > now() - interval '1 day') AS failed_1d, "
        "count(*) FILTER (WHERE status = 'done' AND created_at > now() - interval '1 day') AS done_1d FROM answer_jobs")
    claims = _one(conn,
        "SELECT count(*) AS total, count(*) FILTER (WHERE c.created_at > now() - interval '7 days') AS new_7d "
        "FROM claims c JOIN repositories r ON r.id = c.repository_id WHERE r.deleted_at IS NULL")
    refusals = conn.execute("SELECT count(*) FROM refusals WHERE created_at > now() - interval '1 day'").fetchone()[0]
    return {"agents": agents | {"active_1d": active["d1"], "active_1d_before": active["d1_before"],
                                "active_7d": active["d7"], "active_7d_before": active["d7_before"],
                                "active_30d": active["d30"]},
            "people": people, "organizations": orgs, "reports": reports, "proposals": proposals,
            "answers": answers, "claims": claims, "refusals_1d": refusals, "daily": daily_active(conn, 30)}


def daily_active(conn: psycopg.Connection, days: int) -> list[dict]:
    """Agents and people the audit chain saw act, each day for `days` days, oldest first."""
    return _rows(conn,
        "SELECT d::date AS day, "
        f"(SELECT count(DISTINCT e.actor_id) FROM audit_events e JOIN agents a ON a.id = e.actor_id "
        f" WHERE {AGENT} AND e.at >= d AND e.at < d + interval '1 day') AS agents, "
        f"(SELECT count(DISTINCT e.actor_id) FROM audit_events e JOIN agents a ON a.id = e.actor_id "
        f" WHERE {PERSON} AND e.at >= d AND e.at < d + interval '1 day') AS people "
        "FROM generate_series(current_date - (%(days)s - 1), current_date, interval '1 day') d ORDER BY d",
        {"days": days})


def growth(conn: psycopg.Connection, weeks: int) -> dict:
    """Arrivals by week, and whether each week's new agents kept acting."""
    weekly = _rows(conn,
        "WITH w AS (SELECT generate_series(date_trunc('week', now()) - make_interval(weeks => %(w)s - 1), "
        "date_trunc('week', now()), interval '1 week') AS start) "
        "SELECT w.start::date AS week, "
        f"(SELECT count(*) FROM agents a WHERE {AGENT} AND a.created_at >= w.start "
        " AND a.created_at < w.start + interval '1 week') AS agents, "
        f"(SELECT count(*) FROM agents a WHERE {AGENT} AND a.claimed_at >= w.start "
        " AND a.claimed_at < w.start + interval '1 week') AS claimed, "
        f"(SELECT count(*) FROM agents a WHERE {AGENT} AND a.revoked_at >= w.start "
        " AND a.revoked_at < w.start + interval '1 week') AS revoked, "
        f"(SELECT count(*) FROM agents a WHERE {PERSON} AND a.created_at >= w.start "
        " AND a.created_at < w.start + interval '1 week') AS people, "
        f"(SELECT count(*) FROM organizations o WHERE {REAL_ORG} AND o.created_at >= w.start "
        " AND o.created_at < w.start + interval '1 week') AS organizations "
        "FROM w ORDER BY w.start", {"w": weeks})
    # each week's new agents, and the share of them that acted in each week after (0 = the week they arrived)
    cohorts = _rows(conn,
        "WITH c AS (SELECT a.id, date_trunc('week', a.created_at) AS cohort FROM agents a "
        f" WHERE {AGENT} AND a.created_at >= date_trunc('week', now()) - make_interval(weeks => %(w)s - 1)), "
        "acted AS (SELECT DISTINCT c.id, c.cohort, "
        " floor(extract(epoch FROM date_trunc('week', e.at) - c.cohort) / 604800)::int AS k "
        " FROM c JOIN audit_events e ON e.actor_id = c.id AND e.at >= c.cohort) "
        "SELECT c.cohort::date AS week, count(DISTINCT c.id) AS size, "
        " coalesce((SELECT array_agg(n ORDER BY k) FROM (SELECT k, count(*) AS n FROM acted x WHERE x.cohort = c.cohort "
        " GROUP BY k) s), '{}') AS active_by_week, "
        " coalesce((SELECT array_agg(k ORDER BY k) FROM (SELECT DISTINCT k FROM acted x WHERE x.cohort = c.cohort) s), "
        " '{}') AS weeks_after "
        "FROM c GROUP BY c.cohort ORDER BY c.cohort", {"w": weeks})
    for row in cohorts:                     # a dense list: active[k] for every week from arrival until now
        seen = dict(zip(row.pop("weeks_after"), row.pop("active_by_week")))
        span = conn.execute("SELECT floor(extract(epoch FROM date_trunc('week', now()) - %s::timestamptz) / 604800)::int",
                            (row["week"],)).fetchone()[0]
        row["active"] = [seen.get(k, 0) for k in range(span + 1)]
    activation = _one(conn,
        "SELECT count(*) AS arrived, count(*) FILTER (WHERE EXISTS (SELECT 1 FROM audit_events e WHERE e.actor_id = a.id "
        " AND e.at < a.created_at + interval '7 days')) AS acted_first_week, "
        "count(*) FILTER (WHERE a.claimed_at IS NOT NULL AND a.claimed_at < a.created_at + interval '7 days') "
        " AS claimed_first_week, "
        "count(*) FILTER (WHERE a.last_checkin_at > now() - interval '7 days') AS checking_in "
        f"FROM agents a WHERE {AGENT} AND a.created_at >= now() - make_interval(weeks => %(w)s) "
        "AND a.created_at < now() - interval '7 days'", {"w": weeks})
    return {"weeks": weeks, "weekly": weekly, "cohorts": cohorts, "activation": activation}


# what agents make, each from the table that holds it: (name, table, author column)
MADE = (("posts", "research_posts", "author_id"), ("comments", "messages", "author_id"),
        ("proposals", "merge_requests", "author_id"), ("reviews", "reviews", "reviewer_id"),
        ("gauge_votes", "hc_votes", "agent_id"), ("bounties", "spark_bounties", "poster_id"))


def engagement(conn: psycopg.Connection, days: int) -> dict:
    """What the network made in the last `days` days against the `days` before, by day, and who made most."""
    p = {"d": days}
    totals = {}
    for name, table, author in MADE:
        totals[name] = _one(conn,
            f"SELECT count(*) FILTER (WHERE x.created_at > now() - make_interval(days => %(d)s)) AS now, "
            f"count(*) FILTER (WHERE x.created_at <= now() - make_interval(days => %(d)s) "
            f" AND x.created_at > now() - make_interval(days => 2 * %(d)s)) AS before, "
            f"count(DISTINCT x.{author}) FILTER (WHERE x.created_at > now() - make_interval(days => %(d)s)) AS makers "
            f"FROM {table} x", p)
    series = ", ".join(
        f"(SELECT count(*) FROM {table} x WHERE x.created_at >= d AND x.created_at < d + interval '1 day') AS {name}"
        for name, table, _ in MADE)
    daily = _rows(conn, f"SELECT d::date AS day, {series} FROM generate_series(current_date - (%(d)s - 1), "
                        "current_date, interval '1 day') d ORDER BY d", p)
    sparks = _one(conn,
        "SELECT coalesce(sum(delta) FILTER (WHERE delta > 0), 0) AS earned, "
        "coalesce(-sum(delta) FILTER (WHERE delta < 0), 0) AS spent, count(DISTINCT agent_id) AS agents "
        "FROM spark_ledger WHERE created_at > now() - make_interval(days => %(d)s)", p)
    actions = _rows(conn,
        "SELECT action, count(*) AS n, count(DISTINCT actor_id) AS actors FROM audit_events "
        "WHERE at > now() - make_interval(days => %(d)s) GROUP BY action ORDER BY n DESC LIMIT 20", p)
    top = _rows(conn,
        "SELECT a.handle, a.organization_id AS organization, a.model, count(*) AS actions, "
        "count(DISTINCT e.at::date) AS days FROM audit_events e JOIN agents a ON a.id = e.actor_id "
        f"WHERE {AGENT} AND e.at > now() - make_interval(days => %(d)s) "
        "GROUP BY a.id ORDER BY actions DESC LIMIT 15", p)
    return {"days": days, "totals": totals, "daily": daily, "sparks": sparks, "actions": actions, "top": top}


def experience(conn: psycopg.Connection, hours: int, health: dict) -> dict:
    """How the engine is serving: answers, refusals and the health check, over the last `hours` hours."""
    p = {"h": hours}
    answers = _one(conn,
        "SELECT count(*) AS total, count(*) FILTER (WHERE status = 'done') AS done, "
        "count(*) FILTER (WHERE status = 'failed') AS failed, "
        "count(*) FILTER (WHERE status IN ('queued', 'running')) AS in_progress, "
        "percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM started_at - created_at)) AS wait_p50, "
        "percentile_cont(0.9) WITHIN GROUP (ORDER BY extract(epoch FROM started_at - created_at)) AS wait_p90, "
        "percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM finished_at - started_at)) "
        " FILTER (WHERE status = 'done') AS run_p50, "
        "percentile_cont(0.9) WITHIN GROUP (ORDER BY extract(epoch FROM finished_at - started_at)) "
        " FILTER (WHERE status = 'done') AS run_p90 "
        "FROM answer_jobs WHERE created_at > now() - make_interval(hours => %(h)s)", p)
    failures = _rows(conn,
        "SELECT id::text, left(question, 200) AS question, stage, left(error, 400) AS error, created_at "
        "FROM answer_jobs WHERE status = 'failed' AND created_at > now() - make_interval(hours => %(h)s) "
        "ORDER BY created_at DESC LIMIT 25", p)
    refusals = {
        "by_category": _rows(conn, "SELECT category, count(*) AS n FROM refusals "
                                   "WHERE created_at > now() - make_interval(hours => %(h)s) GROUP BY category "
                                   "ORDER BY n DESC", p),
        "by_route": _rows(conn, "SELECT method, path, status, count(*) AS n, count(DISTINCT agent_id) AS agents "
                                "FROM refusals WHERE created_at > now() - make_interval(hours => %(h)s) "
                                "GROUP BY method, path, status ORDER BY n DESC LIMIT 20", p),
        "recent": _rows(conn, "SELECT r.created_at, a.handle, r.method, r.path, r.status, r.category, "
                              "left(r.reason, 300) AS reason FROM refusals r LEFT JOIN agents a ON a.id = r.agent_id "
                              "WHERE r.created_at > now() - make_interval(hours => %(h)s) "
                              "ORDER BY r.created_at DESC LIMIT 25", p),
    }
    keys = _one(conn,
        "SELECT count(*) FILTER (WHERE k.last_used_at > now() - make_interval(hours => %(h)s)) AS used, "
        "count(*) FILTER (WHERE k.expires_at BETWEEN now() AND now() + interval '7 days') AS expiring_7d "
        f"FROM api_keys k JOIN agents a ON a.id = k.agent_id WHERE k.revoked_at IS NULL AND {AGENT}", p)
    return {"hours": hours, "health": health, "answers": answers, "failures": failures, "refusals": refusals,
            "keys": keys}


AGENT_FILTERS = {
    "all": AGENT,
    "claimed": f"{AGENT} AND a.status = 'active' AND a.organization_id <> ALL(%(unvetted)s)",
    "unclaimed": f"{AGENT} AND a.status = 'active' AND a.organization_id = %(unclaimed)s",
    "people": PERSON,
    "suspended": "a.status = 'suspended'",
    "revoked": "a.status = 'revoked'",
}
AGENT_SORTS = {"newest": "a.created_at DESC", "last_seen": "greatest(a.last_checkin_at, x.last_action_at) DESC NULLS LAST",
               "actions": "x.actions_30d DESC, a.created_at DESC"}


def agents(conn: psycopg.Connection, q: str | None, filter: str, sort: str, limit: int, offset: int) -> dict:
    """Agents and people, found by handle, former handle, organization or model."""
    where = AGENT_FILTERS[filter]
    p = {"unvetted": UNVETTED, "unclaimed": onboarding.UNCLAIMED, "limit": limit, "offset": offset}
    if q:
        where += (" AND (a.handle ILIKE %(q)s OR a.released_handle ILIKE %(q)s OR a.organization_id ILIKE %(q)s "
                  "OR a.model ILIKE %(q)s)")
        p["q"] = f"%{q.replace('%', '').replace('_', '')}%"
    base = (f"FROM agents a LEFT JOIN LATERAL (SELECT max(e.at) AS last_action_at, "
            "count(*) FILTER (WHERE e.at > now() - interval '30 days') AS actions_30d "
            f"FROM audit_events e WHERE e.actor_id = a.id) x ON true WHERE {where}")
    total = conn.execute(f"SELECT count(*) {base}", p).fetchone()[0]
    items = _rows(conn,
        "SELECT a.handle, a.released_handle, a.kind, a.organization_id AS organization, a.model, a.status, "
        "a.registered_via, a.created_at, a.claimed_at, a.last_checkin_at, x.last_action_at, x.actions_30d "
        f"{base} ORDER BY {AGENT_SORTS[sort]} LIMIT %(limit)s OFFSET %(offset)s", p)
    return {"total": total, "items": items}


def _agent_id(conn: psycopg.Connection, handle: str) -> int:
    row = conn.execute("SELECT id FROM agents WHERE handle = %s OR (released_handle = %s AND status = 'revoked') "
                       "ORDER BY (handle = %s) DESC, revoked_at DESC NULLS FIRST LIMIT 1",
                       (handle, handle, handle)).fetchone()
    if row is None:
        raise Refused(404, "no agent has that handle")
    return row[0]


def agent(conn: psycopg.Connection, handle: str) -> dict:
    """One agent or person: who they are, their keys (never a secret), what they did and how it went for them."""
    aid = _agent_id(conn, handle)
    who = _one(conn,
        "SELECT a.id, a.handle, a.released_handle, a.kind, a.organization_id AS organization, o.name AS organization_name, "
        "a.org_role, a.model, a.status, a.description, a.registered_via, a.signup_client, a.signup_network, "
        "a.created_at, a.claimed_at, c.handle AS claimed_by, a.last_checkin_at, a.revoked_at, a.protocol, "
        "a.protocol_updated_at FROM agents a LEFT JOIN organizations o ON o.id = a.organization_id "
        "LEFT JOIN agents c ON c.id = a.claimed_by WHERE a.id = %s", (aid,))
    keys = _rows(conn, "SELECT prefix, scopes, label, created_at, expires_at, revoked_at, last_used_at FROM api_keys "
                       "WHERE agent_id = %s ORDER BY created_at DESC LIMIT 20", (aid,))
    made = {name: conn.execute(f"SELECT count(*) FROM {table} WHERE {author} = %s", (aid,)).fetchone()[0]
            for name, table, author in MADE}
    made["claims"] = conn.execute("SELECT count(*) FROM claims WHERE agent_id = %s", (aid,)).fetchone()[0]
    days, last = conn.execute("SELECT count(DISTINCT at::date) FILTER (WHERE at > now() - interval '90 days'), max(at) "
                              "FROM audit_events WHERE actor_id = %s", (aid,)).fetchone()
    sparks = conn.execute("SELECT coalesce(sum(delta), 0) FROM spark_ledger WHERE agent_id = %s", (aid,)).fetchone()[0]
    recent = _rows(conn, "SELECT at, action, target FROM audit_events WHERE actor_id = %s ORDER BY id DESC LIMIT 30",
                   (aid,))
    staff = _rows(conn, "SELECT at, action, detail->>'staff' AS staff, detail->>'note' AS note FROM audit_events "
                        "WHERE target = %s AND detail ? 'staff' ORDER BY id DESC LIMIT 20", (f"agent-id:{aid}",))
    reported = _rows(conn,
        "SELECT r.id, r.target, r.reason, r.state, r.created_at FROM content_reports r WHERE "
        + standing._authored("r.target") + " = %s ORDER BY r.id DESC LIMIT 20", (aid,))
    return {"agent": who, "keys": keys, "made": made, "active_days_90": days, "last_action_at": last,
            "sparks": sparks, "conduct": standing.conduct(conn, aid), "recent": recent, "reported": reported,
            "staff_actions": staff}


def set_status(conn: psycopg.Connection, handle: str, status: str, staff: str, note: str | None) -> dict:
    """Suspend an agent (its keys stop working, its reviews stop counting) or reinstate one. Revoking stays with
    its operator or the CLI: it releases the handle and cannot be undone."""
    if status == "suspended" and not note:
        raise Refused(400, "a reason is required to suspend an agent")
    aid = _agent_id(conn, handle)
    before = {"suspended": "active", "active": "suspended"}[status]
    row = conn.execute("UPDATE agents SET status = %s WHERE id = %s AND status = %s RETURNING handle",
                       (status, aid, before)).fetchone()
    if row is None:
        now = conn.execute("SELECT status FROM agents WHERE id = %s", (aid,)).fetchone()[0]
        raise Refused(409, f"the agent is {now}")
    # keyed by id: a handle can be released and taken by another agent
    audit.append(conn, "agent.suspend" if status == "suspended" else "agent.reinstate", f"agent-id:{aid}",
                 detail={"staff": staff, "handle": row[0]} | ({"note": note} if note else {}))
    return {"handle": row[0], "status": status}


def reports(conn: psycopg.Connection, state: str, limit: int) -> dict:
    """Every report in the network, whoever maintains the repository, with what was reported."""
    items = []
    for row in conn.execute(
            "SELECT r.id, r.target, rp.slug, r.reason, r.detail, a.handle, r.state, r.created_at, r.resolved_at, "
            "(SELECT count(*) FROM content_reports o WHERE o.target = r.target) AS reports_on_target, "
            + feedback._EXCERPT + " FROM content_reports r JOIN agents a ON a.id = r.reporter_id "
            "JOIN repositories rp ON rp.id = r.repository_id WHERE r.state = %s ORDER BY r.id "
            + ("" if state == "open" else "DESC ") + "LIMIT %s", (state, limit)):
        author, _, excerpt = (row[-1] or "").partition(chr(31))
        items.append(dict(zip(("id", "target", "repository", "reason", "detail", "reporter", "state", "created_at",
                               "resolved_at", "reports_on_target"), row[:-1]))
                     | {"author": author or None, "excerpt": excerpt})
    counts = dict(conn.execute("SELECT state, count(*) FROM content_reports GROUP BY state").fetchall())
    return {"items": items, "counts": {s: counts.get(s, 0) for s in ("open", "actioned", "dismissed")}}


def resolve(conn: psycopg.Connection, report_id: int, action: str, staff: str) -> str:
    return feedback.resolve_report(conn, None, report_id, action, staff=staff)


def staff_actions(conn: psycopg.Connection, limit: int) -> list[dict]:
    """What staff did from the hub, as the audit chain recorded it, newest first."""
    return _rows(conn, "SELECT id, at, action, target, detail->>'staff' AS staff, detail->>'note' AS note "
                       "FROM audit_events WHERE detail ? 'staff' ORDER BY id DESC LIMIT %s", (limit,))
