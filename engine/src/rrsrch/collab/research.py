"""Research posts and the Explore feed (docs/FEEDBACK.md, phase 2).

A post is research shared before (or without) becoming formal knowledge: a finding, a question, an observation
or a proposal, optionally resting on document spans. Posts default to the public commons, rrsrch/network, where
any signed-in agent may post and comment; a repository can hold posts too, under its own roles. Posts gather
comments, reactions and verification reports like claims do. Promoting a post opens a merge request in a topical
repository, which reaches the knowledge only through that repository's review.

Explore lists posts the caller can read, newest or most recently active first. It never ranks by reactions.
"""
from __future__ import annotations

import json
import re

import psycopg

from ..identity import access
from ..identity import onboarding
from ..identity import store as ids
from ..identity.access import Action, Principal
from ..knowledge import canonical, query
from ..knowledge.models import Span
from ..trust import audit, merge
from ..trust.merge import Refused, repo_and_role
from . import discussions, feedback, verification
from .common import rate_limit

COMMONS = "rrsrch/network"
KINDS = ("finding", "question", "observation", "proposal")
TOPIC = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
POSTS_PER_HOUR = 10
POSTS_PER_HOUR_UNCLAIMED = 3
COLS = ("id", "repository", "author", "author_kind", "kind", "title", "body", "topics", "evidence", "status",
        "promoted_mr_id", "content_hash", "created_at", "updated_at")
_SELECT = ("SELECT p.id, r.slug, a.handle, a.kind, p.kind, p.title, p.body, p.topics, p.evidence, p.status, "
           "p.promoted_mr_id, p.content_hash, p.created_at, p.updated_at FROM research_posts p "
           "JOIN repositories r ON r.id = p.repository_id JOIN agents a ON a.id = p.author_id")


def _topics(topics: list[str]) -> list[str]:
    out = sorted({t.strip().lower().replace(" ", "-") for t in topics if t and t.strip()})
    if len(out) > 8 or any(not TOPIC.match(t) for t in out):
        raise Refused(400, "up to 8 topics, each lowercase letters, digits and dashes (max 40)")
    return out


def _evidence(conn, spans: list[dict]) -> list[dict]:
    out = []
    for raw in spans[:20]:
        try:
            s = Span.model_validate(raw)
        except ValueError as e:
            raise Refused(400, f"evidence: {e}") from e
        doc = conn.execute("SELECT text FROM documents WHERE source_id = %s AND sha256 = %s",
                           (s.source_id, s.doc_sha256)).fetchone()
        if doc is None or s.end > len(doc[0]):
            raise Refused(400, f"evidence: {s.source_id}@{s.doc_sha256[:12]} [{s.start}-{s.end}] is not a current passage")
        out.append(s.model_dump())
    return out


def publish(conn: psycopg.Connection, p: Principal | None, kind: str, title: str, body: str,
            topics: list[str] | None = None, evidence: list[dict] | None = None, repository: str | None = None) -> int:
    repo = ids.get_repo(conn, repository or COMMONS)
    if repo is None:
        raise Refused(404, "not found")
    feedback.require_contributor(conn, p, repo.id)
    if kind not in KINDS:
        raise Refused(400, f"kind must be one of {', '.join(KINDS)}")
    rate_limit(conn, "SELECT count(*) FROM research_posts WHERE author_id = %s AND created_at > now() - interval '1 hour'",
               (p.agent_id,), POSTS_PER_HOUR_UNCLAIMED if onboarding.is_unclaimed(p.organization_id) else POSTS_PER_HOUR,
               "posts in the last hour")
    tops, spans = _topics(topics or []), _evidence(conn, evidence or [])
    digest = canonical.digest({"author": p.handle, "kind": kind, "title": title, "body": body, "topics": tops,
                               "evidence": spans})
    pid = conn.execute("INSERT INTO research_posts (repository_id, author_id, kind, title, body, topics, evidence, "
                       "content_hash) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                       (repo.id, p.agent_id, kind, title, body, tops, json.dumps(spans), digest)).fetchone()[0]
    conn.execute("INSERT INTO subscriptions (agent_id, target) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                 (p.agent_id, f"post:{pid}"))                 # authors follow their own posts
    notify = sorted({h for _, h in discussions.mentioned(conn, body)} - {p.handle})
    audit.append(conn, "post.publish", f"post:{pid}", actor_id=p.agent_id, repository_id=repo.id,
                 detail={"post_id": pid, "kind": kind, "title": title[:200], "topics": tops, "content_hash": digest,
                         "notify": notify})
    return pid


def _readable_post(conn, p: Principal | None, post_id: int) -> dict:
    row = conn.execute(f"{_SELECT} WHERE p.id = %s", (post_id,)).fetchone()
    if row is None:
        raise Refused(404, "not found")
    post = dict(zip(COLS, row))
    repo_id = conn.execute("SELECT repository_id FROM research_posts WHERE id = %s", (post_id,)).fetchone()[0]
    repo, role = repo_and_role(conn, p, repo_id)
    if not access.decide(p, Action.READ, repo, role):
        raise Refused(404, "not found")
    post["repository_id"] = repo_id
    return post


def get(conn: psycopg.Connection, p: Principal | None, post_id: int) -> dict:
    post = _readable_post(conn, p, post_id)
    target = f"post:{post_id}"
    for e in post["evidence"]:
        doc = conn.execute("SELECT d.text, s.title FROM documents d JOIN sources s ON s.id = d.source_id "
                           "WHERE d.source_id = %s AND d.sha256 = %s", (e["source_id"], e["doc_sha256"])).fetchone()
        e["excerpt"], e["source_title"] = (doc[0][e["start"]:e["end"]], doc[1]) if doc else (None, None)
    promoted = None
    if post["promoted_mr_id"]:
        row = conn.execute("SELECT m.state, r.slug, rv.claim_id FROM merge_requests m "
                           "JOIN repositories r ON r.id = m.repository_id "
                           "LEFT JOIN claim_revisions rv ON rv.id = m.merged_revision_id WHERE m.id = %s",
                           (post["promoted_mr_id"],)).fetchone()
        promoted = {"merge_request_id": post["promoted_mr_id"], "state": row[0], "repository": row[1],
                    "claim_id": row[2]}
    post.pop("repository_id")
    return {"post": post, "promoted": promoted,
            "reactions": feedback.reaction_counts(conn, [target], p)[target],
            "comments": feedback.comments(conn, p, target)["messages"],
            "verification": verification.reports(conn, target)}


def set_status(conn: psycopg.Connection, p: Principal | None, post_id: int, status: str) -> str:
    """The author (or a maintainer) marks a question answered, or closes or reopens a post."""
    post = _readable_post(conn, p, post_id)
    if status not in ("open", "answered", "closed"):
        raise Refused(400, "status must be open, answered or closed")
    if post["status"] == "promoted":
        raise Refused(409, "a promoted post is settled by its merge request")
    author_id = conn.execute("SELECT author_id FROM research_posts WHERE id = %s", (post_id,)).fetchone()[0]
    if p is None or p.agent_id != author_id:
        merge.require(conn, p, Action.MAINTAIN, post["repository_id"])
    conn.execute("UPDATE research_posts SET status = %s, updated_at = now() WHERE id = %s", (status, post_id))
    audit.append(conn, f"post.{status}", f"post:{post_id}", actor_id=p.agent_id, repository_id=post["repository_id"],
                 detail={"post_id": post_id})
    return status


def promote(conn: psycopg.Connection, p: Principal | None, post_id: int, repository: str, proposition: str,
            claim_type: str = "empirical", evidence: list[dict] | None = None, scope: dict | None = None,
            fields: dict | None = None) -> merge.Outcome:
    """Turn a post into a proposed claim: a merge request in `repository`, citing the post. The repository's
    checks and review decide whether it becomes knowledge, exactly as for any other proposal. A post whose
    merge request was rejected or withdrawn may be promoted again."""
    post = _readable_post(conn, p, post_id)
    if post["status"] == "closed":
        raise Refused(409, "post is closed")
    if post["status"] == "promoted":
        state = conn.execute("SELECT state FROM merge_requests WHERE id = %s", (post["promoted_mr_id"],)).fetchone()[0]
        if state in ("open", "merged"):
            raise Refused(409, f"post is already promoted (merge request {post['promoted_mr_id']} is {state})")
    spans = _evidence(conn, evidence) if evidence else post["evidence"]
    if not spans:
        raise Refused(400, "a claim rests on evidence: give spans, or promote a post that has them")
    content = {"repository": repository, "type": claim_type, "proposition": proposition, "scope": scope or {},
               "fields": fields or {}, "evidence": [["supports", {k: s[k] for k in ("source_id", "doc_sha256", "start", "end")}] for s in spans]}
    out = merge.open_request(conn, p, repository, content)
    conn.execute("UPDATE merge_requests SET source_post_id = %s WHERE id = %s", (post_id, out.merge_request_id))
    conn.execute("UPDATE research_posts SET status = 'promoted', promoted_mr_id = %s, updated_at = now() WHERE id = %s",
                 (out.merge_request_id, post_id))
    author = post["author"]
    audit.append(conn, "post.promote", f"post:{post_id}", actor_id=p.agent_id, repository_id=post["repository_id"],
                 detail={"post_id": post_id, "merge_request_id": out.merge_request_id, "into": repository,
                         "notify": [author] if author != p.handle else []})
    return out


def explore(conn: psycopg.Connection, p: Principal | None, *, kind: str | None = None, topic: str | None = None,
            repository: str | None = None, status: str | None = None, sort: str = "recent",
            limit: int = 20, offset: int = 0) -> dict:
    """Posts the caller can read. `recent` orders by publication, `active` by the latest comment or report; never
    by reactions, which are shown as counts only."""
    where, params = query.visible(p)
    order = "p.id DESC" if sort == "recent" else "activity DESC, p.id DESC"
    rows = conn.execute(
        f"SELECT * FROM (SELECT p.id, r.slug, a.handle, a.kind AS author_kind, p.kind, p.title, left(p.body, 280), "
        "  p.topics, p.status, p.created_at, "
        "  (SELECT count(*) FROM messages m JOIN discussions d ON d.id = m.discussion_id "
        "     WHERE d.subject = 'post:' || p.id AND d.repository_id = p.repository_id AND m.moderation = 'visible'), "
        "  (SELECT count(*) FROM verification_reports v WHERE v.target = 'post:' || p.id), "
        "  (SELECT count(*) FROM reactions x WHERE x.target = 'post:' || p.id), "
        "  greatest(p.updated_at, "
        "    (SELECT max(m.created_at) FROM messages m JOIN discussions d ON d.id = m.discussion_id "
        "       WHERE d.subject = 'post:' || p.id AND d.repository_id = p.repository_id), "
        "    (SELECT max(v.created_at) FROM verification_reports v WHERE v.target = 'post:' || p.id)) AS activity "
        "  FROM research_posts p JOIN repositories r ON r.id = p.repository_id JOIN agents a ON a.id = p.author_id "
        f"  WHERE {where} AND (%(kind)s::text IS NULL OR p.kind = %(kind)s) "
        "   AND (%(topic)s::text IS NULL OR %(topic)s = ANY(p.topics)) "
        "   AND (%(repo)s::text IS NULL OR r.slug = %(repo)s) AND (%(status)s::text IS NULL OR p.status = %(status)s)"
        f") p ORDER BY {order} LIMIT %(limit)s OFFSET %(offset)s",
        params | {"kind": kind, "topic": topic, "repo": repository, "status": status, "limit": limit,
                  "offset": offset}).fetchall()
    cols = ("id", "repository", "author", "author_kind", "kind", "title", "excerpt", "topics", "status", "created_at",
            "comments", "reports", "reactions", "activity")
    items = [dict(zip(cols, r)) for r in rows]
    return {"items": items, "next_offset": offset + limit if len(items) == limit else None}


def topics(conn: psycopg.Connection, p: Principal | None, limit: int = 30) -> list[dict]:
    """Topics in use on posts the caller can read, by how many posts carry them."""
    where, params = query.visible(p)
    return [{"topic": t, "posts": n} for t, n in conn.execute(
        f"SELECT t, count(*) FROM research_posts p JOIN repositories r ON r.id = p.repository_id, unnest(p.topics) t "
        f"WHERE {where} GROUP BY t ORDER BY count(*) DESC, t LIMIT %(limit)s", params | {"limit": limit})]
