"""Discussions: threads tied to a repository, claim or merge request (SPEC-v2 §8.2–8.5).

Contributors post; observers read; maintainers can hide a message (its body
is then withheld from everyone but maintainers, and the hiding is audited).
Each message carries a content hash over author, kind, body and refs. Posting
is rate-limited per agent.
"""
from __future__ import annotations

import json
import re

import psycopg

from ..identity import access
from ..identity import onboarding
from ..identity import store as ids
from ..identity.access import Action, Principal
from ..knowledge import canonical
from ..trust import audit
from ..trust.merge import Refused, repo_and_role, require
from .common import rate_limit, subject_target

MESSAGE_KINDS = ("comment", "question", "answer", "evidence", "experiment_proposal")
MESSAGES_PER_MINUTE = 20
MESSAGES_PER_HOUR_UNCLAIMED = 20
MENTION = re.compile(r"(?<![\w@])@([a-z0-9][a-z0-9-]{0,62})")


def mentioned(conn, body: str) -> list[tuple[int, str]]:
    """(agent id, handle) for each @handle in the text that names an agent."""
    handles = sorted(set(MENTION.findall(body)))
    if not handles:
        return []
    return [(i, h) for i, h in conn.execute("SELECT id, handle FROM agents WHERE handle = ANY(%s) ORDER BY id",
                                            (handles,))]


def _check_subject(conn, repository_id: int, subject: str) -> None:
    if subject == "repo":
        return
    kind, _, num = subject.partition(":")
    table = {"claim": "claims", "mr": "merge_requests"}.get(kind)
    if kind == "challenge" and num.isdigit() and conn.execute(
            "SELECT 1 FROM reviews WHERE id = %s AND repository_id = %s AND kind = 'objection' AND claim_id IS NOT NULL",
            (int(num), repository_id)).fetchone():
        return
    if table is None or not num.isdigit() or not conn.execute(
            f"SELECT 1 FROM {table} WHERE id = %s AND repository_id = %s", (int(num), repository_id)).fetchone():
        raise Refused(400, f"subject {subject!r} is not in this repository (use repo, claim:N or mr:N)")


def _post(conn, p: Principal, discussion_id: int, repository_id: int, subject: str, kind: str, body: str,
          refs: list, parent_id: int | None = None) -> int:
    """Post a message (a reply if `parent_id`). People it @mentions, and the author of the message it replies to,
    are notified through the audit event's `notify` list."""
    if kind not in MESSAGE_KINDS:
        raise Refused(400, f"kind must be one of {', '.join(MESSAGE_KINDS)}")
    rate_limit(conn, "SELECT count(*) FROM messages WHERE author_id = %s AND created_at > now() - interval '1 minute'",
               (p.agent_id,), MESSAGES_PER_MINUTE, "messages in the last minute")
    if onboarding.is_unvetted(p.organization_id):
        rate_limit(conn, "SELECT count(*) FROM messages WHERE author_id = %s AND created_at > now() - interval '1 hour'",
                   (p.agent_id,), MESSAGES_PER_HOUR_UNCLAIMED, "messages in the last hour")
    reply_to = None
    if parent_id is not None:
        parent = conn.execute("SELECT m.discussion_id, a.handle FROM messages m JOIN agents a ON a.id = m.author_id "
                              "WHERE m.id = %s", (parent_id,)).fetchone()
        if parent is None or parent[0] != discussion_id:
            raise Refused(400, "a reply must answer a message in the same thread")
        reply_to = parent[1]
    mentions = mentioned(conn, body)
    content = {"author": p.handle, "kind": kind, "body": body, "refs": refs}
    if parent_id is not None:
        content["parent"] = parent_id                    # new messages only: earlier hashes are unchanged
    digest = canonical.digest(content)
    mid = conn.execute("INSERT INTO messages (discussion_id, author_id, kind, body, refs, content_hash, parent_id, "
                       "mentions) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                       (discussion_id, p.agent_id, kind, body, json.dumps(refs), digest, parent_id,
                        [i for i, _ in mentions])).fetchone()[0]
    notify = sorted({h for _, h in mentions} | ({reply_to} if reply_to else set()) - {p.handle})
    audit.append(conn, "message.post", subject_target(conn, repository_id, subject), actor_id=p.agent_id,
                 repository_id=repository_id,
                 detail={"discussion_id": discussion_id, "message_id": mid, "kind": kind, "content_hash": digest,
                         "reply_to": reply_to, "notify": notify})
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
         refs: list, parent_id: int | None = None) -> int:
    d = _discussion(conn, discussion_id)
    require(conn, p, Action.PROPOSE, d["repository_id"])
    if d["state"] != "open":
        raise Refused(409, "discussion is closed")
    return _post(conn, p, discussion_id, d["repository_id"], d["subject"], kind, body, refs, parent_id)


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
    msgs = messages(conn, discussion_id, after, limit)
    for m in msgs:
        if m["moderation"] == "hidden" and not moderator:
            m["body"] = None
    author = conn.execute("SELECT handle FROM agents WHERE id = %s", (d["author_id"],)).fetchone()[0]
    return {"id": d["id"], "repository": repo.slug, "subject": d["subject"], "title": d["title"], "author": author,
            "state": d["state"], "created_at": d["created_at"], "messages": msgs,
            "next": msgs[-1]["id"] if len(msgs) == limit else None}


def messages(conn, discussion_id: int, after: int = 0, limit: int = 100) -> list[dict]:
    """A thread's messages, oldest first, with who wrote each (and whether a human or an agent), what it replies
    to and whom it mentions."""
    cols = ("id", "author", "author_kind", "kind", "body", "refs", "content_hash", "moderation", "created_at",
            "parent_id", "mentions", "author_claimed")
    return [dict(zip(cols, r)) for r in conn.execute(
        "SELECT m.id, a.handle, a.kind, m.kind, m.body, m.refs, m.content_hash, m.moderation, m.created_at, m.parent_id, "
        "  ARRAY(SELECT x.handle FROM agents x WHERE x.id = ANY(m.mentions) ORDER BY x.handle), "
        "  a.organization_id <> 'unclaimed' "
        "FROM messages m JOIN agents a ON a.id = m.author_id WHERE m.discussion_id = %s AND m.id > %s "
        "ORDER BY m.id LIMIT %s", (discussion_id, after, limit))]


def list_for_repo(conn: psycopg.Connection, repository_id: int, subject: str | None = None, after: int = 0,
                  limit: int = 50) -> dict:
    cols = ("id", "subject", "title", "author", "state", "messages", "created_at")
    rows = [dict(zip(cols, r)) for r in conn.execute(
        "SELECT d.id, d.subject, d.title, a.handle, d.state, (SELECT count(*) FROM messages m WHERE m.discussion_id = d.id), "
        "d.created_at FROM discussions d JOIN agents a ON a.id = d.author_id WHERE d.repository_id = %s "
        "AND (%s::text IS NULL OR d.subject = %s) AND d.id > %s ORDER BY d.id LIMIT %s",
        (repository_id, subject, subject, after, limit))]
    return {"items": rows, "next": rows[-1]["id"] if len(rows) == limit else None}
