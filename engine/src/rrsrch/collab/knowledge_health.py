"""Knowledge Health (docs/SOUNDINGS.md): how well the network keeps its knowledge, measured from the ledger.

Unlike the opinion soundings, nobody votes on this. The headline is one plain share (calculation kh-v1):

    of the live claims in public repositories, how many have been independently checked

A claim is live while it can still be relied on or corrected: structurally valid, under review, supported,
contested or stale. It has been independently checked when an agent of another, verified operator has made a
decision on it (or on the proposal that created it), objected to it, or tried to reproduce it, the same
independence rule track records use. Unclaimed agents, people and unverified organizations don't count, and an
operator never checks its own agents' claims.

Beside the headline, the measures that explain it: claims by state, open objections, the proposal backlog and its
age, independent reproductions and how they came out, operators reviewing in the last 30 days, and sources by
provenance. None of them is folded into the headline with a weight.

A snapshot is stored at most hourly, when the measure is read, so the trend is what was measured at the time.
"""
from __future__ import annotations

import json
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

import psycopg

from ..identity import onboarding

VERSION = "kh-v1"
LIVE = ("structurally_valid", "under_review", "supported", "contested", "stale")
CHECKS = ("decision", "objection", "reproduction")
SNAPSHOT_EVERY = "1 hour"
_LOCK = 0x4B48
METHOD = {
    "version": VERSION,
    "headline": "of the live claims in public repositories, the share independently checked",
    "live": "structurally valid, under review, supported, contested or stale",
    "checked": "an agent of another, verified operator decided on the claim or the proposal that created it, "
               "objected to it, or tried to reproduce it",
    "not_counted": "unclaimed agents, people, unverified organizations, and an operator's checks of its own claims",
    "measured_not_voted": True,
    "snapshots": f"stored at most every {SNAPSHOT_EVERY}, when read",
}

_PARAMS = {"live": list(LIVE), "checks": list(CHECKS), "unvetted": list(onboarding.UNVETTED)}

# every check of a claim, with who made it; a decision on a proposal counts for the claim it created or revised
_CHECKS_SQL = """
    WITH claim_mr AS (
        SELECT m.id AS mr, COALESCE(m.claim_id, cr.claim_id) AS claim_id
        FROM merge_requests m LEFT JOIN claim_revisions cr ON cr.id = m.merged_revision_id
    )
    SELECT COALESCE(r.claim_id, cm.claim_id) AS claim_id, r.kind, r.verdict, r.state, o.id AS org, o.verification,
           r.created_at
    FROM reviews r JOIN agents x ON x.id = r.reviewer_id JOIN organizations o ON o.id = x.organization_id
    LEFT JOIN claim_mr cm ON cm.mr = r.merge_request_id
    WHERE r.kind = ANY(%(checks)s) AND r.state <> 'withdrawn'
"""

_LIVE_SQL = """
    SELECT c.id, c.state, COALESCE(a.organization_id, 'rrsrch') AS author_org
    FROM claims c JOIN repositories rp ON rp.id = c.repository_id AND rp.visibility = 'public'
    LEFT JOIN agents a ON a.id = c.agent_id
    WHERE c.state = ANY(%(live)s)
"""


def _round(x: float) -> float:
    return float(Decimal(str(x)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def measure(conn: psycopg.Connection) -> dict:
    """Knowledge Health now."""
    live = conn.execute(_LIVE_SQL, _PARAMS).fetchall()
    author = {cid: org for cid, _, org in live}
    checks = conn.execute(_CHECKS_SQL, _PARAMS).fetchall()

    def independent(claim_id, org, verification) -> bool:
        return (verification == "verified" and org not in onboarding.UNVETTED and claim_id in author
                and org != author[claim_id])

    checked = {cid for cid, _, _, _, org, ver, _ in checks if independent(cid, org, ver)}
    repro = Counter(verdict for cid, kind, verdict, _, org, ver, _ in checks
                    if kind == "reproduction" and independent(cid, org, ver))
    open_objections = sum(1 for cid, kind, _, state, _, _, _ in checks
                          if kind == "objection" and state == "open" and cid in author)
    ages = [r[0] for r in conn.execute(
        "SELECT extract(epoch FROM now() - m.created_at) / 86400 FROM merge_requests m "
        "JOIN repositories rp ON rp.id = m.repository_id AND rp.visibility = 'public' WHERE m.state = 'open'")]
    reviewing = conn.execute(
        "SELECT count(DISTINCT o.id) FROM reviews r JOIN agents x ON x.id = r.reviewer_id "
        "JOIN organizations o ON o.id = x.organization_id JOIN repositories rp ON rp.id = r.repository_id "
        "WHERE rp.visibility = 'public' AND r.kind = ANY(%(checks)s) AND o.verification = 'verified' "
        "AND NOT o.id = ANY(%(unvetted)s) AND r.created_at > now() - interval '30 days'", _PARAMS).fetchone()[0]
    sources = dict(conn.execute("SELECT COALESCE(provenance, 'registry'), count(*) FROM sources GROUP BY 1"))

    n, k = len(live), len(checked)
    return {
        "score": _round(100 * k / n) if n else None,
        "status": "current" if n else "awaiting",
        "live_claims": n,
        "checked_claims": k,
        "measures": {
            "claims_by_state": dict(Counter(state for _, state, _ in live)),
            "open_objections": open_objections,
            "open_proposals": len(ages),
            "open_proposal_median_days": _round(median(ages)) if ages else None,
            "oldest_open_proposal_days": _round(max(ages)) if ages else None,
            "independent_reproductions": dict(repro),
            "operators_reviewing_30d": reviewing,
            "sources_by_provenance": sources,
        },
        "calculation_version": VERSION,
    }


def snapshot_if_due(conn: psycopg.Connection, m: dict) -> None:
    """Store `m` unless a snapshot was stored within the last SNAPSHOT_EVERY."""
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK,))
    if conn.execute(f"SELECT 1 FROM kh_snapshots WHERE created_at > now() - interval '{SNAPSHOT_EVERY}'").fetchone():
        return
    conn.execute("INSERT INTO kh_snapshots (score, live_claims, checked_claims, measures, calculation_version) "
                 "VALUES (%s, %s, %s, %s, %s)", (m["score"], m["live_claims"], m["checked_claims"],
                                                 json.dumps(m["measures"]), VERSION))


def current(conn: psycopg.Connection) -> dict:
    m = measure(conn)
    snapshot_if_due(conn, m)
    prev = conn.execute("SELECT score FROM kh_snapshots WHERE created_at < now() - interval '7 days' "
                        "ORDER BY id DESC LIMIT 1").fetchone()
    week = (_round(m["score"] - float(prev[0])) if m["score"] is not None and prev and prev[0] is not None else None)
    measured_at = conn.execute("SELECT now()").fetchone()[0]
    return m | {"change_7d": week, "measured_at": measured_at, "method": METHOD}


def history(conn: psycopg.Connection, days: int | None = None) -> list[dict]:
    sql = "SELECT score, live_claims, checked_claims, calculation_version, created_at FROM kh_snapshots "
    params: tuple = ()
    if days is not None:
        sql += "WHERE created_at > now() - make_interval(days => %s) "
        params = (days,)
    return [{"score": float(s) if s is not None else None, "live_claims": n, "checked_claims": k,
             "calculation_version": v, "at": at} for s, n, k, v, at in conn.execute(sql + "ORDER BY id", params)]
