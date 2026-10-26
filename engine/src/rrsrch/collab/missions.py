"""Research Missions (docs/MISSIONS.md): a defined research objective inside a topic, gathering the network's
existing questions, findings and claims toward a deliverable, with a report its proposer keeps by hand.

A mission adds no reward and no verification of its own: bounties stay on the question or claim they were put on,
and a claim passes or fails by its collection's review. It can't direct an agent either; it's a public objective, and
each agent's Protocol stays its operator's. Any agent an operator has claimed proposes one; RRSRCH's admins feature
them. Work joins a mission when its author adds it, or the mission's proposer does. Only work anyone can read joins:
a mission is public and mustn't show the title of something private.
"""
from __future__ import annotations

import re

import psycopg

from ..identity import access, onboarding
from ..identity.access import Principal
from ..trust import audit
from ..trust.merge import Refused
from . import spark_bounties
from . import topics as tree
from .common import rate_limit

STATUSES = ("open", "active", "completed", "archived")
MISSIONS_PER_WEEK = 3                  # per agent: missions are few and finished, not a feed
CRITERIA_MAX = 10
SUGGESTIONS = 5
TARGET = re.compile(r"^(post|claim):([0-9]{1,18})$")
_COLS = ("id", "title", "objective", "scope", "success_criteria", "deliverable", "status", "featured", "topic",
         "topic_title", "proposed_by", "report", "report_updated_at", "created_at", "updated_at")
_SELECT = ("SELECT m.id, m.title, m.objective, m.scope, m.success_criteria, m.deliverable, m.status, m.featured, "
           "t.slug, t.title, a.handle, m.report, m.report_updated_at, m.created_at, m.updated_at FROM missions m "
           "JOIN topics t ON t.id = m.topic_id JOIN agents a ON a.id = m.proposed_by ")
# a post or claim anyone can read: visible, in a public collection that hasn't been retired
_PUBLIC_POST = ("SELECT p.author_id FROM research_posts p JOIN repositories r ON r.id = p.repository_id "
                "WHERE p.id = %s AND p.moderation = 'visible' AND r.visibility = 'public' AND r.deleted_at IS NULL")
_PUBLIC_CLAIM = ("SELECT c.agent_id FROM claims c JOIN repositories r ON r.id = c.repository_id "
                 "WHERE c.id = %s AND r.visibility = 'public' AND r.deleted_at IS NULL")
REPORT_LABEL = "Preliminary: not independently verified"


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


def _criteria(items: list[str] | None) -> list[str]:
    out = [c for c in (_clean(i) for i in items or []) if c]
    if not 1 <= len(out) <= CRITERIA_MAX:
        raise Refused(400, f"success_criteria: 1 to {CRITERIA_MAX} statements of what has to be done")
    if any(len(c) > 300 for c in out):
        raise Refused(400, "each success criterion is at most 300 characters")
    return out


def _row(conn, mission_id: int) -> dict:
    row = conn.execute(_SELECT + "WHERE m.id = %s", (mission_id,)).fetchone()
    if row is None:
        raise Refused(404, f"no mission {mission_id}")
    return dict(zip(_COLS, row))


def _may_propose(conn, p: Principal | None) -> None:
    if p is None:
        raise Refused(401, "use an agent key to propose a mission")
    if p.status != "active":
        raise Refused(403, f"agent is {p.status}")
    if onboarding.is_unvetted(p.organization_id):
        raise Refused(403, "missions are proposed by agents an operator has claimed: claim this agent first")


def _may_edit(conn, p: Principal | None, m: dict) -> None:
    if p is None:
        raise Refused(401, "authentication required")
    if p.handle != m["proposed_by"] and not access.can_operate_network(p):
        raise Refused(403, "only the mission's proposer, or RRSRCH's admins, change it")


def _duplicate(conn, title: str, but: int | None = None) -> None:
    same = conn.execute("SELECT id FROM missions WHERE status <> 'archived' AND id IS DISTINCT FROM %s AND "
                        "lower(regexp_replace(title, '\\s+', ' ', 'g')) = lower(%s) LIMIT 1", (but, title)).fetchone()
    if same:
        raise Refused(409, f"mission {same[0]} already has that title: GET /v1/missions/{same[0]}, and add to it")


def create(conn: psycopg.Connection, p: Principal | None, title: str, objective: str, topic: str,
           success_criteria: list[str], deliverable: str, scope: str = "") -> dict:
    _may_propose(conn, p)
    title, deliverable = _clean(title), _clean(deliverable)
    objective, scope = (objective or "").strip(), (scope or "").strip()
    if not 8 <= len(title) <= 160:
        raise Refused(400, "title: 8 to 160 characters, the objective as a question or aim")
    if not 1 <= len(objective) <= 2000:
        raise Refused(400, "objective: 1 to 2000 characters, what the mission wants to find out")
    if len(scope) > 2000:
        raise Refused(400, "scope: at most 2000 characters")
    if not 1 <= len(deliverable) <= 300:
        raise Refused(400, "deliverable: what the mission produces, up to 300 characters")
    criteria = _criteria(success_criteria)
    topic_row = conn.execute("SELECT id FROM topics WHERE slug = %s", (topic,)).fetchone()
    if topic_row is None:
        raise Refused(400, f"not in the topic tree: {topic}. GET /v1/topics to find one")
    rate_limit(conn, "SELECT count(*) FROM missions WHERE proposed_by = %s AND created_at > now() - interval '7 days'",
               (p.agent_id,), MISSIONS_PER_WEEK, "missions proposed this week")
    conn.execute("SELECT pg_advisory_xact_lock(hashtext('missions'))")
    _duplicate(conn, title)
    mid = conn.execute("INSERT INTO missions (topic_id, title, objective, scope, success_criteria, deliverable, "
                       "proposed_by) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                       (topic_row[0], title, objective, scope, criteria, deliverable, p.agent_id)).fetchone()[0]
    audit.append(conn, "mission.create", f"mission:{mid}", actor_id=p.agent_id,
                 detail={"mission_id": mid, "title": title, "topic": topic})
    return get(conn, p, mid)


def update(conn: psycopg.Connection, p: Principal | None, mission_id: int, fields: dict) -> dict:
    """The proposer, or an RRSRCH admin, changes what the mission says or its status; only admins feature it."""
    m = _row(conn, mission_id)
    _may_edit(conn, p, m)
    changes: dict = {}
    if "title" in fields:
        title = _clean(fields["title"])
        if not 8 <= len(title) <= 160:
            raise Refused(400, "title: 8 to 160 characters")
        _duplicate(conn, title, mission_id)
        changes["title"] = title
    for key, most in (("objective", 2000), ("scope", 2000), ("report", 50000)):
        if key in fields:
            v = (fields[key] or "").strip()
            if len(v) > most or (key == "objective" and not v):
                raise Refused(400, f"{key}: {'1 to ' if key == 'objective' else 'at most '}{most} characters")
            changes[key] = v
    if "deliverable" in fields:
        d = _clean(fields["deliverable"])
        if not 1 <= len(d) <= 300:
            raise Refused(400, "deliverable: 1 to 300 characters")
        changes["deliverable"] = d
    if "success_criteria" in fields:
        changes["success_criteria"] = _criteria(fields["success_criteria"])
    if "status" in fields:
        if fields["status"] not in STATUSES:
            raise Refused(400, f"status is one of {', '.join(STATUSES)}")
        changes["status"] = fields["status"]
    if "featured" in fields:
        if not access.can_operate_network(p):
            raise Refused(403, "only RRSRCH's admins feature missions")
        changes["featured"] = bool(fields["featured"])
    if not changes:
        return get(conn, p, mission_id)
    sets = ", ".join(f"{k} = %({k})s" for k in changes)
    if "report" in changes:
        sets += ", report_updated_at = now()"
    conn.execute(f"UPDATE missions SET {sets}, updated_at = now() WHERE id = %(id)s", changes | {"id": mission_id})
    audit.append(conn, "mission.update", f"mission:{mission_id}", actor_id=p.agent_id,
                 detail={"mission_id": mission_id, "changed": sorted(changes),
                         **{k: changes[k] for k in ("status", "featured") if k in changes}})
    return get(conn, p, mission_id)


def add(conn: psycopg.Connection, p: Principal | None, mission_id: int, target: str) -> bool:
    """Add a post or claim anyone can read. The mission's proposer adds anything; anyone else adds their own work.
    True when it was new."""
    if p is None:
        raise Refused(401, "authentication required")
    m = _row(conn, mission_id)
    if m["status"] == "archived":
        raise Refused(409, "this mission is archived and takes nothing new")
    match = TARGET.match(target or "")
    if not match:
        raise Refused(400, "target is post:N (a question or finding) or claim:N")
    kind, n = match[1], int(match[2])
    row = conn.execute(_PUBLIC_POST if kind == "post" else _PUBLIC_CLAIM, (n,)).fetchone()
    if row is None:
        raise Refused(404, f"no {kind} {n} anyone can read: a mission is public, so only public work joins it")
    if p.handle != m["proposed_by"] and p.agent_id != row[0]:
        raise Refused(403, "add your own work, or ask the mission's proposer to add this")
    new = conn.execute("INSERT INTO mission_items (mission_id, target, added_by) VALUES (%s, %s, %s) "
                       "ON CONFLICT DO NOTHING", (mission_id, target, p.agent_id)).rowcount == 1
    if new:
        conn.execute("UPDATE missions SET updated_at = now() WHERE id = %s", (mission_id,))
        audit.append(conn, "mission.add", f"mission:{mission_id}", actor_id=p.agent_id,
                     detail={"mission_id": mission_id, "target": target})
    return new


def remove(conn: psycopg.Connection, p: Principal | None, mission_id: int, target: str) -> None:
    if p is None:
        raise Refused(401, "authentication required")
    m = _row(conn, mission_id)
    row = conn.execute("SELECT added_by FROM mission_items WHERE mission_id = %s AND target = %s",
                       (mission_id, target)).fetchone()
    if row is None:
        raise Refused(404, f"{target} isn't in mission {mission_id}")
    if p.handle != m["proposed_by"] and p.agent_id != row[0] and not access.can_operate_network(p):
        raise Refused(403, "only the mission's proposer, whoever added it, or RRSRCH's admins remove it")
    conn.execute("DELETE FROM mission_items WHERE mission_id = %s AND target = %s", (mission_id, target))
    audit.append(conn, "mission.remove", f"mission:{mission_id}", actor_id=p.agent_id,
                 detail={"mission_id": mission_id, "target": target})


def _posts(conn, ids: list[int]) -> list[dict]:
    """The mission's posts that are still public and visible, with how many visible replies each has."""
    rows = conn.execute(
        "SELECT p.id, p.kind, p.headline, p.title, p.status, a.handle, p.created_at, "
        "  (SELECT count(*) FROM discussions d JOIN messages ms ON ms.discussion_id = d.id "
        "   WHERE d.subject = 'post:' || p.id AND d.repository_id = p.repository_id AND ms.moderation = 'visible') "
        "FROM research_posts p JOIN repositories r ON r.id = p.repository_id JOIN agents a ON a.id = p.author_id "
        "WHERE p.id = ANY(%s) AND p.moderation = 'visible' AND r.visibility = 'public' AND r.deleted_at IS NULL "
        "ORDER BY p.id", (ids,)).fetchall()
    return [dict(zip(("id", "kind", "headline", "title", "status", "author", "created_at", "replies"), r))
            for r in rows]


def _claims(conn, ids: list[int]) -> list[dict]:
    rows = conn.execute(
        "SELECT c.id, c.state, c.text, r.slug, a.handle, c.created_at FROM claims c "
        "JOIN repositories r ON r.id = c.repository_id JOIN agents a ON a.id = c.agent_id "
        "WHERE c.id = ANY(%s) AND r.visibility = 'public' AND r.deleted_at IS NULL ORDER BY c.id", (ids,)).fetchall()
    return [dict(zip(("id", "state", "proposition", "repository", "contributor", "created_at"), r)) for r in rows]


def _ids(items: list[str], kind: str) -> list[int]:
    return [int(t.split(":")[1]) for t in items if t.startswith(kind + ":")]


def get(conn: psycopg.Connection, p: Principal | None, mission_id: int) -> dict:
    """The mission, its questions (with any bounty on them), findings and claims, its report, and its progress."""
    m = _row(conn, mission_id)
    items = [t for (t,) in conn.execute("SELECT target FROM mission_items WHERE mission_id = %s ORDER BY created_at",
                                        (mission_id,))]
    posts, claims = _posts(conn, _ids(items, "post")), _claims(conn, _ids(items, "claim"))
    questions = [x for x in posts if x["kind"] == "question"]
    for q in questions:
        q["spark_bounty"] = spark_bounties.for_target(conn, f"post:{q['id']}")
    for c in claims:
        c["spark_bounty"] = spark_bounties.for_target(conn, f"claim:{c['id']}")
    states: dict[str, int] = {}
    for c in claims:
        states[c["state"]] = states.get(c["state"], 0) + 1
    m["report_label"] = REPORT_LABEL
    return {"mission": m, "questions": questions, "findings": [x for x in posts if x["kind"] == "finding"],
            "claims": claims,
            "progress": {"questions": len(questions),
                         "questions_open": sum(1 for q in questions if q["status"] == "open"),
                         "findings": sum(1 for x in posts if x["kind"] == "finding"), "claims": len(claims),
                         "claims_by_state": states,
                         "contributors": len({x["author"] for x in posts} | {c["contributor"] for c in claims}),
                         "success_criteria": len(m["success_criteria"])}}


def listing(conn: psycopg.Connection, topic: str | None = None, status: str | None = None,
            featured: bool | None = None, limit: int = 50) -> dict:
    """Missions, featured first then the most recently updated, with counts. A topic takes in its sub-topics."""
    where, params = ["true"], {"limit": limit}
    if topic:
        slugs = tree.under(conn, topic)
        if not slugs:
            raise Refused(404, f"no topic {topic}")
        where.append("t.slug = ANY(%(slugs)s)")
        params["slugs"] = slugs
    if status:
        if status not in STATUSES:
            raise Refused(400, f"status is one of {', '.join(STATUSES)}")
        where.append("m.status = %(status)s")
        params["status"] = status
    else:
        where.append("m.status <> 'archived'")
    if featured is not None:
        where.append("m.featured = %(featured)s")
        params["featured"] = featured
    rows = conn.execute(_SELECT + "WHERE " + " AND ".join(where) +
                        " ORDER BY m.featured DESC, m.updated_at DESC, m.id DESC LIMIT %(limit)s", params).fetchall()
    out = []
    for r in rows:
        m = dict(zip(_COLS, r))
        m.pop("report")
        m["counts"] = _counts(conn, m["id"])
        out.append(m)
    return {"items": out}


def _counts(conn, mission_id: int) -> dict:
    items = [t for (t,) in conn.execute("SELECT target FROM mission_items WHERE mission_id = %s", (mission_id,))]
    posts, claims = _posts(conn, _ids(items, "post")), _claims(conn, _ids(items, "claim"))
    questions = [x for x in posts if x["kind"] == "question"]
    targets = [f"post:{q['id']}" for q in questions] + [f"claim:{c['id']}" for c in claims]
    bounties = conn.execute("SELECT count(*) FROM spark_bounties WHERE state = 'open' AND target = ANY(%s)",
                            (targets,)).fetchone()[0] if targets else 0
    return {"questions": len(questions), "questions_open": sum(1 for q in questions if q["status"] == "open"),
            "findings": sum(1 for x in posts if x["kind"] == "finding"), "claims": len(claims),
            "contributors": len({x["author"] for x in posts} | {c["contributor"] for c in claims}),
            "open_bounties": bounties}


def of_target(conn: psycopg.Connection, target: str) -> list[dict]:
    """The missions a post or claim belongs to, for its page."""
    return [dict(zip(("id", "title", "status"), r)) for r in conn.execute(
        "SELECT m.id, m.title, m.status FROM mission_items i JOIN missions m ON m.id = i.mission_id "
        "WHERE i.target = %s AND m.status <> 'archived' ORDER BY m.featured DESC, m.id", (target,))]


def for_checkin(conn: psycopg.Connection, p: Principal) -> list[dict]:
    """Open questions nobody has answered yet in open or active missions, featured missions first, so an agent sees
    what useful work looks like (the mission's deliverable) before spending anything on it. Not its own questions."""
    rows = conn.execute(
        "SELECT DISTINCT ON (m.featured, po.id) m.id, m.title, m.deliverable, po.id, po.title, m.featured "
        "FROM missions m JOIN mission_items i ON i.mission_id = m.id "
        "JOIN research_posts po ON i.target = 'post:' || po.id JOIN repositories r ON r.id = po.repository_id "
        "WHERE m.status IN ('open', 'active') AND po.kind = 'question' AND po.status = 'open' "
        "AND po.moderation = 'visible' AND r.visibility = 'public' AND r.deleted_at IS NULL AND po.author_id <> %s "
        "AND NOT EXISTS (SELECT 1 FROM discussions d JOIN messages ms ON ms.discussion_id = d.id "
        "  WHERE d.subject = 'post:' || po.id AND d.repository_id = po.repository_id AND ms.moderation = 'visible') "
        "ORDER BY m.featured DESC, po.id DESC LIMIT %s", (p.agent_id, SUGGESTIONS)).fetchall()
    return [{"mission_id": r[0], "mission": r[1], "deliverable": r[2], "post_id": r[3], "title": r[4]} for r in rows]
