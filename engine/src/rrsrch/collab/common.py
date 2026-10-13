"""Shared helpers: rate limits and the audit target for a subject."""
from __future__ import annotations

import psycopg

from ..trust.merge import Refused


def rate_limit(conn: psycopg.Connection, sql: str, params: tuple, limit: int, what: str) -> None:
    """Refuse with 429 when `sql` (a count) has already reached `limit`."""
    if conn.execute(sql, params).fetchone()[0] >= limit:
        raise Refused(429, f"too many {what}; try again later")


def repo_slug(conn: psycopg.Connection, repository_id: int) -> str:
    return conn.execute("SELECT slug FROM repositories WHERE id = %s", (repository_id,)).fetchone()[0]


def subject_target(conn: psycopg.Connection, repository_id: int, subject: str) -> str:
    """Where events about a subject are filed: the subject itself, or the repository."""
    return f"repo:{repo_slug(conn, repository_id)}" if subject == "repo" else subject
