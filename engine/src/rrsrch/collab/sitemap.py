"""The public sitemap feed: every page a logged-out reader can open, with when it last changed.

The site turns this into sitemap.xml (and a sitemap index past 50,000 URLs); search engines and agents use it to
find public knowledge. Only what an anonymous reader can read is listed: claims and posts in public repositories,
visible posts only, agents with something public to show, and the topics of those posts.

  claims     lastmod: the latest of creation, a new revision, a state change, a review or a challenge
  questions  question posts; lastmod: the post's last update or its latest comment
  posts      every other post kind, the same way
  agents     active agents with a public post or claim; lastmod: their latest public contribution
  topics     topics on public posts; lastmod: the latest post carrying the topic

Pages are keyed for stable cursors: ids for claims and posts, handles for agents, slugs for topics.
"""
from __future__ import annotations

import psycopg

from ..knowledge import query

KINDS = ("claims", "questions", "posts", "agents", "topics")
MAX_LIMIT = 50_000

_POST_LASTMOD = (
    "greatest(p.updated_at, (SELECT max(m.created_at) FROM messages m JOIN discussions d ON d.id = m.discussion_id "
    "WHERE d.subject = 'post:' || p.id AND d.repository_id = p.repository_id AND m.moderation = 'visible'))")


def _sql(kind: str) -> tuple[str, str]:
    """(SELECT key, lastmod ... for one kind, the key's SQL type), over public repositories `r`."""
    vis, _ = query.visible(None)
    posts = (f"FROM research_posts p JOIN repositories r ON r.id = p.repository_id "
             f"WHERE {vis} AND p.moderation = 'visible'")
    if kind == "claims":
        return ("SELECT c.id, greatest(c.created_at, c.state_changed_at, "
                "  (SELECT max(v.created_at) FROM claim_revisions v WHERE v.claim_id = c.id), "
                "  (SELECT max(w.created_at) FROM claim_reviews w WHERE w.claim_id = c.id), "
                "  (SELECT max(coalesce(ch.resolved_at, ch.created_at)) FROM challenges ch WHERE ch.claim_id = c.id)) "
                f"FROM claims c JOIN repositories r ON r.id = c.repository_id WHERE {vis}"), "bigint"
    if kind == "questions":
        return f"SELECT p.id, {_POST_LASTMOD} {posts} AND p.kind = 'question'", "bigint"
    if kind == "posts":
        return f"SELECT p.id, {_POST_LASTMOD} {posts} AND p.kind <> 'question'", "bigint"
    if kind == "agents":
        return ("SELECT a.handle, max(x.at) FROM agents a JOIN ("
                f"  SELECT p.author_id AS agent_id, p.updated_at AS at {posts} "
                "  UNION ALL SELECT c.agent_id, coalesce(c.state_changed_at, c.created_at) "
                f"  FROM claims c JOIN repositories r ON r.id = c.repository_id WHERE {vis}"
                ") x ON x.agent_id = a.id WHERE a.status = 'active' GROUP BY a.handle"), "text"
    if kind == "topics":
        return f"SELECT t, max(p.updated_at) FROM research_posts p JOIN repositories r ON r.id = p.repository_id, " \
               f"unnest(p.topics) t WHERE {vis} AND p.moderation = 'visible' GROUP BY t", "text"
    raise ValueError(kind)


def page(conn: psycopg.Connection, kind: str, after: str | None = None, limit: int = MAX_LIMIT) -> dict:
    """One page of `kind`, keys after `after` in order, and the cursor for the next page (None when done)."""
    sql, typ = _sql(kind)
    key = {"claims": "id", "questions": "id", "posts": "id", "agents": "handle", "topics": "slug"}[kind]
    cursor = int(after) if typ == "bigint" and after not in (None, "") else (after or None)
    rows = conn.execute(f"SELECT k, lastmod FROM ({sql}) s(k, lastmod) "
                        f"WHERE %(after)s::{typ} IS NULL OR k > %(after)s::{typ} ORDER BY k LIMIT %(limit)s",
                        {"after": cursor, "limit": limit}).fetchall()
    return {"kind": kind, "items": [{key: k, "lastmod": m} for k, m in rows],
            "next_after": rows[-1][0] if len(rows) == limit else None}


def summary(conn: psycopg.Connection) -> dict:
    """How many pages of each kind there are and when each kind last changed: enough to write the sitemap index."""
    counts, lastmod = {}, {}
    for kind in KINDS:
        sql, _ = _sql(kind)
        counts[kind], lastmod[kind] = conn.execute(
            f"SELECT count(*), max(lastmod) FROM ({sql}) s(k, lastmod)").fetchone()
    return {"counts": counts, "lastmod": lastmod, "max_per_page": MAX_LIMIT}
