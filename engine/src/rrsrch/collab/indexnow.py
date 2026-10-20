"""IndexNow: tell search engines (Bing, and through it ChatGPT search and Copilot; Yandex, Seznam, Naver) which
public pages changed, so a claim that becomes supported is re-crawled in hours rather than weeks.

Triggers (db/migrations/0022_discovery.sql) queue a page when a public claim's state changes or it enters a
public repository, and when a public question is asked or answered. `send` posts the queue in batches to
api.indexnow.org with the site's key; the key file it names lives on the site at /{key}.txt (the site serves it
from its own INDEXNOW_KEY). With no RRSRCH_INDEXNOW_KEY set, nothing is sent and the queue just waits.

A failed batch stays queued with its error and is retried on the next run, up to MAX_ATTEMPTS.
"""
from __future__ import annotations

import os
import re
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx
import psycopg

ENDPOINT = "https://api.indexnow.org/indexnow"
BATCH = 10_000                      # IndexNow's limit per request
MAX_ATTEMPTS = 8
_KEY = re.compile(r"^[A-Za-z0-9-]{8,128}$")   # the protocol's key format


def base_url() -> str:
    return os.environ.get("RRSRCH_PUBLIC_URL", "https://rrsrch.com").rstrip("/")


def seed(conn: psycopg.Connection) -> int:
    """Queue every public claim and question once (after first configuring IndexNow). Returns how many."""
    return conn.execute(
        "INSERT INTO indexnow_queue (path) "
        "SELECT '/claims/' || c.id FROM claims c JOIN repositories r ON r.id = c.repository_id "
        "WHERE r.visibility = 'public' AND r.deleted_at IS NULL "
        "UNION ALL SELECT '/questions/' || p.id FROM research_posts p JOIN repositories r ON r.id = p.repository_id "
        "WHERE r.visibility = 'public' AND r.deleted_at IS NULL AND p.kind = 'question' AND p.moderation = 'visible' "
        "ON CONFLICT DO NOTHING").rowcount


def pending(conn: psycopg.Connection) -> int:
    return conn.execute("SELECT count(*) FROM indexnow_queue WHERE sent_at IS NULL AND attempts < %s",
                        (MAX_ATTEMPTS,)).fetchone()[0]


def send(conn: psycopg.Connection, key: str | None = None,
         post: Callable[..., httpx.Response] | None = None) -> dict:
    """Send what's queued, a batch at a time. Returns {"sent", "failed", "pending", "skipped"?}; never the key."""
    key = key if key is not None else os.environ.get("RRSRCH_INDEXNOW_KEY", "")
    if not key:
        return {"sent": 0, "failed": 0, "pending": pending(conn), "skipped": "RRSRCH_INDEXNOW_KEY is not set"}
    if not _KEY.match(key):
        return {"sent": 0, "failed": 0, "pending": pending(conn), "skipped": "RRSRCH_INDEXNOW_KEY is not a valid key"}
    post = post or (lambda url, **kw: httpx.post(url, timeout=30, **kw))
    base = base_url()
    sent = failed = 0
    while True:
        rows = conn.execute("SELECT id, path FROM indexnow_queue WHERE sent_at IS NULL AND attempts < %s "
                            "ORDER BY id LIMIT %s", (MAX_ATTEMPTS, BATCH)).fetchall()
        if not rows:
            break
        ids = [i for i, _ in rows]
        body = {"host": urlsplit(base).hostname, "key": key, "keyLocation": f"{base}/{key}.txt",
                "urlList": [base + path for _, path in rows]}
        try:
            r = post(ENDPOINT, json=body, headers={"Content-Type": "application/json; charset=utf-8"})
            error = None if r.status_code in (200, 202) else f"HTTP {r.status_code}: {r.text[:200]}"
        except httpx.HTTPError as e:
            error = f"unreachable: {type(e).__name__}"
        if error is None:
            conn.execute("UPDATE indexnow_queue SET sent_at = now(), attempts = attempts + 1, last_error = NULL "
                         "WHERE id = ANY(%s)", (ids,))
            sent += len(ids)
        else:
            conn.execute("UPDATE indexnow_queue SET attempts = attempts + 1, last_error = %s WHERE id = ANY(%s)",
                         (error.replace(key, "<key>"), ids))
            failed += len(ids)
            conn.commit()
            break                                       # the service is refusing or down: try again next run
        conn.commit()
    return {"sent": sent, "failed": failed, "pending": pending(conn)}
