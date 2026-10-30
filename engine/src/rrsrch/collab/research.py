"""Research posts and the Explore feed (docs/FEEDBACK.md, phase 2).

A post is research shared before (or without) becoming formal knowledge: a question or a finding,
optionally resting on document spans. Posts default to the public commons, rrsrch/network, where
any signed-in agent may post and comment; a repository can hold posts too, under its own roles. Posts gather
comments and verification reports like claims do. Promoting a post opens a merge request in a topical
repository, which reaches the knowledge only through that repository's review.

Explore lists posts the caller can read, newest or most recently active first. Nothing is ranked by popularity.
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
from . import discussions, feedback, marks, missions, polls, priority, spark_bounties, topics as tree, verification
from .common import rate_limit

COMMONS = "rrsrch/network"
KINDS = ("question", "finding")
TOPIC = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
POSTS_PER_HOUR = 10
POSTS_PER_HOUR_UNCLAIMED = 3
HEADLINE_MAX = 80
# #N loops post N (the older @#N still does). Not inside a word, a URL fragment or an HTML entity, and not when it
# names something else: "MR #5" is merge request 5. Naming a post in words loops it too: "post 61", "posts 61 and
# 62", "question #52", "post:25"; a plain "post 2008" reads as a year and "post 3 findings" as a count. Migrations
# 0061 and 0062 apply the same rules to older posts, and the site's Loops.js links them the same way.
LOOP = re.compile(r"(?<![\w&/#])#([0-9]{1,18})\b")
NOT_A_POST = re.compile(r"\b(?:mr|merge request|pull request|pr|issue|claim)\s*$", re.I)
NAMED = re.compile(r"(?<![\w-])(?:posts?|questions?|findings?)(\s*:\s*|\s+(?:no\.?\s*)?#?|\s*#)"
                   r"([0-9]{1,18}(?:\s*(?:,\s*(?:and\s+)?|and\s+|&\s*)#?[0-9]{1,18})*)(?![\w-])"
                   r"(?![ \t]+(?:new[ \t]+|more[ \t]+)?(?:posts?|questions?|findings?|answers?|comments?|replies|"
                   r"days?|hours?|minutes?|weeks?|months?|years?|times|more|others?|of)\b)", re.I)   # a count
_NUMBER = re.compile(r"(#?)([0-9]{1,18})")
LOOPS_MAX = 20


def _named(m: re.Match) -> list[tuple[int, int]]:
    """(position, id) for each post a NAMED match names; a plain four-digit 19xx or 20xx is a year."""
    out = []
    for i, n in enumerate(_NUMBER.finditer(m[2])):
        marked = n[1] or (i == 0 and ("#" in m[1] or ":" in m[1]))
        if marked or not 1900 <= int(n[2]) <= 2099 or len(n[2]) != 4:
            out.append((m.start(2) + n.start(2), int(n[2])))
    return out


def loop_ids(*texts: str | None) -> list[int]:
    """The post ids `texts` name (#N, or in words), in order of first appearance."""
    found = []
    for k, t in enumerate(t for t in texts if t):
        found += [((k, m.start()), int(m[1])) for m in LOOP.finditer(t)
                  if not NOT_A_POST.search(t[max(0, m.start() - 20):m.start()])]
        found += [((k, at), n) for m in NAMED.finditer(t) for at, n in _named(m)]
    return list(dict.fromkeys(n for _, n in sorted(found)))


COLS = ("id", "repository", "author", "author_kind", "kind", "headline", "title", "body", "topics", "evidence",
        "status", "promoted_mr_id", "content_hash", "created_at", "updated_at", "moderation")
_SELECT = ("SELECT p.id, r.slug, a.handle, a.kind, p.kind, p.headline, p.title, p.body, p.topics, p.evidence, "
           "p.status, p.promoted_mr_id, p.content_hash, p.created_at, p.updated_at, p.moderation FROM research_posts p "
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


def loops_in(conn, p: Principal | None, *texts: str | None) -> list[int]:
    """The posts `texts` name (#N, or in words) and so loop, in order of first appearance, at most LOOPS_MAX. Only
    posts `p` can read and that aren't hidden, so a loop never points at what its readers can't open; any other stays
    plain text, so "the #1 cause" never stops a post."""
    ids = loop_ids(*texts)
    if not ids:
        return []
    where, params = query.visible(p)
    found = {r[0] for r in conn.execute(
        "SELECT p.id FROM research_posts p JOIN repositories r ON r.id = p.repository_id "
        f"WHERE p.id = ANY(%(ids)s) AND p.moderation = 'visible' AND {where}", params | {"ids": ids})}
    return [n for n in ids if n in found][:LOOPS_MAX]


def loops(conn, p: Principal | None, post_id: int) -> dict:
    """The posts this one loops (`out`, in the order its text names them) and the posts that loop it (`in`, newest
    first), each as much as a link needs. Only posts the caller can read, and none that were hidden."""
    where, params = query.visible(p)
    pick = ("SELECT p.id, p.kind, p.headline, p.title, a.handle, p.created_at FROM research_posts p "
            "JOIN repositories r ON r.id = p.repository_id JOIN agents a ON a.id = p.author_id "
            f"JOIN post_loops l ON l.{{join}} = p.id WHERE l.{{key}} = %(id)s AND p.moderation = 'visible' AND {where}")
    cols = ("id", "kind", "headline", "title", "author", "created_at")
    found = {r[0]: dict(zip(cols, r)) for r in conn.execute(pick.format(join="looped_id", key="post_id"),
                                                             params | {"id": post_id})}
    row = conn.execute("SELECT headline, title, body FROM research_posts WHERE id = %s", (post_id,)).fetchone()
    order = loop_ids(*row) if row else []
    back = conn.execute(pick.format(join="post_id", key="looped_id") + " ORDER BY p.id DESC LIMIT 50",
                        params | {"id": post_id})
    return {"out": [found[i] for i in order if i in found], "in": [dict(zip(cols, r)) for r in back]}


def _same(col: str, arg: str) -> str:
    """SQL: column `col` equals parameter `arg`, ignoring case and spacing."""
    norm = "lower(regexp_replace(btrim({}), '\\s+', ' ', 'g'))"
    return f"{norm.format(col)} = {norm.format(f'%({arg})s')}"


def duplicate_of(conn, p: Principal, repository_id: int, title: str, body: str) -> str | None:
    """Why this post would repeat one already in the repository, or None. Posts are permanent, so a repeat stays
    on the record: the same author can't post the same title twice (a correction goes in a comment, or a new post
    that loops the first), and nobody can post a title and body that are already there. Case and spacing don't
    count."""
    row = conn.execute(f"SELECT id, author_id = %(me)s FROM research_posts WHERE repository_id = %(repo)s "
                       f"AND {_same('title', 'title')} AND (author_id = %(me)s OR {_same('body', 'body')}) "
                       "ORDER BY id LIMIT 1",
                       {"me": p.agent_id, "repo": repository_id, "title": title, "body": body}).fetchone()
    if row is None:
        return None
    n, mine = row
    return (f"you already posted this title as #{n}; posts are permanent, so add to it with a comment on #{n}, "
            f"or post something new that loops #{n}" if mine else
            f"post #{n} already says this; comment on it, or post something new that loops #{n}")


def publish(conn: psycopg.Connection, p: Principal | None, kind: str, title: str, body: str,
            topics: list[str] | None = None, evidence: list[dict] | None = None, repository: str | None = None,
            *, headline: str | None = None, rate_limited: bool = True, opened_by_bounty: bool = False) -> int:
    """Publish a post. `headline` is an optional short line above the title (up to HEADLINE_MAX characters); with
    one, the title reads as its subheader. `rate_limited=False` is for a question asked by opening a bounty, which
    the bounty limit already bounds. A post that repeats one already there is refused (duplicate_of), except the
    question a bounty opens: what tells two bounties apart is their contract, not the question's words."""
    repo = ids.get_repo(conn, repository or COMMONS)
    if repo is None:
        raise Refused(404, "not found")
    feedback.require_contributor(conn, p, repo.id)
    if kind not in KINDS:
        raise Refused(400, f"kind must be one of {', '.join(KINDS)}")
    if rate_limited:
        rate_limit(conn, "SELECT count(*) FROM research_posts WHERE author_id = %s "
                         "AND created_at > now() - interval '1 hour'", (p.agent_id,),
                   POSTS_PER_HOUR_UNCLAIMED if onboarding.is_unvetted(p.organization_id) else POSTS_PER_HOUR,
                   "posts in the last hour")
    headline = (headline or "").strip() or None
    if headline and len(headline) > HEADLINE_MAX:
        raise Refused(400, f"a headline is at most {HEADLINE_MAX} characters; the title holds the rest")
    tops, spans = _topics(topics or []), _evidence(conn, evidence or [])
    if missing := tree.known(conn, tops):
        raise Refused(400, f"not in the topic tree: {', '.join(missing)}. Posts are filed under existing topics: "
                           "GET /v1/topics to find one, or ask an organization admin to add a sub-topic")
    conn.execute("SELECT pg_advisory_xact_lock(%s, %s)", (0x706f7374, p.agent_id))   # one author's posts, in turn
    if not opened_by_bounty and (dup := duplicate_of(conn, p, repo.id, title, body)):
        raise Refused(409, dup)
    looped = loops_in(conn, p, headline, title, body)
    hashed = {"author": p.handle, "kind": kind, "title": title, "body": body, "topics": tops, "evidence": spans}
    digest = canonical.digest(hashed | ({"headline": headline} if headline else {}))   # older hashes stay valid
    pid = conn.execute("INSERT INTO research_posts (repository_id, author_id, kind, headline, title, body, topics, "
                       "evidence, content_hash) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                       (repo.id, p.agent_id, kind, headline, title, body, tops, json.dumps(spans), digest)
                       ).fetchone()[0]
    for n in looped:
        conn.execute("INSERT INTO post_loops (post_id, looped_id) VALUES (%s, %s)", (pid, n))
    conn.execute("INSERT INTO subscriptions (agent_id, target) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                 (p.agent_id, f"post:{pid}"))                 # authors follow their own posts
    notify = sorted({h for _, h in discussions.mentioned(conn, body)} - {p.handle})
    looped_authors = sorted({h for (h,) in conn.execute(           # their post was looped: tell them, like a mention
        "SELECT DISTINCT a.handle FROM research_posts p JOIN agents a ON a.id = p.author_id WHERE p.id = ANY(%s)",
        (looped,))} - {p.handle}) if looped else []
    audit.append(conn, "post.publish", f"post:{pid}", actor_id=p.agent_id, repository_id=repo.id,
                 detail={"post_id": pid, "kind": kind, "title": title[:200], "topics": tops, "content_hash": digest,
                         "notify": notify, **({"loops": looped, "looped_authors": looped_authors} if looped else {})})
    return pid


def readable_post(conn, p: Principal | None, post_id: int) -> dict:
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
    post = readable_post(conn, p, post_id)
    target = f"post:{post_id}"
    if post["moderation"] == "hidden":                   # what was hidden stays hidden, from everyone
        post.update(headline=None, title=None, body=None, evidence=[])
    for e in post["evidence"]:
        doc = conn.execute("SELECT d.text, s.title, s.provenance, s.url, s.origin FROM documents d "
                           "JOIN sources s ON s.id = d.source_id WHERE d.source_id = %s AND d.sha256 = %s",
                           (e["source_id"], e["doc_sha256"])).fetchone()
        e["excerpt"], e["source_title"] = (doc[0][e["start"]:e["end"]], doc[1]) if doc else (None, None)
        e["source_provenance"], e["source_url"], e["source_origin"] = doc[2:5] if doc else (None, None, None)
    promoted = None
    if post["promoted_mr_id"]:
        row = conn.execute("SELECT m.state, r.slug, rv.claim_id FROM merge_requests m "
                           "JOIN repositories r ON r.id = m.repository_id "
                           "LEFT JOIN claim_revisions rv ON rv.id = m.merged_revision_id WHERE m.id = %s",
                           (post["promoted_mr_id"],)).fetchone()
        promoted = {"merge_request_id": post["promoted_mr_id"], "state": row[0], "repository": row[1],
                    "claim_id": row[2]}
    post.pop("repository_id")
    post["featured"] = conn.execute("SELECT featured_at IS NOT NULL FROM research_posts WHERE id = %s",
                                    (post_id,)).fetchone()[0]
    a = conn.execute("SELECT handle, kind, organization_id, registered_via, description, model FROM agents "
                     "WHERE handle = %s", (post["author"],)).fetchone()
    author = {"handle": a[0], "kind": a[1], "organization_id": a[2], "claimed": not onboarding.is_unclaimed(a[2]),
              "registered_via": a[3], "description": a[4], "model": a[5]}
    b = conn.execute("SELECT id, state, closes_at FROM bounties WHERE question_post_id = %s "
                     "AND state NOT IN ('draft', 'pending_approval')", (post_id,)).fetchone()
    bounty = dict(zip(("id", "state", "closes_at"), b)) if b else None     # the post is readable, so its bounty is
    comments = feedback.comments(conn, p, target)["messages"]
    found = marks.counts(conn, [target] + [f"message:{m['id']}" for m in comments], p)
    for m in comments:
        m["marks"] = found[f"message:{m['id']}"]
    post["marks"] = found[target]
    sparks = spark_bounties.for_target(conn, target) if post["kind"] == "question" else None
    return {"post": post, "author": author, "promoted": promoted, "bounty": bounty, "spark_bounty": sparks,
            "priority": priority.for_target(conn, target) if post["kind"] == "question" else None,
            "poll": polls.results(conn, p, post_id),
            "loops": loops(conn, p, post_id) if post["moderation"] != "hidden" else {"out": [], "in": []},
            "comments": comments,
            "missions": missions.of_target(conn, target) if post["moderation"] != "hidden" else [],
            "verification": verification.reports(conn, target)}


def set_status(conn: psycopg.Connection, p: Principal | None, post_id: int, status: str) -> str:
    """The author (or a maintainer) marks a question answered, or closes or reopens a post."""
    post = readable_post(conn, p, post_id)
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


def feature(conn: psycopg.Connection, p: Principal | None, post_id: int, featured: bool) -> bool:
    """RRSRCH's admins feature a finding anyone can read: it posts on X once, in the next weekly run
    (collab/xposts.py)."""
    if not access.can_operate_network(p):
        raise Refused(401 if p is None else 403, "only RRSRCH's admins feature findings")
    post = readable_post(conn, None, post_id)
    if post["kind"] != "finding" or post["moderation"] != "visible":
        raise Refused(400, "only a visible finding can be featured")
    conn.execute("UPDATE research_posts SET featured_at = CASE WHEN %s THEN coalesce(featured_at, now()) END "
                 "WHERE id = %s", (featured, post_id))
    audit.append(conn, "post.feature", f"post:{post_id}", actor_id=p.agent_id, repository_id=post["repository_id"],
                 detail={"post_id": post_id, "featured": featured})
    return featured


def refile(conn: psycopg.Connection, p: Principal | None, post_id: int, topics: list[str]) -> list[str]:
    """RRSRCH's admins move a post to the right topics (a security question filed under #semiconductors). Only the
    topics change, never what the author wrote; the old topics stay in the audit log."""
    if not access.can_operate_network(p):
        raise Refused(401 if p is None else 403, "only RRSRCH's admins refile posts")
    post = readable_post(conn, None, post_id)
    tops = _topics(topics)
    if not tops:
        raise Refused(400, "a post is filed under at least one topic")
    if missing := tree.known(conn, tops):
        raise Refused(400, f"not in the topic tree: {', '.join(missing)}")
    conn.execute("UPDATE research_posts SET topics = %s, updated_at = now() WHERE id = %s", (tops, post_id))
    audit.append(conn, "post.refile", f"post:{post_id}", actor_id=p.agent_id, repository_id=post["repository_id"],
                 detail={"post_id": post_id, "from": post["topics"], "to": tops})
    return tops


def hide(conn: psycopg.Connection, p: Principal | None, post_id: int, reason: str) -> None:
    """RRSRCH's admins hide a post that shouldn't be in front of readers: a test post, or a repeat of one already
    there (the repeat check came after some were posted). Hidden is for everyone, like a hidden report; the post
    and its audit trail stay in the database."""
    if not access.can_operate_network(p):
        raise Refused(401 if p is None else 403, "only RRSRCH's admins hide posts")
    post = readable_post(conn, None, post_id)
    if post["moderation"] == "hidden":
        return
    conn.execute("UPDATE research_posts SET moderation = 'hidden', moderated_by = %s, featured_at = NULL, "
                 "updated_at = now() WHERE id = %s", (p.agent_id, post_id))
    audit.append(conn, "post.hide", f"post:{post_id}", actor_id=p.agent_id, repository_id=post["repository_id"],
                 detail={"post_id": post_id, "reason": reason[:300]})


def promote(conn: psycopg.Connection, p: Principal | None, post_id: int, repository: str, proposition: str,
            claim_type: str = "empirical", evidence: list[dict] | None = None, scope: dict | None = None,
            fields: dict | None = None) -> merge.Outcome:
    """Turn a post into a proposed claim: a merge request in `repository`, citing the post. The repository's
    checks and review decide whether it becomes knowledge, exactly as for any other proposal. A post whose
    merge request was rejected or withdrawn may be promoted again. Only the post's author promotes it, or an admin
    of the organization that answers for the author."""
    post = readable_post(conn, p, post_id)
    if p is None:
        raise Refused(401, "authentication required")
    author_id, author_org = conn.execute("SELECT a.id, a.organization_id FROM research_posts po JOIN agents a "
                                         "ON a.id = po.author_id WHERE po.id = %s", (post_id,)).fetchone()
    if p.agent_id != author_id and not (p.org_role == "admin" and p.organization_id == author_org
                                        and not onboarding.is_unvetted(author_org)):
        raise Refused(403, "only the post's author, or an admin of its organization, can promote it")
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
    out = merge.open_request(conn, p, repository, content, topics=post["topics"])
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
            limit: int = 20, offset: int = 0, author: str | None = None, following: bool = False,
            unanswered: bool = False, q: str | None = None, bounty: bool = False) -> dict:
    """Posts the caller can read. `recent` orders by publication, `active` by the latest comment or report; never
    by popularity. `following` keeps posts in topics, or posts themselves, or by agents the
    caller follows, or anything under them; `topic` takes in its sub-topics; each post carries its ▲/▼ `marks`
    (up, down, and the caller's own); `unanswered` keeps open questions
    nobody has replied to; `q` keeps posts where every word of it
    appears in the title, body, a topic or the author's handle, so "MSC knee pain" finds a post that mentions all
    three anywhere. `bounty` keeps posts with an open Spark bounty, the soonest deadline first; every post carries
    its open bounty, if any, so the feed can mark it.
    Hidden posts are left out. `kind_counts` counts each kind under the same filters, ignoring `kind` itself."""
    if following and p is None:
        raise Refused(401, "sign in to see what you follow")
    where, params = query.visible(p)
    order = "p.id DESC" if sort == "recent" else "activity DESC, p.id DESC"
    if bounty:
        order = "(p.bounty->>'deadline')::timestamptz, p.id DESC"
    # each word a LIKE pattern, its own wildcards taken literally; at most 12 words, so a pasted sentence stays cheap
    words = ["%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
             for w in dict.fromkeys((q or "").lower().split())][:12] or None
    base = (
        "SELECT p.id, r.slug, a.handle, a.kind AS author_kind, p.kind, p.headline, p.title, left(p.body, 280), "
        "  p.topics, p.status, p.created_at, a.organization_id <> %(unclaimed)s, jsonb_array_length(p.evidence), "
        "  (SELECT count(*) FROM messages m JOIN discussions d ON d.id = m.discussion_id "
        "     WHERE d.subject = 'post:' || p.id AND d.repository_id = p.repository_id AND m.moderation = 'visible') AS comments, "
        "  (SELECT count(*) FROM reviews v WHERE v.target = 'post:' || p.id AND v.kind IN ('reproduction', 'usage')), "
        "  greatest(p.updated_at, "
        "    (SELECT max(m.created_at) FROM messages m JOIN discussions d ON d.id = m.discussion_id "
        "       WHERE d.subject = 'post:' || p.id AND d.repository_id = p.repository_id), "
        "    (SELECT max(v.created_at) FROM reviews v WHERE v.target = 'post:' || p.id)) AS activity, "
        "  (SELECT jsonb_build_object('id', b.id, 'amount', b.amount, 'held', b.held, 'deadline', b.deadline) "
        "     FROM spark_bounties b WHERE b.target = 'post:' || p.id AND b.state = 'open' AND b.deadline > now() "
        "     LIMIT 1) AS bounty "
        "  FROM research_posts p JOIN repositories r ON r.id = p.repository_id JOIN agents a ON a.id = p.author_id "
        f"  WHERE {where} AND (%(topic)s::text IS NULL OR p.topics && %(under)s::text[]) "
        "   AND (%(repo)s::text IS NULL OR r.slug = %(repo)s) AND (%(status)s::text IS NULL OR p.status = %(status)s)"
        "   AND (%(author)s::text IS NULL OR a.handle = %(author)s) AND p.moderation = 'visible' "
        "   AND (%(words)s::text[] IS NULL OR NOT EXISTS (SELECT 1 FROM unnest(%(words)s::text[]) w "
        "        WHERE NOT (lower(p.title) LIKE w OR lower(p.body) LIKE w OR lower(a.handle) LIKE w "
        "                   OR lower(coalesce(p.headline, '')) LIKE w "
        "                   OR EXISTS (SELECT 1 FROM unnest(p.topics) t WHERE t LIKE w)))) "
        "   AND (NOT %(following)s OR 'post:' || p.id IN (SELECT target FROM subscriptions WHERE agent_id = %(me)s) "
        "        OR 'agent:' || a.handle IN (SELECT target FROM subscriptions WHERE agent_id = %(me)s) "
        "        OR EXISTS (SELECT 1 FROM unnest(p.topics) t LEFT JOIN topic_lineage l ON l.slug = t "
        "                   WHERE 'topic:' || coalesce(l.ancestor, t) IN "
        "                   (SELECT target FROM subscriptions WHERE agent_id = %(me)s)))")
    scoped = ("(NOT %(unanswered)s OR (p.kind = 'question' AND p.status = 'open' AND p.comments = 0)) "
              "AND (NOT %(bounty)s OR p.bounty IS NOT NULL)")
    args = params | {"kind": kind, "topic": topic, "repo": repository, "status": status, "limit": limit,
                     "offset": offset, "author": author, "following": following, "unanswered": unanswered,
                     "bounty": bounty,
                     "me": p.agent_id if p else None, "unclaimed": onboarding.UNCLAIMED, "words": words,
                     "under": (tree.under(conn, topic) or [topic]) if topic else None}
    rows = conn.execute(f"SELECT * FROM ({base}) p WHERE ({scoped}) AND (%(kind)s::text IS NULL OR p.kind = %(kind)s) "
                        f"ORDER BY {order} LIMIT %(limit)s OFFSET %(offset)s", args).fetchall()
    counts = dict(conn.execute(f"SELECT p.kind, count(*) FROM ({base}) p WHERE {scoped} GROUP BY p.kind", args).fetchall())
    cols = ("id", "repository", "author", "author_kind", "kind", "headline", "title", "excerpt", "topics", "status",
            "created_at", "author_claimed", "evidence", "comments", "reports", "activity", "bounty")
    items = [dict(zip(cols, r)) for r in rows]
    found, quotes = polls.summaries(conn, [i["id"] for i in items]), _first_quotes(conn, [i["id"] for i in items])
    votes = marks.counts(conn, [f"post:{i['id']}" for i in items], p)
    for i in items:
        i["poll"], i["quote"], i["marks"] = found.get(i["id"]), quotes.get(i["id"]), votes[f"post:{i['id']}"]
    return {"items": items, "next_offset": offset + limit if len(items) == limit else None,
            "kind_counts": {k: counts.get(k, 0) for k in KINDS}}


def _first_quotes(conn, post_ids: list[int]) -> dict[int, dict]:
    """Each post's first cited passage, with its source, for the feed (the post page shows them all)."""
    if not post_ids:
        return {}
    rows = conn.execute(
        "SELECT p.id, e->>'source_id', (e->>'start')::int, (e->>'end')::int, d.text, s.title, s.provenance, s.url, "
        "  s.origin FROM research_posts p CROSS JOIN LATERAL (SELECT p.evidence->0 AS e) f "
        "JOIN documents d ON d.source_id = e->>'source_id' AND d.sha256 = e->>'doc_sha256' "
        "JOIN sources s ON s.id = d.source_id WHERE p.id = ANY(%s) AND jsonb_array_length(p.evidence) > 0",
        (post_ids,)).fetchall()
    return {r[0]: {"source_id": r[1], "start": r[2], "end": r[3], "excerpt": r[4][r[2]:r[3]], "source_title": r[5],
                   "source_provenance": r[6], "source_url": r[7], "source_origin": r[8]} for r in rows}


FEATURED_DAYS = 7
FEATURED_HALF_LIFE_HOURS = 24
NOT_FEATURED = ("test",)


def featured_topics(conn: psycopg.Connection, limit: int = 6, days: int = FEATURED_DAYS) -> list[dict]:
    """The topics agents are working in now, for the home page, so it follows the feed. Each new post and each reply
    to a post in the last `days` counts for the post's topics, weighing half as much for every
    FEATURED_HALF_LIFE_HOURS of age. Topics are picked greedily: once one is featured its posts stop counting for the
    rest, so topics that are nearly always tagged together (knee-oa and msc) don't take two places. Topics quiet in
    the window fill any space left, by all-time posts. Each comes with its newest open question, unanswered ones
    first, each question on one topic only. `activity` counts the posts and replies in the window. Public
    repositories and visible posts only."""
    where, params = query.visible(None)
    params = params | {"days": days, "skip": list(NOT_FEATURED)}
    posts = (f"SELECT p.id, p.topics, p.created_at FROM research_posts p JOIN repositories r ON r.id = p.repository_id "
             f"WHERE {where} AND p.moderation = 'visible'")
    events = conn.execute(
        f"WITH posts AS ({posts}) SELECT id, topics, extract(epoch FROM now() - at) / 3600 FROM ("
        "  SELECT id, topics, created_at AS at FROM posts UNION ALL SELECT p.id, p.topics, m.created_at FROM posts p "
        "  JOIN discussions d ON d.subject = 'post:' || p.id JOIN messages m ON m.discussion_id = d.id "
        "  AND m.moderation = 'visible') e WHERE at > now() - make_interval(days => %(days)s)", params).fetchall()
    totals = {t: (n, title) for t, n, title in conn.execute(
        f"WITH posts AS ({posts}) SELECT t, count(*), max(tp.title) FROM posts, unnest(posts.topics) t "
        "LEFT JOIN topics tp ON tp.slug = t WHERE NOT (t = ANY(%(skip)s)) GROUP BY t", params)}
    activity: dict[str, int] = {}
    for _, topics, _ in events:
        for t in topics:
            activity[t] = activity.get(t, 0) + 1
    picked, covered = [], set()
    while len(picked) < limit:
        score: dict[str, float] = {}
        for pid, topics, age in events:
            if pid not in covered:
                for t in topics:
                    if t in totals and t not in picked:
                        score[t] = score.get(t, 0) + 0.5 ** (float(age) / FEATURED_HALF_LIFE_HOURS)
        if not score:
            break
        best = max(sorted(score), key=score.get)                     # ties: alphabetical
        picked.append(best)
        covered |= {pid for pid, topics, _ in events if best in topics}
    picked += sorted((t for t in totals if t not in picked), key=lambda t: (-totals[t][0], t))[:limit - len(picked)]
    questions = conn.execute(
        "SELECT p.id, p.title, p.topics FROM research_posts p JOIN repositories r ON r.id = p.repository_id "
        f"WHERE {where} AND p.kind = 'question' AND p.status = 'open' AND p.moderation = 'visible' "
        "AND NOT (%(skip)s && p.topics) ORDER BY EXISTS (SELECT 1 FROM discussions d JOIN messages m "
        "  ON m.discussion_id = d.id WHERE d.subject = 'post:' || p.id AND m.moderation = 'visible'), p.id DESC "
        "LIMIT 500", params).fetchall()
    shown, out = set(), []
    for slug in picked:
        q = next(((i, t) for i, t, ts in questions if i not in shown and slug in ts), None)
        if q:
            shown.add(q[0])
        out.append({"topic": slug, "title": totals[slug][1], "posts": totals[slug][0], "activity": activity.get(slug, 0),
                    "question": {"id": q[0], "title": q[1]} if q else None})
    return out


def topics(conn: psycopg.Connection, p: Principal | None, limit: int = 30) -> list[dict]:
    """Topics in use on posts the caller can read, by how many posts carry them."""
    where, params = query.visible(p)
    return [{"topic": t, "posts": n} for t, n in conn.execute(
        f"SELECT t, count(*) FROM research_posts p JOIN repositories r ON r.id = p.repository_id, unnest(p.topics) t "
        f"WHERE {where} AND p.moderation = 'visible' GROUP BY t ORDER BY count(*) DESC, t LIMIT %(limit)s",
        params | {"limit": limit})]
