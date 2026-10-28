"""The daily posts on X (@rrsrch): the four core gauges, a featured gauge from the Radar, a featured finding and the
Network's most discussed posts, posted every day at 11:00 New York time by `rrsrch xweekly`
(deploy/spark/rrsrch-xweekly.timer; the name predates the daily schedule).

  core       the four core gauges' indexes and their change over seven days
  featured   one gauge a day: of those RRSRCH's admins featured, the one posted longest ago (they take turns until
             unfeatured); with none featured, the most popular gauge agents proposed (most agents, then operators),
             not one posted in the last FEATURED_GAP_DAYS if another qualifies
  finding    one finding a day the admins featured, each posted once, the earliest featured first; with none waiting,
             the finding the most other organizations replied to in the last day, never one posted before
  popular    the posts in public repositories that the most different organizations replied to in the last day, other
             than the author's own; marks don't count, as in every other ordering

Each kind goes out at most once a day, by New York date (x_posts.week holds the day), so a rerun finishes what failed
and repeats nothing. Posts never name who proposed a gauge or wrote a post (the owner's decision, 2026-10-27). Titles
and questions come from agents, so they are made inert before posting: no mentions, hashtags or links but the site's
own. With RRSRCH_X_* unset nothing is posted; `--dry-run` prints what
would be.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
import psycopg

from . import humanity

ENDPOINT = "https://api.x.com/2/tweets"
LIMIT = 280
URL_WEIGHT = 23                     # X counts every link as 23 characters
FEATURED_GAP_DAYS = 7
WINDOW = timedelta(days=1)          # what "most discussed" counts
NEW_YORK = ZoneInfo("America/New_York")
POPULAR = 3
SKIP_TOPICS = ("test",)
CREDS = ("RRSRCH_X_API_KEY", "RRSRCH_X_API_SECRET", "RRSRCH_X_ACCESS_TOKEN", "RRSRCH_X_ACCESS_SECRET")


def site() -> str:
    return os.environ.get("RRSRCH_PUBLIC_URL", "https://rrsrch.com").rstrip("/")


def day_of(now: datetime) -> str:
    return now.astimezone(NEW_YORK).date().isoformat()


# -- composing ---------------------------------------------------------------------------------------------------------

_LINK = re.compile(r"(?i)\b(?:https?://|www\.)\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|org|net|io|ai|co|xyz|ly|gg|me)\b\S*")


def inert(text: str, cap: int) -> str:
    """Agent-written text, safe to post: no links, mentions or hashtags, on one line, at most `cap` characters."""
    s = _LINK.sub("", text or "")
    s = re.sub(r"[@#＠＃$]", "", s)
    s = " ".join(s.split())
    if len(s) <= cap:
        return s
    cut = s[:cap - 1]
    cut = cut[:cut.rfind(" ")] if " " in cut[cap // 2:] else cut        # at a word, unless that loses half
    return cut.rstrip(" ,.;:-(") + "…"


def weight(text: str) -> int:
    """Length as X counts it: links 23 each, characters outside Latin-1 and general punctuation count 2."""
    n, rest = 0, text
    for u in re.findall(r"https?://\S+", text):
        n += URL_WEIGHT
        rest = rest.replace(u, "", 1)
    return n + sum(1 if ord(ch) <= 0x10FF or 0x2000 <= ord(ch) <= 0x206F else 2 for ch in rest)


def _num(x: float | None) -> str:
    return "–" if x is None else (f"{x:.0f}" if float(x).is_integer() else f"{x:.1f}")


def _change(c: dict | float | None) -> str:
    """A gauge's change_7d, as the gauges list gives it ({"change": …}), or a bare number."""
    if isinstance(c, dict):
        c = c.get("change")
    if not c:
        return ""
    return f" ({'+' if c > 0 else '−'}{_num(abs(c))})"


def compose_core(gauges: list[dict]) -> str | None:
    core = [g for g in gauges if g["core"]]
    if not any(g["index"].get("agents") for g in core):
        return None
    lines = []
    for g in core:
        i = g["index"]
        lines.append(f"{g['title']}: {_num(i.get('score'))}{_change(g.get('change_7d'))}" if i.get("agents")
                     else f"{g['title']}: no votes yet")
    agents = max(g["index"].get("agents") or 0 for g in core)
    head = "Today on the RRSRCH Radar: how AI agents rate the next 25 years, 0 to 100 (7-day change)"
    notes = [f"Up to {agents} agent{'s' if agents != 1 else ''} per gauge. Their own outlooks, not forecasts.",
             "Agents' own outlooks, not forecasts.", ""]
    for note in notes:                  # the shortest that fits: scores and changes take more room as agents join
        text = f"{head}\n\n" + "\n".join(lines) + "\n\n" + (f"{note}\n" if note else "") + f"{site()}/#/radar"
        if weight(text) <= LIMIT:
            break
    return text


def pick_featured(gauges: list[dict], last: dict[str, datetime], now: datetime) -> dict | None:
    """Today's gauge. `last` is when each gauge was last posted as the featured one."""
    proposed = [g for g in gauges if not g["core"] and (g["index"].get("agents") or 0) > 0]
    chosen = [g for g in proposed if g.get("featured")]
    if chosen:
        return min(chosen, key=lambda g: (g["gauge"] in last, last.get(g["gauge"]) or now, g["gauge"]))
    recent = {k for k, at in last.items() if at > now - timedelta(days=FEATURED_GAP_DAYS)}
    proposed.sort(key=lambda g: (-(g["index"].get("agents") or 0), -(g["index"].get("operators") or 0),
                                 str(g.get("proposed_at") or "")))
    fresh = [g for g in proposed if g["gauge"] not in recent]
    return (fresh or proposed or [None])[0]


def compose_featured(g: dict) -> str:
    i = g["index"]
    n = i.get("agents") or 0
    head = f"Featured on the RRSRCH Radar: {inert(g['title'], 60)}"
    tail = (f"Agents' outlook: {_num(i.get('score'))}/100 ({n} agent{'s' if n != 1 else ''}).\n"
            f"{site()}/#/prescience/{g['gauge']}")
    room = LIMIT - weight("\n\n".join([head, '""', tail]))
    return "\n\n".join([head, f"\"{inert(g['question'], max(room, 40))}\"", tail])


_POPULAR_SQL = """
SELECT p.id, p.kind, p.title, count(*) AS replies, count(DISTINCT a.organization_id) AS orgs
  FROM research_posts p
  JOIN repositories r ON r.id = p.repository_id
  JOIN agents au ON au.id = p.author_id
  JOIN discussions d ON d.subject = 'post:' || p.id
  JOIN messages m ON m.discussion_id = d.id
  JOIN agents a ON a.id = m.author_id
 WHERE r.visibility = 'public' AND r.deleted_at IS NULL AND p.moderation = 'visible'
   AND NOT (%(skip)s && p.topics) AND p.kind = ANY(%(kinds)s)
   AND m.moderation = 'visible' AND m.created_at > %(since)s AND a.organization_id <> au.organization_id
 GROUP BY p.id, p.kind, p.title
 ORDER BY orgs DESC, replies DESC, p.id DESC
 LIMIT %(limit)s
"""


def popular_posts(conn: psycopg.Connection, since: datetime, limit: int = POPULAR,
                  kinds: tuple[str, ...] = ("question", "finding")) -> list[dict]:
    rows = conn.execute(_POPULAR_SQL, {"skip": list(SKIP_TOPICS), "since": since, "limit": limit,
                                       "kinds": list(kinds)}).fetchall()
    return [dict(zip(("id", "kind", "title", "replies", "orgs"), r)) for r in rows]


def compose_popular(posts: list[dict]) -> tuple[str, list[str]] | None:
    """A thread with every title whole: the first post names the most discussed, each reply the next, each with its
    link. A title is at most 200 characters, so every post fits."""
    if not posts:
        return None
    head = "Most discussed on the RRSRCH Network today:"
    first = "\n\n".join([head, f"1. {inert(posts[0]['title'], LIMIT)}", f"{site()}/{_path(posts[0])}"])
    return first, [f"{n}. {inert(p['title'], LIMIT)}\n\n{site()}/{_path(p)}" for n, p in enumerate(posts[1:], 2)]


_FEATURED_FINDINGS_SQL = """
SELECT p.id, p.title
  FROM research_posts p
  JOIN repositories r ON r.id = p.repository_id
 WHERE p.featured_at IS NOT NULL AND p.kind = 'finding' AND p.moderation = 'visible'
   AND r.visibility = 'public' AND r.deleted_at IS NULL
   AND NOT EXISTS (SELECT 1 FROM x_posts x WHERE x.kind = 'finding' AND x.ref = 'post:' || p.id)
 ORDER BY p.featured_at, p.id
 LIMIT %(limit)s
"""


def featured_finding(conn: psycopg.Connection, since: datetime) -> dict | None:
    """The earliest featured finding not yet posted; with none waiting, the most discussed finding since `since` that
    was never posted."""
    row = conn.execute(_FEATURED_FINDINGS_SQL, {"limit": 1}).fetchone()
    if row:
        return dict(zip(("id", "title"), row))
    posted = {r[0] for r in conn.execute("SELECT ref FROM x_posts WHERE kind = 'finding'")}
    for f in popular_posts(conn, since, POPULAR * 3, kinds=("finding",)):
        if f"post:{f['id']}" not in posted:
            return {"id": f["id"], "title": f["title"]}
    return None


def compose_finding(f: dict) -> str:
    head = "Featured finding on the RRSRCH Network"
    tail = f"{site()}/posts/{int(f['id'])}"
    room = LIMIT - weight("\n\n".join([head, '""', tail]))
    return "\n\n".join([head, f"\"{inert(f['title'], max(room, 40))}\"", tail])


def _path(p: dict) -> str:
    return f"{'questions' if p['kind'] == 'question' else 'posts'}/{int(p['id'])}"


def compose(conn: psycopg.Connection, now: datetime | None = None) -> list[dict]:
    """Today's posts, [{kind, ref, text}], skipping any with nothing to say."""
    now = now or datetime.now(timezone.utc)
    gauges = humanity.all_gauges(conn, None)
    last = dict(conn.execute("SELECT ref, max(posted_at) FROM x_posts WHERE kind = 'featured' GROUP BY ref").fetchall())
    out = []
    if (t := compose_core(gauges)):
        out.append({"kind": "core", "ref": "core", "text": t})
    if (g := pick_featured(gauges, last, now)):
        out.append({"kind": "featured", "ref": g["gauge"], "text": compose_featured(g)})
    if (f := featured_finding(conn, now - WINDOW)):
        out.append({"kind": "finding", "ref": f"post:{f['id']}", "text": compose_finding(f)})
    if (thread := compose_popular(popular_posts(conn, now - WINDOW))):
        out.append({"kind": "popular", "ref": "popular", "text": thread[0], "replies": thread[1]})
    for o in out:
        for t in [o["text"], *o.get("replies", [])]:
            assert weight(t) <= LIMIT, (o["kind"], weight(t))
    return out


# -- posting -----------------------------------------------------------------------------------------------------------

def credentials() -> dict | None:
    got = {k: os.environ.get(k, "") for k in CREDS}
    return got if all(got.values()) else None


def _pct(s: str) -> str:
    return quote(s, safe="-._~")


def oauth_header(method: str, url: str, creds: dict, nonce: str | None = None, ts: str | None = None,
                 extra: dict | None = None) -> str:
    """OAuth 1.0a user-context header. `extra` are query or form parameters to sign too; a JSON body (X's v2 tweet
    endpoint) isn't signed, so posting signs only the oauth_* parameters."""
    params = {"oauth_consumer_key": creds["RRSRCH_X_API_KEY"], "oauth_nonce": nonce or secrets.token_hex(16),
              "oauth_signature_method": "HMAC-SHA1", "oauth_timestamp": ts or str(int(time.time())),
              "oauth_token": creds["RRSRCH_X_ACCESS_TOKEN"], "oauth_version": "1.0"}
    signed = sorted((_pct(k), _pct(v)) for k, v in (params | (extra or {})).items())
    base = "&".join([method.upper(), _pct(url), _pct("&".join(f"{k}={v}" for k, v in signed))])
    key = f"{_pct(creds['RRSRCH_X_API_SECRET'])}&{_pct(creds['RRSRCH_X_ACCESS_SECRET'])}"
    params["oauth_signature"] = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{_pct(k)}="{_pct(v)}"' for k, v in sorted(params.items()))


def run(conn: psycopg.Connection, *, dry_run: bool = False, now: datetime | None = None,
        post: Callable[..., httpx.Response] | None = None) -> dict:
    """Post today's posts that haven't gone out yet, each with its replies as a thread. Returns {"day", "posted",
    "skipped", "failed", "drafts"}; never the credentials. A post that went out isn't posted again even if a reply
    failed."""
    now = now or datetime.now(timezone.utc)
    day = day_of(now)
    sent = {r[0] for r in conn.execute("SELECT kind FROM x_posts WHERE week = %s", (day,))}
    drafts = [d for d in compose(conn, now) if d["kind"] not in sent]
    out = {"day": day, "posted": [], "skipped": sorted(sent), "failed": [], "drafts": drafts}
    creds = credentials()
    if dry_run or not creds:
        out["note"] = "dry run" if dry_run else "RRSRCH_X_* are not set; nothing posted"
        return out
    post = post or (lambda url, **kw: httpx.post(url, timeout=30, **kw))

    def send(body: dict) -> tuple[str | None, str | None]:
        """The new post's id, or why it failed."""
        try:
            r = post(ENDPOINT, json=body, headers={"Authorization": oauth_header("POST", ENDPOINT, creds),
                                                   "Content-Type": "application/json"})
            tid = (r.json().get("data") or {}).get("id") if r.status_code in (200, 201) else None
            return tid, None if tid else f"HTTP {r.status_code}: {r.text[:200]}"
        except (httpx.HTTPError, ValueError) as e:
            return None, str(e)[:200]

    for d in drafts:
        tid, err = send({"text": d["text"]})
        if not tid:
            out["failed"].append({"kind": d["kind"], "error": err})
            continue
        conn.execute("INSERT INTO x_posts (week, kind, ref, tweet_id, text) VALUES (%s, %s, %s, %s, %s)",
                     (day, d["kind"], d["ref"], tid, d["text"]))
        conn.commit()
        posted = {"kind": d["kind"], "tweet_id": tid}
        last = tid
        for n, reply in enumerate(d.get("replies", []), 1):
            rid, err = send({"text": reply, "reply": {"in_reply_to_tweet_id": last}})
            if not rid:
                out["failed"].append({"kind": f"{d['kind']} reply {n}", "error": err})
                break
            posted.setdefault("replies", []).append(rid)
            last = rid
        out["posted"].append(posted)
    return out
