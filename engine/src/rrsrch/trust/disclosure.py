"""Embargoes and the disclosure record: holding a verified finding back while the people affected are told.

A claim in a private repository can be embargoed until a date. While any of its claims is under an active embargo
the repository can't be made public (knowledge/repos.py), so a finding can't be published before its disclosure is
done. The date is the publication deadline agreed or announced; once it passes the embargo no longer holds anything
back. A maintainer can extend an embargo or lift it early; each change is audited.

The disclosure record is what happened outside RRSRCH: notices sent, replies, a maintainer confirming or disputing
the finding, fixes and advisories published, corrections submitted upstream and what became of them. Entries are
append-only; a mistaken one is corrected by a later entry that supersedes it. They are evidence recorded next to
the claim's own evidence, and they never change its review state: a maintainer's confirmation doesn't overrule
evidence anyone can reproduce, and a dispute doesn't erase it. Any disagreement stays on the record.

Message bodies are untrusted text, stored and shown as received.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import psycopg

from ..identity.access import Action, Principal
from . import audit
from .merge import Refused, require

KINDS = ("notice_sent", "reply_received", "maintainer_confirmed", "maintainer_disputed", "fix_released",
         "advisory_published", "correction_submitted", "correction_accepted", "correction_rejected", "note")
MAX_EMBARGO = timedelta(days=366)
EVENTS_PER_HOUR = 60


def _claim(conn, claim_id: int, lock: bool = False) -> tuple[int, str]:
    row = conn.execute("SELECT c.repository_id, r.visibility FROM claims c JOIN repositories r ON r.id = c.repository_id "
                       "WHERE c.id = %s" + (" FOR UPDATE OF c, r" if lock else ""), (claim_id,)).fetchone()
    if row is None:
        raise Refused(404, "not found")
    return row


def active_embargo(conn, claim_id: int) -> dict | None:
    row = conn.execute(
        "SELECT e.id, e.until, e.reason, a.handle, e.set_at FROM claim_embargoes e JOIN agents a ON a.id = e.set_by "
        "WHERE e.claim_id = %s AND e.lifted_at IS NULL AND e.until > now()", (claim_id,)).fetchone()
    return dict(zip(("id", "until", "reason", "set_by", "set_at"), row)) if row else None


def embargoed_in(conn, repository_id: int) -> list[tuple[int, datetime]]:
    """(claim id, until) for every claim in the repository still under an active embargo."""
    return conn.execute(
        "SELECT e.claim_id, e.until FROM claim_embargoes e JOIN claims c ON c.id = e.claim_id "
        "WHERE c.repository_id = %s AND e.lifted_at IS NULL AND e.until > now() ORDER BY e.claim_id",
        (repository_id,)).fetchall()


def set_embargo(conn: psycopg.Connection, p: Principal | None, claim_id: int, until: datetime, reason: str) -> dict:
    """Embargo a claim until `until`, or move the date of its active embargo. Maintainers only."""
    repo_id, visibility = _claim(conn, claim_id, lock=True)
    require(conn, p, Action.MAINTAIN, repo_id)
    if visibility != "private":
        raise Refused(409, "the claim is in a public repository: it is already published, so there is nothing to "
                           "hold back")
    if until.tzinfo is None:
        raise Refused(400, "until needs a timezone")
    now = datetime.now(timezone.utc)
    if until <= now:
        raise Refused(400, "until must be in the future")
    if until - now > MAX_EMBARGO:
        raise Refused(400, "an embargo lasts at most a year; extend it later if disclosure needs longer")
    reason = " ".join(reason.split())
    if not 1 <= len(reason) <= 500:
        raise Refused(400, "reason must be 1-500 characters")
    current = conn.execute("SELECT id, until FROM claim_embargoes WHERE claim_id = %s AND lifted_at IS NULL "
                           "FOR UPDATE", (claim_id,)).fetchone()
    if current is not None and current[1] <= now:
        # a past embargo stays as history; this is a new one
        conn.execute("UPDATE claim_embargoes SET lifted_at = until, lifted_by = %s, lift_note = 'the date passed' "
                     "WHERE id = %s", (p.agent_id, current[0]))
        current = None
    if current is None:
        conn.execute("INSERT INTO claim_embargoes (claim_id, until, reason, set_by) VALUES (%s, %s, %s, %s)",
                     (claim_id, until, reason, p.agent_id))
        action, detail = "claim.embargo", {"until": until.isoformat()}
    else:
        conn.execute("UPDATE claim_embargoes SET until = %s, reason = %s WHERE id = %s", (until, reason, current[0]))
        action, detail = "claim.embargo_changed", {"from": current[1].isoformat(), "until": until.isoformat()}
    audit.append(conn, action, f"claim:{claim_id}", actor_id=p.agent_id, repository_id=repo_id,
                 detail=detail | {"claim_id": claim_id, "reason": reason[:200]})
    return active_embargo(conn, claim_id)


def lift_embargo(conn: psycopg.Connection, p: Principal | None, claim_id: int, note: str = "") -> None:
    repo_id, _ = _claim(conn, claim_id, lock=True)
    require(conn, p, Action.MAINTAIN, repo_id)
    note = " ".join(note.split())[:500]
    row = conn.execute("UPDATE claim_embargoes SET lifted_at = now(), lifted_by = %s, lift_note = %s "
                       "WHERE claim_id = %s AND lifted_at IS NULL RETURNING id", (p.agent_id, note, claim_id)).fetchone()
    if row is None:
        raise Refused(409, "the claim has no embargo to lift")
    audit.append(conn, "claim.embargo_lifted", f"claim:{claim_id}", actor_id=p.agent_id, repository_id=repo_id,
                 detail={"claim_id": claim_id, "note": note[:200]})


def record(conn: psycopg.Connection, p: Principal | None, claim_id: int, kind: str, party: str, occurred_at: datetime,
           summary: str, *, channel: str = "", reference: str = "", url: str | None = None, body: str = "",
           supersedes: int | None = None) -> int:
    """Add an entry to the claim's disclosure record. Maintainers of the claim's repository only."""
    repo_id, _ = _claim(conn, claim_id)
    require(conn, p, Action.MAINTAIN, repo_id)
    if kind not in KINDS:
        raise Refused(400, f"kind is one of {', '.join(KINDS)}")
    if occurred_at.tzinfo is None:
        raise Refused(400, "occurred_at needs a timezone")
    if occurred_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise Refused(400, "occurred_at is in the future: record things once they have happened")
    if url is not None and not url.startswith("https://"):
        raise Refused(400, "url must be an https:// link")
    if supersedes is not None and not conn.execute(
            "SELECT 1 FROM disclosure_events WHERE id = %s AND claim_id = %s", (supersedes, claim_id)).fetchone():
        raise Refused(400, f"entry {supersedes} is not in this claim's disclosure record")
    if conn.execute("SELECT count(*) FROM disclosure_events WHERE recorded_by = %s "
                    "AND created_at > now() - interval '1 hour'", (p.agent_id,)).fetchone()[0] >= EVENTS_PER_HOUR:
        raise Refused(429, "too many disclosure entries in the last hour")
    eid = conn.execute(
        "INSERT INTO disclosure_events (claim_id, kind, party, channel, reference, url, occurred_at, summary, body, "
        "supersedes, recorded_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (claim_id, kind, party.strip(), channel.strip(), reference.strip(), url, occurred_at, summary.strip(), body,
         supersedes, p.agent_id)).fetchone()[0]
    audit.append(conn, "disclosure.record", f"claim:{claim_id}", actor_id=p.agent_id, repository_id=repo_id,
                 detail={"claim_id": claim_id, "entry": eid, "kind": kind, "party": party[:100],
                         "reference": reference[:100], "supersedes": supersedes})
    return eid


def record_of(conn, claim_id: int) -> list[dict]:
    """The claim's disclosure record, oldest first. Callers check the claim is readable."""
    cols = ("id", "kind", "party", "channel", "reference", "url", "occurred_at", "summary", "body", "supersedes",
            "recorded_by", "created_at")
    rows = [dict(zip(cols, r)) for r in conn.execute(
        "SELECT e.id, e.kind, e.party, e.channel, e.reference, e.url, e.occurred_at, e.summary, e.body, e.supersedes, "
        "a.handle, e.created_at FROM disclosure_events e JOIN agents a ON a.id = e.recorded_by "
        "WHERE e.claim_id = %s ORDER BY e.occurred_at, e.id", (claim_id,))]
    replaced = {r["supersedes"] for r in rows if r["supersedes"]}
    for r in rows:
        r["superseded"] = r["id"] in replaced
    return rows


def embargo_history(conn, claim_id: int) -> list[dict]:
    cols = ("until", "reason", "set_by", "set_at", "lifted_at", "lifted_by", "lift_note")
    return [dict(zip(cols, r)) for r in conn.execute(
        "SELECT e.until, e.reason, s.handle, e.set_at, e.lifted_at, l.handle, e.lift_note FROM claim_embargoes e "
        "JOIN agents s ON s.id = e.set_by LEFT JOIN agents l ON l.id = e.lifted_by WHERE e.claim_id = %s "
        "ORDER BY e.id", (claim_id,))]
