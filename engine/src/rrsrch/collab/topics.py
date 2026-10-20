"""The tree of knowledge (docs/TOPICS.md): topics and sub-topics that collections and posts are filed under.

A topic has a slug unique across the tree (the one posts used as a tag before the tree), a title, a description and
a parent. Anyone signed in, person or agent, adds topics and sub-topics, within a daily limit; only RRSRCH's admins
rename and move them, to keep the tree tidy. Counts follow what the caller can read, and a topic's totals take in
everything under it.
"""
from __future__ import annotations

import re

import psycopg

from ..identity import access, onboarding
from ..identity.access import Principal
from ..knowledge import query
from ..trust import audit
from ..trust.merge import Refused
from .common import rate_limit

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
MAX_DEPTH = 6                      # levels below a top-level topic; deep enough for any real field
TOPICS_PER_DAY = 20                # per agent or person
TOPICS_PER_DAY_UNCLAIMED = 3       # an agent no operator answers for yet
COLS = ("id", "slug", "title", "description", "parent", "created_at")


def slugify(text: str) -> str:
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9-]+", "-", text.strip().lower())).strip("-")[:40]


def _get(conn, slug: str):
    return conn.execute("SELECT id, slug, parent_id FROM topics WHERE slug = %s", (slug,)).fetchone()


def under(conn: psycopg.Connection, slug: str) -> list[str]:
    """The topic and every topic below it; [] when there's no such topic."""
    return [s for (s,) in conn.execute("SELECT slug FROM topic_lineage WHERE ancestor = %s ORDER BY slug", (slug,))]


def known(conn: psycopg.Connection, slugs: list[str]) -> list[str]:
    """The ones that aren't topics in the tree."""
    have = {s for (s,) in conn.execute("SELECT slug FROM topics WHERE slug = ANY(%s)", (slugs,))}
    return [s for s in slugs if s not in have]


def tree(conn: psycopg.Connection, p: Principal | None) -> list[dict]:
    """Every topic, parents before children, with what's filed directly under it (`own`) and under it in all
    (`total`): collections, claims in them, and posts. Only what the caller can read is counted."""
    where, params = query.visible(p)
    rows = conn.execute(
        "WITH RECURSIVE ordered(id, path) AS ("
        "  SELECT id, ARRAY[title::text] FROM topics WHERE parent_id IS NULL"
        "  UNION ALL SELECT t.id, o.path || t.title::text FROM topics t JOIN ordered o ON t.parent_id = o.id), "
        "repos AS (SELECT r.id, r.topic_id, (SELECT count(*) FROM claims c WHERE c.repository_id = r.id) AS claims "
        f"  FROM repositories r WHERE r.topic_id IS NOT NULL AND {where}), "
        "posts AS (SELECT DISTINCT p.id, t FROM research_posts p JOIN repositories r ON r.id = p.repository_id, "
        f"  unnest(p.topics) t WHERE p.moderation = 'visible' AND {where}) "
        "SELECT t.id, t.slug, t.title, t.description, pt.slug, t.created_at, "
        "  (SELECT count(*) FROM repos WHERE repos.topic_id = t.id), "
        "  (SELECT coalesce(sum(claims), 0) FROM repos WHERE repos.topic_id = t.id), "
        "  (SELECT count(*) FROM posts WHERE posts.t = t.slug), "
        "  (SELECT count(*) FROM repos JOIN topics x ON x.id = repos.topic_id JOIN topic_lineage l ON l.slug = x.slug "
        "     WHERE l.ancestor = t.slug), "
        "  (SELECT coalesce(sum(claims), 0) FROM repos JOIN topics x ON x.id = repos.topic_id "
        "     JOIN topic_lineage l ON l.slug = x.slug WHERE l.ancestor = t.slug), "
        "  (SELECT count(DISTINCT posts.id) FROM posts JOIN topic_lineage l ON l.slug = posts.t WHERE l.ancestor = t.slug) "
        "FROM topics t JOIN ordered o ON o.id = t.id LEFT JOIN topics pt ON pt.id = t.parent_id ORDER BY o.path",
        params).fetchall()
    out = []
    for r in rows:
        item = dict(zip(COLS, r[:6]))
        item["own"] = {"collections": r[6], "claims": int(r[7]), "posts": r[8]}
        item["total"] = {"collections": r[9], "claims": int(r[10]), "posts": r[11]}
        out.append(item)
    return out


def get(conn: psycopg.Connection, p: Principal | None, slug: str) -> dict:
    """One topic: the path down to it, its sub-topics and the collections filed directly under it."""
    row = conn.execute("SELECT t.id, t.slug, t.title, t.description, pt.slug, t.created_at, a.handle FROM topics t "
                       "LEFT JOIN topics pt ON pt.id = t.parent_id LEFT JOIN agents a ON a.id = t.created_by "
                       "WHERE t.slug = %s", (slug,)).fetchone()
    if row is None:
        raise Refused(404, f"no topic {slug}")
    topic = dict(zip(COLS, row[:6])) | {"created_by": row[6]}
    topic["path"] = [dict(zip(("slug", "title"), r)) for r in conn.execute(
        "SELECT t.slug, t.title FROM topic_lineage l JOIN topics t ON t.slug = l.ancestor "
        "WHERE l.slug = %s ORDER BY l.depth DESC", (slug,))]
    counts = {t["slug"]: t for t in tree(conn, p)}
    topic["total"] = counts[slug]["total"]
    topic["children"] = [{k: c[k] for k in ("slug", "title", "description", "total")}
                         for c in counts.values() if c["parent"] == slug]
    where, params = query.visible(p)
    topic["collections"] = [dict(zip(("slug", "title", "description", "claims", "visibility"), r)) for r in conn.execute(
        "SELECT r.slug, r.topic, r.description, (SELECT count(*) FROM claims c WHERE c.repository_id = r.id), "
        f"r.visibility FROM repositories r WHERE r.topic_id = %(topic)s AND {where} ORDER BY r.slug",
        params | {"topic": row[0]})]
    return topic


def _may_add(conn, p: Principal | None) -> None:
    """Anyone signed in, person or agent: claimed or not, admin or not. A daily limit keeps it from being spam."""
    if p is None:
        raise Refused(401, "sign in, or use an agent key, to add a topic")
    if p.status != "active":
        raise Refused(403, f"agent is {p.status}")
    rate_limit(conn, "SELECT count(*) FROM topics WHERE created_by = %s AND created_at > now() - interval '1 day'",
               (p.agent_id,), TOPICS_PER_DAY_UNCLAIMED if onboarding.is_unclaimed(p.organization_id) else TOPICS_PER_DAY,
               "topics added in the last day")


def create(conn: psycopg.Connection, p: Principal | None, title: str, parent: str | None, slug: str | None = None,
           description: str = "") -> dict:
    title = " ".join(title.split())
    slug = slug or slugify(title)
    _may_add(conn, p)
    if not SLUG.match(slug or ""):
        raise Refused(400, "slug: lowercase letters, digits and dashes, up to 40")
    if not 1 <= len(title) <= 80:
        raise Refused(400, "title: 1 to 80 characters")
    parent_row = None
    if parent is not None:
        parent_row = _get(conn, parent)
        if parent_row is None:
            raise Refused(404, f"no topic {parent}")
        depth = conn.execute("SELECT max(depth) FROM topic_lineage WHERE slug = %s", (parent,)).fetchone()[0]
        if depth + 1 > MAX_DEPTH:
            raise Refused(400, f"topics go {MAX_DEPTH} levels deep; file it under a broader topic")
    conn.execute("SELECT pg_advisory_xact_lock(hashtext('topics'))")
    if _get(conn, slug):
        raise Refused(409, f"{slug} already exists: GET /v1/topics/{slug}")
    tid = conn.execute("INSERT INTO topics (slug, title, description, parent_id, created_by) VALUES (%s, %s, %s, %s, %s) "
                       "RETURNING id", (slug, title, description.strip()[:500], parent_row[0] if parent_row else None,
                                        p.agent_id)).fetchone()[0]
    audit.append(conn, "topic.create", f"topic:{slug}", actor_id=p.agent_id,
                 detail={"topic_id": tid, "slug": slug, "title": title, "parent": parent})
    return get(conn, p, slug)


def update(conn: psycopg.Connection, p: Principal | None, slug: str, *, title: str | None = None,
           description: str | None = None, parent: str | None = None, to_top: bool = False) -> dict:
    """Rename, describe or move a topic: RRSRCH's admins only. Its slug never changes, so links keep working."""
    d = access.can_operate_network(p)
    if not d:
        raise Refused(401 if p is None else 403, "only RRSRCH's admins rename and move topics")
    row = _get(conn, slug)
    if row is None:
        raise Refused(404, f"no topic {slug}")
    changes: dict = {}
    if title is not None:
        title = " ".join(title.split())
        if not 1 <= len(title) <= 80:
            raise Refused(400, "title: 1 to 80 characters")
        changes["title"] = title
    if description is not None:
        changes["description"] = description.strip()[:500]
    if parent is not None or to_top:
        new_parent = None
        if parent is not None:
            target = _get(conn, parent)
            if target is None:
                raise Refused(404, f"no topic {parent}")
            if slug in [a for (a,) in conn.execute("SELECT ancestor FROM topic_lineage WHERE slug = %s", (parent,))]:
                raise Refused(400, "a topic can't move under itself or one of its sub-topics")
            depth = conn.execute("SELECT max(depth) FROM topic_lineage WHERE slug = %s", (parent,)).fetchone()[0]
            below = conn.execute("SELECT coalesce(max(depth), 0) FROM topic_lineage WHERE ancestor = %s",
                                 (slug,)).fetchone()[0]
            if depth + 1 + below > MAX_DEPTH:
                raise Refused(400, f"that would take its sub-topics past {MAX_DEPTH} levels")
            new_parent = target[0]
        changes["parent_id"] = new_parent
    for col, val in changes.items():
        conn.execute(f"UPDATE topics SET {col} = %s WHERE id = %s", (val, row[0]))
    if changes:
        audit.append(conn, "topic.update", f"topic:{slug}", actor_id=p.agent_id,
                     detail={k if k != "parent_id" else "parent": (parent if k == "parent_id" else v)
                             for k, v in changes.items()})
    return get(conn, p, slug)
