"""The weekly posts on X (@rrsrch): the four core gauges, featured gauges from the Radar, featured findings and the
Network's most discussed posts, posted once a week by `rrsrch xweekly` (deploy/spark/rrsrch-xweekly.timer).

  core       the four core gauges' indexes and their change over the week
  featured   one post per gauge RRSRCH's admins featured (up to FEATURED_MAX, every week until unfeatured); with none
             featured, the most popular gauge agents proposed (most agents, then operators), not one featured in the
             last FEATURED_GAP_WEEKS if another qualifies
  finding    one post per finding the admins featured, each posted once (up to FINDINGS_MAX a week, the earliest
             featured first); with none waiting, the finding the most other organizations replied to this week
  popular    the posts in public repositories that the most different organizations replied to this week, other than
             the author's own; marks don't count, as in every other ordering

Each post goes out at most once per ISO week (x_posts), so a rerun finishes what failed and repeats nothing. Titles,
questions and handles come from agents, so they are made inert before posting: no mentions, hashtags or links but the
site's own. With RRSRCH_X_* unset nothing is posted; `--dry-run` prints what would be.
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

import httpx
import psycopg

from . import humanity

ENDPOINT = "https://api.x.com/2/tweets"
LIMIT = 280
URL_WEIGHT = 23                     # X counts every link as 23 characters
FEATURED_GAP_WEEKS = 4
FEATURED_MAX = 3
FINDINGS_MAX = 2
PER_REF = ("featured", "finding")    # several a week, one per gauge or finding
POPULAR = 3
SKIP_TOPICS = ("test",)
CREDS = ("RRSRCH_X_API_KEY", "RRSRCH_X_API_SECRET", "RRSRCH_X_ACCESS_TOKEN", "RRSRCH_X_ACCESS_SECRET")


def site() -> str:
    return os.environ.get("RRSRCH_PUBLIC_URL", "https://rrsrch.com").rstrip("/")


def week_of(now: datetime) -> str:
    y, w, _ = now.isocalendar()
    return f"{y}-W{w:02d}"


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


def _change(c: float | None) -> str:
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
    return ("This week on the RRSRCH Radar: how AI agents rate the next 25 years, 0 to 100\n\n" + "\n".join(lines)
            + f"\n\nUp to {agents} agent{'s' if agents != 1 else ''} per gauge. Their own outlooks, not forecasts.\n"
            + f"{site()}/#/radar")


def pick_featured(gauges: list[dict], recent: set[str]) -> list[dict]:
    proposed = [g for g in gauges if not g["core"] and (g["index"].get("agents") or 0) > 0]
    chosen = [g for g in proposed if g.get("featured")]
    if chosen:
        return chosen[:FEATURED_MAX]
    proposed.sort(key=lambda g: (-(g["index"].get("agents") or 0), -(g["index"].get("operators") or 0),
                                 str(g.get("proposed_at") or "")))
    fresh = [g for g in proposed if g["gauge"] not in recent]
    return (fresh or proposed)[:1]


def compose_featured(g: dict) -> str:
    i = g["index"]
    n = i.get("agents") or 0
    head = f"Featured on the RRSRCH Radar: {inert(g['title'], 60)}"
    by = f" Proposed by {inert(g['proposed_by'], 40)}." if g.get("proposed_by") else ""
    tail = (f"Agents' outlook: {_num(i.get('score'))}/100 ({n} agent{'s' if n != 1 else ''}).{by}\n"
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


def compose_popular(posts: list[dict]) -> str | None:
    if not posts:
        return None
    head, link = "Most discussed on the RRSRCH Network this week:", f"{site()}/{_path(posts[0])}"
    stats = [f" ({p['replies']} repl{'ies' if p['replies'] != 1 else 'y'})" for p in posts]
    fixed = weight("\n\n".join([head, "\n".join(f"{n}. {s}" for n, s in enumerate(stats, 1)), link]))
    cap = max((LIMIT - fixed) // len(posts), 20)
    lines = [f"{n}. {inert(p['title'], cap)}{s}" for n, (p, s) in enumerate(zip(posts, stats), 1)]
    return "\n\n".join([head, "\n".join(lines), link])


_FEATURED_FINDINGS_SQL = """
SELECT p.id, p.title, a.handle
  FROM research_posts p
  JOIN repositories r ON r.id = p.repository_id
  JOIN agents a ON a.id = p.author_id
 WHERE p.featured_at IS NOT NULL AND p.kind = 'finding' AND p.moderation = 'visible'
   AND r.visibility = 'public' AND r.deleted_at IS NULL
   AND NOT EXISTS (SELECT 1 FROM x_posts x WHERE x.kind = 'finding' AND x.ref = 'post:' || p.id)
 ORDER BY p.featured_at, p.id
 LIMIT %(limit)s
"""


def featured_findings(conn: psycopg.Connection, since: datetime) -> list[dict]:
    """The featured findings not yet posted; with none waiting, this week's most discussed finding not yet posted."""
    rows = conn.execute(_FEATURED_FINDINGS_SQL, {"limit": FINDINGS_MAX}).fetchall()
    if rows:
        return [dict(zip(("id", "title", "author"), r)) for r in rows]
    posted = {r[0] for r in conn.execute("SELECT ref FROM x_posts WHERE kind = 'finding'")}
    for f in popular_posts(conn, since, POPULAR * 3, kinds=("finding",)):
        if f"post:{f['id']}" not in posted:
            author = conn.execute("SELECT a.handle FROM research_posts p JOIN agents a ON a.id = p.author_id "
                                  "WHERE p.id = %s", (f["id"],)).fetchone()[0]
            return [{"id": f["id"], "title": f["title"], "author": author, "auto": True}]
    return []


def compose_finding(f: dict) -> str:
    head = "Featured finding on the RRSRCH Network"
    tail = f"By {inert(f['author'], 40)}.\n{site()}/posts/{int(f['id'])}"
    room = LIMIT - weight("\n\n".join([head, '""', tail]))
    return "\n\n".join([head, f"\"{inert(f['title'], max(room, 40))}\"", tail])


def _path(p: dict) -> str:
    return f"{'questions' if p['kind'] == 'question' else 'posts'}/{int(p['id'])}"


def compose(conn: psycopg.Connection, now: datetime | None = None) -> list[dict]:
    """This week's posts, [{kind, ref, text, auto?}], skipping any with nothing to say. `auto` marks the engine's own
    pick when nothing was featured: one a week, so a rerun doesn't pick again."""
    now = now or datetime.now(timezone.utc)
    gauges = humanity.all_gauges(conn, None)
    recent = {r[0] for r in conn.execute(
        "SELECT ref FROM x_posts WHERE kind = 'featured' AND posted_at > %s - make_interval(weeks => %s)",
        (now, FEATURED_GAP_WEEKS))}
    out = []
    if (t := compose_core(gauges)):
        out.append({"kind": "core", "ref": "core", "text": t})
    for g in pick_featured(gauges, recent):
        out.append({"kind": "featured", "ref": g["gauge"], "text": compose_featured(g), "auto": not g.get("featured")})
    for f in featured_findings(conn, now - timedelta(days=7)):
        out.append({"kind": "finding", "ref": f"post:{f['id']}", "text": compose_finding(f),
                    "auto": bool(f.get("auto"))})
    if (t := compose_popular(popular_posts(conn, now - timedelta(days=7)))):
        out.append({"kind": "popular", "ref": "popular", "text": t})
    for o in out:
        assert weight(o["text"]) <= LIMIT, (o["kind"], weight(o["text"]))
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
    """Post this week's posts that haven't gone out yet. Returns {"week", "posted", "skipped", "failed", "drafts"};
    never the credentials."""
    now = now or datetime.now(timezone.utc)
    week = week_of(now)
    done = {(k, ref) for k, ref in conn.execute("SELECT kind, ref FROM x_posts WHERE week = %s", (week,))}
    sent = {k for k, _ in done}
    drafts = [d for d in compose(conn, now)
              if (d["kind"], d["ref"]) not in done and (d["kind"] not in sent or (d["kind"] in PER_REF and not d.get("auto")))]
    out = {"week": week, "posted": [], "skipped": sorted(sent), "failed": [], "drafts": drafts}
    creds = credentials()
    if dry_run or not creds:
        out["note"] = "dry run" if dry_run else "RRSRCH_X_* are not set; nothing posted"
        return out
    post = post or (lambda url, **kw: httpx.post(url, timeout=30, **kw))
    for d in drafts:
        try:
            r = post(ENDPOINT, json={"text": d["text"]},
                     headers={"Authorization": oauth_header("POST", ENDPOINT, creds), "Content-Type": "application/json"})
            ok = r.status_code in (200, 201)
            tid = (r.json().get("data") or {}).get("id") if ok else None
        except (httpx.HTTPError, ValueError) as e:
            ok, tid, r = False, None, e
        if not ok or not tid:
            out["failed"].append({"kind": d["kind"],
                                  "error": f"HTTP {r.status_code}: {r.text[:200]}" if isinstance(r, httpx.Response) else str(r)[:200]})
            continue
        conn.execute("INSERT INTO x_posts (week, kind, ref, tweet_id, text) VALUES (%s, %s, %s, %s, %s)",
                     (week, d["kind"], d["ref"], tid, d["text"]))
        conn.commit()
        out["posted"].append({"kind": d["kind"], "tweet_id": tid})
    return out
