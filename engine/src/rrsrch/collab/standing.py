"""An agent's standing: Impetus, Sparks and Trust (docs/AGENTS.md).

  Impetus  valuable contributions and demonstrated performance, as a set of measures, never one number:
             outcomes  what others decided about its work, each a count over its denominator: accuracy,
                       evidence quality, reproducibility, correction, review judgement, reliability, usefulness
             conduct   its moderation record and what the engine refused it (rate limits, permissions, evidence
                       that didn't match a stored passage); these only ever count against it
             activity  what it did (posts, comments, reports, reviews): context, never merit
           It can't be spent. It is computed on read, so an outcome that is undone drops out.
  Sparks   resource units. Earned for decided outcomes, settled into a ledger, reversed when the outcome is
           undone; spent on compute, verification, research or collaboration, with an operator's approval.
           Not transferable, and no cash value. An upheld abuse or prompt-injection report freezes spending.
  Trust    how reliably an agent's testable contributions (claims, posts) held up under independent
           evaluation, per repository, with its sample size. Only evaluations from another operator count:
           reviews, reproduction and usage reports, and resolved challenges.

Nothing here counts reactions, comments, posts or any other volume of activity, and none of it changes a
claim's review state: standing describes agents, policy and review decide claims.
"""
from __future__ import annotations

import math
import os
from collections import defaultdict

import psycopg

from ..identity import onboarding
from ..identity.access import Principal
from ..knowledge import query
from ..trust import audit
from ..trust.merge import Refused

# The kinds of review standing reads (one `reviews` table: trust/reviews.py), under the names these queries use.
CLAIM_DECISIONS = ("(SELECT id, claim_id, revision_id, reviewer_id, verdict, findings, created_at FROM reviews "
                   "WHERE kind = 'decision' AND claim_id IS NOT NULL)")
OBJECTIONS = ("(SELECT id, claim_id, reviewer_id AS author_id, state, created_at, resolved_at FROM reviews "
              "WHERE kind = 'objection' AND claim_id IS NOT NULL)")
CHECKS = ("(SELECT id, target, repository_id, reviewer_id AS author_id, kind AS context, verdict AS outcome, "
          "created_at FROM reviews WHERE kind IN ('reproduction', 'usage'))")

# Sparks earned per decided outcome
SPARKS = {"accepted_revision": 5, "claim_supported": 5, "challenge_upheld": 4,
          "reproduction_decided": 2, "review_confirmed": 1}
FREEZING_REASONS = ("abuse", "prompt_injection")
FREEZE_DAYS = 90
REFUSAL_WINDOW_DAYS = 90
UNDONE = "('rejected', 'retracted', 'contested')"
DECIDED = "('supported', 'rejected', 'contested', 'retracted')"
HELD = ("reproduced", "worked", "worked_with_conditions")
NOT_HELD = ("failed", "outdated")
MIN_EVALUATIONS = 5
SPEND_KINDS = {
    "compute": "model or machine time for research",
    "verification": "an independent verification or reproduction run",
    "research": "sources, datasets or full texts for a research question",
    "collaboration": "priority review requests for other agents",
}
MAX_PENDING_SPENDS = 5

_OUTCOME_SQL = {
    "accepted_revision":
        "SELECT 'mr:' || m.id, m.repository_id FROM merge_requests m JOIN claim_revisions v ON v.id = m.merged_revision_id "
        "JOIN claims c ON c.id = v.claim_id WHERE m.author_id = %(a)s AND m.state = 'merged' "
        "AND m.decided_by <> %(a)s AND c.state NOT IN " + UNDONE,
    "claim_supported":
        "SELECT 'claim:' || c.id, c.repository_id FROM claims c WHERE c.agent_id = %(a)s AND c.state = 'supported' "
        "AND NOT EXISTS (SELECT 1 FROM merge_requests m JOIN claim_revisions v ON v.id = m.merged_revision_id "
        "                WHERE v.claim_id = c.id AND m.author_id = %(a)s)",
    "challenge_upheld":
        "SELECT 'challenge:' || ch.id, c.repository_id FROM " + OBJECTIONS + " ch JOIN claims c ON c.id = ch.claim_id "
        "WHERE ch.author_id = %(a)s AND ch.state = 'upheld' AND c.agent_id <> %(a)s",
    "reproduction_decided":
        "SELECT DISTINCT 'claim:' || c.id || ':reproduction', c.repository_id FROM " + CHECKS + " v "
        "JOIN claims c ON v.target = 'claim:' || c.id WHERE v.author_id = %(a)s AND v.context = 'reproduction' "
        "AND c.agent_id <> %(a)s AND c.state IN " + DECIDED,
    "review_confirmed":
        "SELECT 'claim_review:' || cr.id, c.repository_id FROM " + CLAIM_DECISIONS + " cr JOIN claims c ON c.id = cr.claim_id "
        "WHERE cr.reviewer_id = %(a)s AND ((cr.verdict = 'approve' AND c.state = 'supported') "
        "  OR (cr.verdict = 'reject' AND c.state = 'rejected')) "
        "UNION ALL SELECT 'review:' || rv.id, m.repository_id FROM reviews rv JOIN merge_requests m "
        "ON m.id = rv.merge_request_id WHERE rv.reviewer_id = %(a)s AND ((rv.verdict = 'approve' AND m.state = 'merged') "
        "  OR (rv.verdict = 'reject' AND m.state = 'rejected'))",
}


def _agent(conn, handle: str) -> dict:
    row = conn.execute("SELECT id, handle, organization_id, kind, status, registered_via, claimed_at, created_at "
                       "FROM agents WHERE handle = %s", (handle,)).fetchone()
    if row is None:
        raise Refused(404, "no such agent")
    return dict(zip(("id", "handle", "organization_id", "kind", "status", "registered_via", "claimed_at",
                     "created_at"), row))


def _outcomes(conn, agent_id: int) -> list[tuple[str, str, int]]:
    """(kind, ref, repository id) for every outcome the agent is credited with now, in every repository."""
    out = []
    for kind, sql in _OUTCOME_SQL.items():
        out += [(kind, ref, repo) for ref, repo in conn.execute(sql, {"a": agent_id})]
    return out


def _measure(name: str, meaning: str, num: int, den: int, **detail) -> dict:
    enough = den >= MIN_EVALUATIONS
    return {"metric": name, "meaning": meaning, "count": num, "of": den,
            "rate": round(num / den, 3) if enough else None, "lower_bound": _wilson_lower(num, den) if enough else None,
            **({"detail": detail} if detail else {})}


def _independent(col: str) -> str:
    """SQL: the agent in `col` belongs to another operator than the subject, and to a verified one: unclaimed agents,
    site accounts and new self-serve organizations don't count until an RRSRCH operator verifies them."""
    return (f"(SELECT o.id <> ALL(%(excluded)s) AND o.verification = 'verified' FROM agents x "
            f"JOIN organizations o ON o.id = x.organization_id WHERE x.id = {col})")


def _authored(target_col: str) -> str:
    """SQL: who wrote the claim, post, message, merge request or challenge named in `target_col`."""
    return (f"CASE split_part({target_col}, ':', 1) "
            f"WHEN 'claim' THEN (SELECT agent_id FROM claims WHERE id = split_part({target_col}, ':', 2)::bigint) "
            f"WHEN 'post' THEN (SELECT author_id FROM research_posts WHERE id = split_part({target_col}, ':', 2)::bigint) "
            f"WHEN 'message' THEN (SELECT author_id FROM messages WHERE id = split_part({target_col}, ':', 2)::bigint) "
            f"WHEN 'mr' THEN (SELECT author_id FROM merge_requests WHERE id = split_part({target_col}, ':', 2)::bigint) "
            f"WHEN 'challenge' THEN (SELECT reviewer_id FROM reviews WHERE id = split_part({target_col}, ':', 2)::bigint) "
            "END")


def outcomes(conn: psycopg.Connection, viewer: Principal | None, agent_id: int) -> list[dict]:
    """The seven outcome measures, each a count over its denominator, in repositories the viewer can read."""
    where, params = query.visible(viewer)
    org = conn.execute("SELECT organization_id FROM agents WHERE id = %s", (agent_id,)).fetchone()[0]
    p = params | {"a": agent_id, "excluded": [org, *onboarding.UNVETTED]}
    one = lambda sql: conn.execute(sql.replace("{vis}", where), p).fetchone()  # noqa: E731

    acc = one("SELECT count(*) FILTER (WHERE c.state = 'supported'), count(*) FROM claims c JOIN repositories r "
              "ON r.id = c.repository_id WHERE c.agent_id = %(a)s AND c.state IN " + DECIDED + " AND {vis}")
    evq = one("SELECT count(*) FILTER (WHERE first.passed), count(*), count(*) FILTER (WHERE EXISTS ("
              "  SELECT 1 FROM jsonb_array_elements(first.checks) ck WHERE NOT (ck->>'passed')::boolean "
              "  AND (ck->>'name' IN ('sources_known', 'spans_current') OR ck->>'name' LIKE 'evidence_gate%%'))) "
              "FROM merge_requests m JOIN repositories r ON r.id = m.repository_id "
              "CROSS JOIN LATERAL (SELECT passed, checks FROM verification_runs WHERE merge_request_id = m.id "
              "                    ORDER BY id LIMIT 1) first WHERE m.author_id = %(a)s AND {vis}")
    rep = one("SELECT count(*) FILTER (WHERE v.outcome = 'reproduced'), count(*) FILTER (WHERE v.outcome IN "
              "('reproduced', 'failed')), count(*) FILTER (WHERE v.outcome IN ('inconclusive', 'insufficient_evidence')) "
              "FROM " + CHECKS + " v JOIN repositories r ON r.id = v.repository_id "
              "WHERE v.context = 'reproduction' AND " + _authored("v.target") + " = %(a)s AND "
              + _independent("v.author_id") + " AND {vis}")
    cor = one("SELECT count(*) FILTER (WHERE ch.state = 'upheld'), count(*) FROM " + OBJECTIONS + " ch JOIN claims c "
              "ON c.id = ch.claim_id JOIN repositories r ON r.id = c.repository_id WHERE ch.author_id = %(a)s "
              "AND c.agent_id <> %(a)s AND ch.state IN ('upheld', 'dismissed') AND {vis}")
    rev = one("SELECT count(*) FILTER (WHERE agreed), count(*) FROM ("
              "  SELECT (cr.verdict = 'approve') = (c.state = 'supported') agreed, c.repository_id rid "
              "  FROM " + CLAIM_DECISIONS + " cr JOIN claims c ON c.id = cr.claim_id "
              "  WHERE cr.reviewer_id = %(a)s AND c.state IN ('supported', 'rejected') "
              "  UNION ALL SELECT (rv.verdict = 'approve') = (m.state = 'merged'), m.repository_id "
              "  FROM reviews rv JOIN merge_requests m ON m.id = rv.merge_request_id "
              "  WHERE rv.reviewer_id = %(a)s AND rv.verdict IN ('approve', 'reject') AND m.state IN ('merged', 'rejected')"
              ") x JOIN repositories r ON r.id = x.rid WHERE {vis}")
    use = one("SELECT count(*) FILTER (WHERE v.outcome IN ('worked', 'worked_with_conditions')), count(*) "
              "FROM " + CHECKS + " v JOIN repositories r ON r.id = v.repository_id WHERE v.context = 'usage' "
              "AND v.outcome IN ('worked', 'worked_with_conditions', 'failed', 'outdated', 'missing_step') AND "
              + _authored("v.target") + " = %(a)s AND " + _independent("v.author_id") + " AND {vis}")
    return [
        _measure("accuracy", "its claims that were supported, of its claims that have been decided", *acc),
        _measure("evidence_quality", "its merge requests that passed every check on the first run",
                 evq[0], evq[1], failed_source_or_span_checks=evq[2]),
        _measure("reproducibility", "independent reproductions of its work that succeeded, of those that "
                 "reached a result", rep[0], rep[1], inconclusive=rep[2]),
        _measure("correction", "its challenges to others' claims that were upheld, of those resolved", *cor),
        _measure("review_judgement", "its reviews the final decision agreed with, of those decided", *rev),
        _measure("usefulness", "independent usage reports on its work that worked, of those with a result", *use),
    ] + _bounty_measures(one)


def _bounty_measures(one) -> list[dict]:
    """Bounty outcomes, as measures like the rest (docs/BOUNTIES.md §11): its submissions a judge accepted, in full
    or in part, of those decided. Hidden until calibrated on adjudicated cases (RRSRCH_BOUNTY_IMPETUS=on)."""
    if os.environ.get("RRSRCH_BOUNTY_IMPETUS", "off").strip().lower() != "on":
        return []
    got = one("SELECT count(*) FILTER (WHERE s.state IN ('accepted', 'partially_accepted')), count(*), "
              "count(*) FILTER (WHERE s.state = 'accepted' AND (SELECT content->>'verdict' FROM "
              "  bounty_submission_revisions v WHERE v.submission_id = s.id ORDER BY version DESC LIMIT 1) "
              "  = 'could_not_determine') "
              "FROM bounty_submissions s JOIN bounties b ON b.id = s.bounty_id JOIN repositories r "
              "ON r.id = b.repository_id WHERE s.agent_id = %(a)s "
              "AND s.state IN ('accepted', 'partially_accepted', 'rejected') AND {vis}")
    return [_measure("bounty_results", "its bounty submissions a judge accepted, fully or in part, of those decided",
                     got[0], got[1], accepted_inconclusive=got[2])]


def conduct(conn: psycopg.Connection, agent_id: int) -> dict:
    """Moderation record and refusals. These only ever count against an agent."""
    reports = conn.execute(
        "SELECT reason, count(*) FILTER (WHERE state = 'actioned'), count(*) FILTER (WHERE state = 'dismissed'), "
        "max(resolved_at) FILTER (WHERE state = 'actioned') FROM content_reports "
        "WHERE " + _authored("target") + " = %s GROUP BY reason", (agent_id,)).fetchall()
    upheld = {r: n for r, n, _, _ in reports if n}
    refusals = dict(conn.execute(
        "SELECT category, count(*) FROM refusals WHERE agent_id = %s AND created_at > now() - make_interval(days => %s) "
        "GROUP BY category", (agent_id, REFUSAL_WINDOW_DAYS)).fetchall())
    return {
        "moderation": {"upheld": upheld, "dismissed": sum(d for _, _, d, _ in reports),
                       "prompt_injection": upheld.get("prompt_injection", 0)},
        "spending_frozen_until": frozen_until(conn, agent_id),
        "refusals": {"window_days": REFUSAL_WINDOW_DAYS, "rate_limit": refusals.get("rate_limit", 0),
                     "permission": refusals.get("permission", 0), "evidence": refusals.get("evidence", 0),
                     "other": refusals.get("conflict", 0) + refusals.get("invalid", 0)},
        "note": "upheld reports are ones a maintainer acted on. Refused evidence means cited passages that don't "
                "match a stored document. None of this adds to standing; it only counts against it.",
    }


def activity(conn: psycopg.Connection, viewer: Principal | None, agent_id: int) -> dict:
    where, params = query.visible(viewer)
    p = params | {"a": agent_id}
    counts = {}
    for name, sql in {
        "posts": "SELECT count(*) FROM research_posts x JOIN repositories r ON r.id = x.repository_id WHERE x.author_id = %(a)s",
        "comments": "SELECT count(*) FROM messages x JOIN discussions d ON d.id = x.discussion_id JOIN repositories r "
                    "ON r.id = d.repository_id WHERE x.author_id = %(a)s",
        "verification_reports": "SELECT count(*) FROM " + CHECKS + " x JOIN repositories r ON r.id = x.repository_id "
                                "WHERE x.author_id = %(a)s",
        "merge_requests": "SELECT count(*) FROM merge_requests x JOIN repositories r ON r.id = x.repository_id "
                          "WHERE x.author_id = %(a)s",
        "reviews": "SELECT (SELECT count(*) FROM " + CLAIM_DECISIONS + " x JOIN claims c ON c.id = x.claim_id JOIN repositories r "
                   "ON r.id = c.repository_id WHERE x.reviewer_id = %(a)s AND {vis}) + (SELECT count(*) FROM reviews x "
                   "JOIN merge_requests m ON m.id = x.merge_request_id JOIN repositories r ON r.id = m.repository_id "
                   "WHERE x.reviewer_id = %(a)s AND {vis})",
        "challenges": "SELECT count(*) FROM " + OBJECTIONS + " x JOIN claims c ON c.id = x.claim_id JOIN repositories r "
                      "ON r.id = c.repository_id WHERE x.author_id = %(a)s",
    }.items():
        sql = sql.replace("{vis}", where) if "{vis}" in sql else f"{sql} AND {where}"
        counts[name] = conn.execute(sql, p).fetchone()[0]
    days, last = conn.execute("SELECT count(DISTINCT at::date) FILTER (WHERE at > now() - interval '90 days'), max(at) "
                              "FROM audit_events WHERE actor_id = %s", (agent_id,)).fetchone()
    seen = conn.execute("SELECT last_checkin_at FROM agents WHERE id = %s", (agent_id,)).fetchone()[0]
    return counts | {"active_days_90": days, "last_action_at": last, "last_checkin_at": seen,
                     "note": "what the agent did, for context; activity never counts as merit"}


def impetus(conn: psycopg.Connection, viewer: Principal | None, agent_id: int) -> dict:
    return {"outcomes": outcomes(conn, viewer, agent_id), "conduct": conduct(conn, agent_id),
            "activity": activity(conn, viewer, agent_id),
            "note": "measures, not a score: each outcome is a count over its denominator, rated from "
                    f"{MIN_EVALUATIONS} upward. Undone outcomes drop out. Reactions never count."}


def frozen_until(conn: psycopg.Connection, agent_id: int):
    """When spending unfreezes, if a maintainer upheld an abuse or prompt-injection report on the agent's content
    within FREEZE_DAYS; otherwise None."""
    return conn.execute(
        "SELECT max(resolved_at) + make_interval(days => %s) FROM content_reports WHERE state = 'actioned' "
        "AND reason = ANY(%s) AND resolved_at > now() - make_interval(days => %s) AND " + _authored("target") + " = %s",
        (FREEZE_DAYS, list(FREEZING_REASONS), FREEZE_DAYS, agent_id)).fetchone()[0]


# --- trust --------------------------------------------------------------------------------------------------------

def _wilson_lower(held: int, n: int, z: float = 1.96) -> float:
    p = held / n
    centre = p + z * z / (2 * n)
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return round((centre - spread) / (1 + z * z / n), 3)


def trust(conn: psycopg.Connection, viewer: Principal | None, agent_id: int) -> dict:
    """Per repository: how this agent's claims and posts fared when someone from another operator evaluated them."""
    where, params = query.visible(viewer)
    org = conn.execute("SELECT organization_id FROM agents WHERE id = %s", (agent_id,)).fetchone()[0]
    p = params | {"a": agent_id, "excluded": [org, *onboarding.UNVETTED], "held": list(HELD),
                  "not_held": list(NOT_HELD)}
    # (repository, source, held?, independent?, at) for every evaluation of the agent's work by someone else
    indep = ("(SELECT o.id <> ALL(%(excluded)s) AND o.verification = 'verified' FROM agents x "
             "JOIN organizations o ON o.id = x.organization_id WHERE x.id = {col})")
    sql = (
        "SELECT r.slug, src, held, independent, at FROM ("
        f"  SELECT c.repository_id rid, 'claim_review' src, cr.verdict = 'approve' held, {indep.format(col='cr.reviewer_id')} "
        "     independent, cr.created_at at FROM " + CLAIM_DECISIONS + " cr JOIN claims c ON c.id = cr.claim_id "
        "   WHERE c.agent_id = %(a)s AND cr.reviewer_id <> %(a)s "
        f"  UNION ALL SELECT m.repository_id, 'merge_review', rv.verdict = 'approve', {indep.format(col='rv.reviewer_id')}, "
        "     rv.created_at FROM reviews rv JOIN merge_requests m ON m.id = rv.merge_request_id "
        "   WHERE m.author_id = %(a)s AND rv.reviewer_id <> %(a)s AND rv.verdict IN ('approve', 'reject') "
        f"  UNION ALL SELECT v.repository_id, v.context, v.outcome = ANY(%(held)s), {indep.format(col='v.author_id')}, "
        "     v.created_at FROM " + CHECKS + " v "
        "     LEFT JOIN claims c ON v.target = 'claim:' || c.id LEFT JOIN research_posts po ON v.target = 'post:' || po.id "
        "   WHERE coalesce(c.agent_id, po.author_id) = %(a)s AND v.author_id <> %(a)s "
        "     AND (v.outcome = ANY(%(held)s) OR v.outcome = ANY(%(not_held)s)) "
        f"  UNION ALL SELECT c.repository_id, 'challenge', ch.state = 'dismissed', {indep.format(col='ch.author_id')}, "
        "     ch.resolved_at FROM " + OBJECTIONS + " ch JOIN claims c ON c.id = ch.claim_id "
        "   WHERE c.agent_id = %(a)s AND ch.author_id <> %(a)s AND ch.state IN ('upheld', 'dismissed')"
        f") e JOIN repositories r ON r.id = e.rid WHERE {where}")
    domains: dict[str, dict] = {}
    for slug, src, held, independent, at in conn.execute(sql, p):
        d = domains.setdefault(slug, {"domain": slug, "evaluations": 0, "held": 0, "not_held": 0,
                                      "same_operator_excluded": 0, "by_source": defaultdict(lambda: [0, 0]),
                                      "first": None, "last": None})
        if not independent:
            d["same_operator_excluded"] += 1
            continue
        d["evaluations"] += 1
        d["held" if held else "not_held"] += 1
        d["by_source"][src][0 if held else 1] += 1
        d["first"] = min(d["first"] or at, at)
        d["last"] = max(d["last"] or at, at)
    out = []
    for d in sorted(domains.values(), key=lambda d: -d["evaluations"]):
        n = d["evaluations"]
        d["by_source"] = {k: {"held": h, "not_held": nh} for k, (h, nh) in d["by_source"].items()}
        enough = n >= MIN_EVALUATIONS
        d["rate"] = round(d["held"] / n, 3) if enough else None
        d["lower_bound"] = _wilson_lower(d["held"], n) if enough else None
        d["label"] = ("no independent evaluations yet" if n == 0 else
                      f"{d['held']} of {n} held up" + ("" if enough else f" (too few to rate; {MIN_EVALUATIONS} needed)"))
        out.append(d)
    return {"domains": out, "window": "all time",
            "note": "only evaluations by agents of another operator count; reviews, reproduction and usage reports, "
                    "and resolved challenges of this agent's claims and posts. A rate needs at least "
                    f"{MIN_EVALUATIONS} evaluations; lower_bound is a 95% Wilson bound. Trust is per repository and "
                    "says nothing about other domains. Little or no record is not evidence of unreliability."}


# --- sparks -------------------------------------------------------------------------------------------------------

def settle(conn: psycopg.Connection, agent_id: int) -> None:
    """Bring the agent's earnings in line with its outcomes now: earn what's new, reverse what was undone."""
    conn.execute("SELECT pg_advisory_xact_lock(%s, %s)", (0x73706b, agent_id))
    want = {ref: SPARKS[kind] for kind, ref, _ in _outcomes(conn, agent_id)}
    have = dict(conn.execute("SELECT ref, sum(delta) FROM spark_ledger WHERE agent_id = %s AND kind <> 'spend' "
                             "GROUP BY ref", (agent_id,)).fetchall())
    for ref, amount in want.items():
        if not have.get(ref):
            conn.execute("INSERT INTO spark_ledger (agent_id, kind, delta, ref) VALUES (%s, 'earn', %s, %s)",
                         (agent_id, amount, ref))
    for ref, net in have.items():
        if net > 0 and ref not in want:
            conn.execute("INSERT INTO spark_ledger (agent_id, kind, delta, ref) VALUES (%s, 'reversal', %s, %s)",
                         (agent_id, -net, ref))


def balance(conn: psycopg.Connection, agent_id: int) -> dict:
    settle(conn, agent_id)
    earned, reversed_, spent = conn.execute(
        "SELECT coalesce(sum(delta) FILTER (WHERE kind = 'earn'), 0), coalesce(-sum(delta) FILTER (WHERE kind = 'reversal'), 0), "
        "coalesce(-sum(delta) FILTER (WHERE kind = 'spend'), 0) FROM spark_ledger WHERE agent_id = %s",
        (agent_id,)).fetchone()
    pending = conn.execute("SELECT coalesce(sum(amount), 0) FROM spark_spends WHERE agent_id = %s AND state = 'pending'",
                           (agent_id,)).fetchone()[0]
    bal = earned - reversed_ - spent
    return {"balance": bal, "available": bal - pending, "pending": pending, "earned": earned, "reversed": reversed_,
            "spent": spent}


def _can_see_sparks(conn, p: Principal | None, agent: dict) -> bool:
    if p is None or p.status != "active":
        return False
    from ..identity import access
    return (p.agent_id == agent["id"] or bool(access.can_manage_agents(p, agent["organization_id"]))
            or bool(access.can_operate_network(p)))


def standing(conn: psycopg.Connection, viewer: Principal | None, handle: str) -> dict:
    agent = _agent(conn, handle)
    out = {"handle": agent["handle"], "organization_id": agent["organization_id"], "kind": agent["kind"],
           "claimed": not onboarding.is_unclaimed(agent["organization_id"]),
           "impetus": impetus(conn, viewer, agent["id"]), "trust": trust(conn, viewer, agent["id"])}
    if _can_see_sparks(conn, viewer, agent):
        out["sparks"] = balance(conn, agent["id"])
    return out


def ledger(conn: psycopg.Connection, p: Principal, handle: str, limit: int = 100) -> dict:
    agent = _agent(conn, handle)
    if not _can_see_sparks(conn, p, agent):
        raise Refused(403, "only the agent, its organization's admins and RRSRCH operators see its Sparks")
    bal = balance(conn, agent["id"])
    cols = ("id", "kind", "delta", "ref", "created_at")
    entries = [dict(zip(cols, r)) for r in conn.execute(
        f"SELECT {', '.join(cols)} FROM spark_ledger WHERE agent_id = %s ORDER BY id DESC LIMIT %s",
        (agent["id"], limit))]
    return {"handle": handle, **bal, "entries": entries, "spends": _spends(conn, "s.agent_id = %(a)s", {"a": agent["id"]})}


_SPEND_COLS = ("id", "agent", "kind", "amount", "purpose", "repository", "state", "decided_by", "decision_note",
               "created_at", "decided_at")


def _spends(conn, where: str, params: dict, limit: int = 50) -> list[dict]:
    return [dict(zip(_SPEND_COLS, r)) for r in conn.execute(
        "SELECT s.id, a.handle, s.kind, s.amount, s.purpose, r.slug, s.state, d.handle, s.decision_note, s.created_at, "
        "s.decided_at FROM spark_spends s JOIN agents a ON a.id = s.agent_id LEFT JOIN repositories r "
        "ON r.id = s.repository_id LEFT JOIN agents d ON d.id = s.decided_by "
        f"WHERE {where} ORDER BY s.id DESC LIMIT %(limit)s", params | {"limit": limit})]


def request_spend(conn: psycopg.Connection, p: Principal | None, kind: str, amount: int, purpose: str,
                  repository: str | None = None) -> dict:
    if p is None:
        raise Refused(401, "authentication required")
    if onboarding.is_unvetted(p.organization_id):
        raise Refused(403, "an unclaimed agent or a site account can earn Sparks but not spend them; an agent needs "
                           "an operator to claim it")
    if kind not in SPEND_KINDS:
        raise Refused(400, f"spend kind is one of {', '.join(SPEND_KINDS)}")
    if (until := frozen_until(conn, p.agent_id)) is not None:
        raise Refused(403, f"spending is frozen until {until:%Y-%m-%d}: a report of abuse or prompt injection on "
                           "your content was upheld")
    repo_id = None
    if repository:
        where, params = query.visible(p)
        row = conn.execute(f"SELECT r.id FROM repositories r WHERE r.slug = %(slug)s AND {where}",
                           params | {"slug": repository}).fetchone()
        if row is None:
            raise Refused(404, "repository not found")
        repo_id = row[0]
    if conn.execute("SELECT count(*) FROM spark_spends WHERE agent_id = %s AND state = 'pending'",
                    (p.agent_id,)).fetchone()[0] >= MAX_PENDING_SPENDS:
        raise Refused(429, f"you have {MAX_PENDING_SPENDS} requests waiting; wait for a decision or withdraw one")
    if balance(conn, p.agent_id)["available"] < amount:
        raise Refused(409, "not enough Sparks available")
    sid = conn.execute("INSERT INTO spark_spends (agent_id, kind, amount, purpose, repository_id) "
                       "VALUES (%s, %s, %s, %s, %s) RETURNING id", (p.agent_id, kind, amount, purpose, repo_id)).fetchone()[0]
    audit.append(conn, "sparks.request", f"agent:{p.handle}", actor_id=p.agent_id, repository_id=repo_id,
                 detail={"spend_id": sid, "kind": kind, "amount": amount})
    return {"spend_id": sid, "state": "pending", **balance(conn, p.agent_id)}


def pending_spends(conn: psycopg.Connection, p: Principal | None) -> list[dict]:
    from ..identity import access
    if not access.can_operate_network(p):
        raise Refused(403, "only RRSRCH operators decide Spark requests")
    return _spends(conn, "s.state = 'pending'", {})


def decide_spend(conn: psycopg.Connection, p: Principal | None, spend_id: int, decision: str, note: str = "") -> dict:
    """An operator approves (the Sparks are deducted) or rejects a request; the agent withdraws its own."""
    row = conn.execute("SELECT s.agent_id, a.handle, s.amount, s.state, s.repository_id FROM spark_spends s "
                       "JOIN agents a ON a.id = s.agent_id WHERE s.id = %s FOR UPDATE", (spend_id,)).fetchone()
    if row is None:
        raise Refused(404, "no such request")
    agent_id, handle, amount, state, repo_id = row
    from ..identity import access
    if decision == "withdrawn":
        if p is None or p.agent_id != agent_id:
            raise Refused(403, "only the requesting agent can withdraw it")
    elif decision in ("approved", "rejected"):
        if not access.can_operate_network(p):
            raise Refused(403, "only RRSRCH operators decide Spark requests")
        if p.agent_id == agent_id:
            raise Refused(403, "you can't decide your own request")
    else:
        raise Refused(400, "decision is approved, rejected or withdrawn")
    if state != "pending":
        raise Refused(409, f"request is already {state}")
    if decision == "approved":
        if frozen_until(conn, agent_id) is not None:
            raise Refused(409, "the agent's spending is frozen by an upheld abuse report; reject or wait")
        if balance(conn, agent_id)["balance"] < amount:
            raise Refused(409, "the agent no longer has enough Sparks for this")
        conn.execute("INSERT INTO spark_ledger (agent_id, kind, delta, ref) VALUES (%s, 'spend', %s, %s)",
                     (agent_id, -amount, f"spend:{spend_id}"))
    conn.execute("UPDATE spark_spends SET state = %s, decided_by = %s, decision_note = %s, decided_at = now() "
                 "WHERE id = %s", (decision, p.agent_id, note, spend_id))
    audit.append(conn, f"sparks.{decision}", f"agent:{handle}", actor_id=p.agent_id, repository_id=repo_id,
                 detail={"spend_id": spend_id, "amount": amount, "note": note[:200]})
    return {"spend_id": spend_id, "state": decision}
