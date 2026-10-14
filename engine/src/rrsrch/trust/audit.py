"""The audit chain: every decision appended, each event hashed over the one before it.

An event's hash covers its canonical form, including the previous event's
hash, so editing or removing any stored event breaks every hash after it.
The table refuses UPDATE and DELETE; `verify` catches what a trigger can't
(someone with superuser rights, a restored backup).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import psycopg

from ..knowledge import canonical

_LOCK = 0x72727372   # serializes appends so two writers can't both chain onto the same event


def _event(at: datetime, actor_id, action, target, repository_id, detail, policy_version, prev_hash) -> dict:
    return {"at": at.astimezone(timezone.utc).isoformat(), "actor_id": actor_id, "action": action,
            "target": target, "repository_id": repository_id, "detail": detail,
            "policy_version": policy_version, "prev_hash": prev_hash}


def append(conn: psycopg.Connection, action: str, target: str, *, actor_id: int | None = None,
           repository_id: int | None = None, detail: dict[str, Any] | None = None,
           policy_version: str | None = None) -> str:
    """Record an event in the caller's transaction. Returns its hash."""
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK,))
    prev = conn.execute("SELECT hash FROM audit_events ORDER BY id DESC LIMIT 1").fetchone()
    at = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    detail = detail or {}
    prev_hash = prev[0] if prev else None
    h = canonical.digest(_event(at, actor_id, action, target, repository_id, detail, policy_version, prev_hash))
    conn.execute("INSERT INTO audit_events (at, actor_id, action, target, repository_id, detail, policy_version, "
                 "prev_hash, hash) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                 (at, actor_id, action, target, repository_id, canonical.dumps(detail).decode(),
                  policy_version, prev_hash, h))
    return h


def verify(conn: psycopg.Connection) -> list[str]:
    """Problems with the chain, oldest first; empty when every event hashes and links correctly."""
    problems, prev = [], None
    for (id_, at, actor_id, action, target, repo_id, detail, policy, prev_hash, h) in conn.execute(
            "SELECT id, at, actor_id, action, target, repository_id, detail, policy_version, prev_hash, hash "
            "FROM audit_events ORDER BY id"):
        if prev_hash != prev:
            problems.append(f"event {id_}: links to {prev_hash}, expected {prev}")
        if canonical.digest(_event(at, actor_id, action, target, repo_id, detail, policy, prev_hash)) != h:
            problems.append(f"event {id_}: content does not match its hash")
        prev = h
    return problems
