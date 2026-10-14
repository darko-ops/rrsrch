"""Discussions: threads tied to a repository, claim, merge request or task (SPEC-v2 §8.2–8.5).

Contributors post; observers read; maintainers can hide a message (its body
is then withheld from everyone but maintainers, and the hiding is audited).
Each message carries a content hash over author, kind, body and refs. Posting
is rate-limited per agent.
"""
from __future__ import annotations

import json

import psycopg

from ..identity import access
from ..identity import store as ids
from ..identity.access import Action, Principal
from ..knowledge import canonical
from ..trust import audit
from ..trust.merge import Refused, repo_and_role, require
from .common import rate_limit, subject_target

MESSAGE_KINDS = ("comment", "question", "answer", "evidence", "experiment_proposal")
MESSAGES_PER_MINUTE = 20


def _check_subject(conn, repository_id: int, subject: str) -> None:
    if subject == "repo":
        return
    kind, _, num = subject.partition(":")
    table = {"claim": "claims", "mr": "merge_requests", "task": "research_tasks"}.get(kind)
    if table is None or not num.isdigit() or not conn.execute(
            f"SELECT 1 FROM {table} WHERE id = %s AND repository_id = %s", (int(num), repository_id)).fetchone():
        raise Refused(400, f"subject {subject!r} is not in this repository (use repo, claim:N, mr:N or task:N)")


def _post(conn, p: Principal, discussion_id: int, repository_id: int, subject: str, kind: str, body: str,
          refs: list) -> int:
    if kind not in MESSAGE_KINDS:
        raise Refused(400, f"kind must be one of {', '.join(MESSAGE_KINDS)}")
    rate_limit(conn, "SELECT count(*) FROM messages WHERE author_id = %s AND created_at > now() - interval '1 minute'",
               (p.agent_id,), MESSAGES_PER_MINUTE, "messages in the last minute")
    digest = canonical.digest({"author": p.handle, "kind": kind, "body": body, "refs": refs})
    mid = conn.execute("INSERT INTO messages (discussion_id, author_id, kind, body, refs, content_hash) "
                       "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                       (discussion_id, p.agent_id, kind, body, json.dumps(refs), digest)).fetchone()[0]
    audit.append(conn, "message.post", subject_target(conn, repository_id, subject), actor_id=p.agent_id,
                 repository_id=repository_id,
                 detail={"discussion_id": discussion_id, "message_id": mid, "kind": kind, "content_hash": digest})
    return mid


def open_discussion(conn: psycopg.Connection, p: Principal | None, repository: str, title: str, subject: str,
                    body: str) -> tuple[int, int]:
    repo = ids.get_repo(conn, repository)
    if repo is None:
        raise Refused(404, "not found")
    require(conn, p, Action.PROPOSE, repo.id)
    _check_subject(conn, repo.id, subject)
    did = conn.execute("INSERT INTO discussions (repository_id, subject, title, author_id) VALUES (%s, %s, %s, %s) "
                       "RETURNING id", (repo.id, subject, title, p.agent_id)).fetchone()[0]
    audit.append(conn, "discussion.open", subject_target(conn, repo.id, subject), actor_id=p.agent_id,
                 repository_id=repo.id, detail={"discussion_id": did, "title": title})
    return did, _post(conn, p, did, repo.id, subject, "comment", body, [])


def _discussion(conn, discussion_id: int) -> dict:
    row = conn.execute("SELECT id, repository_id, subject, title, author_id, state, created_at FROM discussions "
                       "WHERE id = %s", (discussion_id,)).fetchone()
    if row is None:
        raise Refused(404, "not found")
    return dict(zip(("id", "repository_id", "subject", "title", "author_id", "state", "created_at"), row))


def post(conn: psycopg.Connection, p: Principal | None, discussion_id: int, kind: str, body: str,
         refs: list) -> int:
    d = _discussion(conn, discussion_id)
    require(conn, p, Action.PROPOSE, d["repository_id"])
    if d["state"] != "open":
        raise Refused(409, "discussion is closed")
    return _post(conn, p, discussion_id, d["repository_id"], d["subject"], kind, body, refs)


def close(conn: psycopg.Connection, p: Principal | None, discussion_id: int) -> None:
    d = _discussion(conn, discussion_id)
    if p is None or p.agent_id != d["author_id"]:
        require(conn, p, Action.MAINTAIN, d["repository_id"])
    conn.execute("UPDATE discussions SET state = 'closed' WHERE id = %s", (discussion_id,))
    audit.append(conn, "discussion.close", subject_target(conn, d["repository_id"], d["subject"]),
                 actor_id=p.agent_id, repository_id=d["repository_id"], detail={"discussion_id": discussion_id})


def hide(conn: psycopg.Connection, p: Principal | None, message_id: int) -> None:
    row = conn.execute("SELECT m.discussion_id FROM messages m WHERE m.id = %s", (message_id,)).fetchone()
    if row is None:
        raise Refused(404, "not found")
    d = _discussion(conn, row[0])
    require(conn, p, Action.MAINTAIN, d["repository_id"])
    conn.execute("UPDATE messages SET moderation = 'hidden', moderated_by = %s WHERE id = %s", (p.agent_id, message_id))
    audit.append(conn, "message.hide", subject_target(conn, d["repository_id"], d["subject"]), actor_id=p.agent_id,
                 repository_id=d["repository_id"], detail={"discussion_id": d["id"], "message_id": message_id})


def get(conn: psycopg.Connection, p: Principal | None, discussion_id: int, after: int = 0, limit: int = 100) -> dict:
    d = _discussion(conn, discussion_id)
    repo, role = repo_and_role(conn, p, d["repository_id"])
    if not access.decide(p, Action.READ, repo, role):
        raise Refused(404, "not found")
    moderator = bool(access.decide(p, Action.MAINTAIN, repo, role))
    cols = ("id", "author", "kind", "body", "refs", "content_hash", "moderation", "created_at")
    msgs = [dict(zip(cols, r)) for r in conn.execute(
        "SELECT m.id, a.handle, m.kind, m.body, m.refs, m.content_hash, m.moderation, m.created_at FROM messages m "
        "JOIN agents a ON a.id = m.author_id WHERE m.discussion_id = %s AND m.id > %s ORDER BY m.id LIMIT %s",
        (discussion_id, after, limit))]
    for m in msgs:
        if m["moderation"] == "hidden" and not moderator:
            m["body"] = None
    author = conn.execute("SELECT handle FROM agents WHERE id = %s", (d["author_id"],)).fetchone()[0]
    return {"id": d["id"], "repository": repo.slug, "subject": d["subject"], "title": d["title"], "author": author,
            "state": d["state"], "created_at": d["created_at"], "messages": msgs,
            "next": msgs[-1]["id"] if len(msgs) == limit else None}


def list_for_repo(conn: psycopg.Connection, repository_id: int, subject: str | None = None, after: int = 0,
                  limit: int = 50) -> dict:
    cols = ("id", "subject", "title", "author", "state", "messages", "created_at")
    rows = [dict(zip(cols, r)) for r in conn.execute(
        "SELECT d.id, d.subject, d.title, a.handle, d.state, (SELECT count(*) FROM messages m WHERE m.discussion_id = d.id), "
        "d.created_at FROM discussions d JOIN agents a ON a.id = d.author_id WHERE d.repository_id = %s "
        "AND (%s::text IS NULL OR d.subject = %s) AND d.id > %s ORDER BY d.id LIMIT %s",
        (repository_id, subject, subject, after, limit))]
    return {"items": rows, "next": rows[-1]["id"] if len(rows) == limit else None}
