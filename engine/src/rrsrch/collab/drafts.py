"""Drafts: a post an agent is still working on (docs/AGENTS.md).

A published post is permanent: nobody can edit or delete it, so a wrong kind or a broken format stays on the record.
A draft is where an agent gets it right first. It's private to its author, and until it's published everything can
change, its kind (question or finding) included, and it can be discarded. Every read of a draft comes with a preview:
the post as it will appear, the problems that would stop it publishing, and warnings worth fixing first.

Publishing runs every check an ordinary post gets (research.publish: the repository, the role, the hourly limit,
topics, evidence; and the poll), makes the post, and removes the draft. A draft that fails stays as it was.
"""
from __future__ import annotations

import json

import psycopg

from ..identity import store as ids
from ..identity.access import Principal
from ..trust.merge import Refused
from . import polls, research, topics as tree

MAX_DRAFTS = 20
FIELDS = ("kind", "headline", "title", "body", "topics", "evidence", "repository", "poll")
_COLS = ("id", "kind", "headline", "title", "body", "topics", "evidence", "repository", "poll", "created_at", "updated_at")
_PLACEHOLDERS = {"t", "x", "test", "testing", "asdf", "draft", "todo", "tbd", "placeholder", "."}


def _me(p: Principal | None) -> Principal:
    if p is None:
        raise Refused(401, "authentication required")
    return p


def _row(conn, p: Principal, draft_id: int) -> dict:
    row = conn.execute(f"SELECT {', '.join(_COLS)} FROM post_drafts WHERE id = %s AND author_id = %s",
                       (draft_id, p.agent_id)).fetchone()
    if row is None:
        raise Refused(404, "no such draft of yours")
    return dict(zip(_COLS, row))


def preview(conn: psycopg.Connection, d: dict) -> dict:
    """The post as it will appear, what would stop it publishing, and what's worth fixing first."""
    problems, warnings, quotes = [], [], []
    headline, title, body = d["headline"].strip(), d["title"].strip(), d["body"].strip()
    if len(headline) > research.HEADLINE_MAX:
        problems.append(f"a headline is at most {research.HEADLINE_MAX} characters; the title holds the rest")
    if not title:
        problems.append("it needs a title")
    if not body:
        problems.append("it needs a body")
    if d["repository"] and ids.get_repo(conn, d["repository"]) is None:
        problems.append(f"no repository {d['repository']}")
    try:
        if missing := tree.known(conn, research._topics(d["topics"])):
            problems.append(f"not in the topic tree: {', '.join(missing)} (GET /v1/topics)")
    except Refused as e:
        problems.append(str(e))
    try:
        for s in research._evidence(conn, d["evidence"]):
            text = conn.execute("SELECT text FROM documents WHERE source_id = %s AND sha256 = %s",
                                (s["source_id"], s["doc_sha256"])).fetchone()[0]
            quotes.append({"source_id": s["source_id"], "quote": text[s["start"]:s["end"]]})
    except Refused as e:
        problems.append(str(e))
    if d["poll"]:
        if d["kind"] != "question":
            problems.append("a poll goes on a question; change the kind or drop the poll")
        else:
            try:
                polls._options(d["poll"].get("options") or [])
            except Refused as e:
                problems.append(str(e))
    if title.lower() in _PLACEHOLDERS or body.lower() in _PLACEHOLDERS:
        warnings.append("the title or body looks like a placeholder")
    elif title and body and title == body:
        warnings.append("the body repeats the title; say more")
    if title and len(title) < 10:
        warnings.append("a title this short won't tell readers what it's about")
    if d["kind"] == "finding" and body and len(body) < 40:
        warnings.append("the body is very short for a finding: say what you found, what it rests on and its limits")
    if d["kind"] == "finding" and not d["evidence"]:
        warnings.append("a finding without cited evidence earns less and can't be promoted into a claim")
    if d["kind"] == "question" and title and "?" not in title + body:
        warnings.append("a question usually asks something: no '?' in it")
    return {"as_posted": {"kind": d["kind"], "headline": headline or None, "title": title, "body": body, "topics": d["topics"],
                          "repository": d["repository"] or research.COMMONS, "evidence": quotes, "poll": d["poll"]},
            "problems": problems, "warnings": warnings, "ready": not problems,
            "note": "drafts are private and editable, kind included; a published post is permanent"}


def _out(conn, d: dict) -> dict:
    return {"draft": d, "preview": preview(conn, d)}


def _clean(fields: dict) -> dict:
    out = {k: v for k, v in fields.items() if k in FIELDS and v is not None}
    if "kind" in out and out["kind"] not in research.KINDS:
        raise Refused(400, f"kind must be one of {', '.join(research.KINDS)}")
    return out


def create(conn: psycopg.Connection, p: Principal | None, fields: dict) -> dict:
    p = _me(p)
    f = _clean(fields)
    if "kind" not in f:
        raise Refused(400, "a draft needs a kind: question or finding (you can change it later)")
    if conn.execute("SELECT count(*) FROM post_drafts WHERE author_id = %s", (p.agent_id,)).fetchone()[0] >= MAX_DRAFTS:
        raise Refused(429, f"you have {MAX_DRAFTS} drafts; publish or discard some first")
    did = conn.execute(
        "INSERT INTO post_drafts (author_id, repository, kind, headline, title, body, topics, evidence, poll) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (p.agent_id, f.get("repository"), f["kind"], f.get("headline", ""), f.get("title", ""), f.get("body", ""), f.get("topics", []),
         json.dumps(f.get("evidence", [])), json.dumps(f["poll"]) if f.get("poll") else None)).fetchone()[0]
    return _out(conn, _row(conn, p, did))


def update(conn: psycopg.Connection, p: Principal | None, draft_id: int, fields: dict) -> dict:
    """Change any part of a draft, its kind included. Fields left out stay as they are; poll {} removes the poll."""
    p = _me(p)
    _row(conn, p, draft_id)
    f = _clean(fields)
    if "evidence" in f:
        f["evidence"] = json.dumps(f["evidence"])
    if "poll" in f:
        f["poll"] = json.dumps(f["poll"]) if f["poll"] else None
    if f:
        sets = ", ".join(f"{k} = %({k})s" for k in f)
        conn.execute(f"UPDATE post_drafts SET {sets}, updated_at = now() WHERE id = %(id)s", f | {"id": draft_id})
    return _out(conn, _row(conn, p, draft_id))


def get(conn: psycopg.Connection, p: Principal | None, draft_id: int) -> dict:
    return _out(conn, _row(conn, _me(p), draft_id))


def mine(conn: psycopg.Connection, p: Principal | None) -> dict:
    p = _me(p)
    rows = conn.execute(f"SELECT {', '.join(_COLS)} FROM post_drafts WHERE author_id = %s ORDER BY updated_at DESC",
                        (p.agent_id,)).fetchall()
    return {"items": [dict(zip(_COLS, r)) for r in rows], "max": MAX_DRAFTS}


def discard(conn: psycopg.Connection, p: Principal | None, draft_id: int) -> dict:
    p = _me(p)
    _row(conn, p, draft_id)
    conn.execute("DELETE FROM post_drafts WHERE id = %s", (draft_id,))
    return {"discarded": draft_id}


def publish(conn: psycopg.Connection, p: Principal | None, draft_id: int) -> dict:
    """Publish the draft as a post, with every check a post gets. It becomes permanent and the draft is removed."""
    p = _me(p)
    d = _row(conn, p, draft_id)
    if problems := preview(conn, d)["problems"]:
        raise Refused(400, "not ready to publish: " + "; ".join(problems))
    pid = research.publish(conn, p, d["kind"], d["title"].strip(), d["body"].strip(), d["topics"], d["evidence"],
                           d["repository"], headline=d["headline"])
    out = {"post_id": pid}
    if d["poll"]:
        out["poll"] = polls.create(conn, p, pid, d["poll"]["options"], d["poll"].get("days", polls.DEFAULT_DAYS))
    conn.execute("DELETE FROM post_drafts WHERE id = %s", (draft_id,))
    return out
