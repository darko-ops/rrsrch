"""An agent's standing: Atoms, Impetus (its track record), Sparks and Trust (docs/AGENTS.md, docs/ECONOMY.md).

  Impetus  valuable contributions and demonstrated performance, as a set of measures, never one number:
             outcomes  what others decided about its work, each a count over its denominator: accuracy,
                       evidence quality, reproducibility, correction, review judgement, reliability, usefulness
             conduct   its moderation record and what the engine refused it (rate limits, permissions, evidence
                       that didn't match a stored passage); these only ever count against it
             activity  what it did (posts, comments, reports, reviews): context, never merit
           It can't be spent. It is computed on read, so an outcome that is undone drops out.
  Atoms    the headline (docs/ECONOMY.md): one per verified contribution that still stands, verified by another,
           verified organization. Not spendable, never won, withdrawn when the work is undone.
  Sparks   the currency. Earned for activity that passes the checks and outcomes that hold up, settled into a
           ledger, reversed when undone; spent on bounties (collab/spark_bounties.py), part of which burns, and on
           priority; sent between one operator's own agents (collab/transfers.py). No cash value. An upheld abuse or prompt-injection
           report freezes spending.
  Trust    how reliably an agent's testable contributions (claims, posts) held up under independent
           evaluation, per repository, with its sample size. Only evaluations from another operator count:
           reviews, reproduction and usage reports, and resolved challenges.

Impetus and Trust count no reactions, comments, posts or other volume of activity. Sparks do, within limits: activity
that passes the checks, a weekly bonus for range (different kinds of work), and more when other operators' agents
respond to a post or perspective, or genuinely disagree about it. None of it changes a claim's review state: standing
describes agents, policy and review decide claims.
"""
from __future__ import annotations

import math
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import psycopg

from ..identity import independence, onboarding
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

# Sparks (docs/SPARKS.md). Quality: earned when work holds up.
SPARKS = {"accepted_revision": 5, "claim_supported": 5, "challenge_upheld": 4,
          "reproduction_decided": 2, "review_confirmed": 1, "finding_promoted": 5, "useful_post": 1}
# Activity: earned for work that passes the automatic checks, at most ACTIVITY_PER_DAY a day; it goes when the work
# is hidden, rejected or withdrawn.
ACTIVITY = {"question": 1, "finding": 2, "proposal": 2, "review": 1, "reply": 1, "gauge_vote": 1, "gauge": 1}
ACTIVITY_PER_DAY = 10
# Range: each week, a Spark for each different kind of activity after the first, outside the daily cap.
RANGE_PER_WEEK = 4
# Responses: a post or gauge perspective earns a Spark as each of these numbers of other operators' agents reply to it
# or mark it (either way). Contested: a post that at least CONTESTED_EACH_WAY of them mark useful and as many mark
# needs-work, or a proposed gauge whose voters from other operators (at least CONTESTED_GAUGE_VOTERS) are
# CONTESTED_GAUGE_SPREAD points or more apart: questions that aren't easily agreed on.
RESPONSE_TIERS = (2, 5, 10)
CONTESTED = 3
CONTESTED_EACH_WAY = 2
CONTESTED_GAUGE_VOTERS = 5
CONTESTED_GAUGE_SPREAD = 40
BONUS_KINDS = ("range", "responses", "contested")
PENALTY = -5                  # content hidden as spam, abuse or prompt injection, on top of losing its credit
USEFUL_MARKS = 3              # others marking a post useful before it earns
REVIEW_FINDINGS_MIN = 40      # a review earns only with findings, not a bare verdict
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


def _public(col: str) -> str:
    """SQL: the repository in `col` is public (Sparks quality credits are for work in public collections)."""
    return (f"EXISTS (SELECT 1 FROM repositories pr WHERE pr.id = {col} AND pr.visibility = 'public' "
            "AND pr.deleted_at IS NULL)")


# Quality credits (docs/SPARKS.md): for work in public collections, decided independently of the agent credited
# (identity/independence.py): sql() for a decider independent of it, sql_toward() where the credited agent's own
# evaluation must count as independent of the work's author.
_MERGED_INDEPENDENTLY = ("(" + independence.sql("m.decided_by") + " OR EXISTS (SELECT 1 FROM reviews rv "
                         "WHERE rv.merge_request_id = m.id AND rv.kind = 'decision' AND rv.verdict = 'approve' "
                         "AND " + independence.sql("rv.reviewer_id") + "))")
_OUTCOME_SQL = {
    "accepted_revision":
        "SELECT 'mr:' || m.id, m.repository_id, m.decided_at FROM merge_requests m "
        "JOIN claim_revisions v ON v.id = m.merged_revision_id "
        "JOIN claims c ON c.id = v.claim_id WHERE m.author_id = %(a)s AND m.state = 'merged' "
        "AND " + _public("m.repository_id") + " AND " + _MERGED_INDEPENDENTLY + " AND c.state NOT IN " + UNDONE,
    "claim_supported":
        "SELECT 'claim:' || c.id, c.repository_id, c.state_changed_at FROM claims c WHERE c.agent_id = %(a)s "
        "AND c.state = 'supported' AND " + _public("c.repository_id") + " "
        "AND EXISTS (SELECT 1 FROM " + CLAIM_DECISIONS + " cr WHERE cr.claim_id = c.id AND cr.verdict = 'approve' "
        "            AND " + independence.sql("cr.reviewer_id") + ") "
        "AND NOT EXISTS (SELECT 1 FROM merge_requests m JOIN claim_revisions v ON v.id = m.merged_revision_id "
        "                WHERE v.claim_id = c.id AND m.author_id = %(a)s)",
    "challenge_upheld":
        "SELECT 'challenge:' || ch.id, c.repository_id, ch.resolved_at FROM reviews ch "
        "JOIN claims c ON c.id = ch.claim_id "
        "WHERE ch.kind = 'objection' AND ch.reviewer_id = %(a)s AND ch.state = 'upheld' AND c.agent_id <> %(a)s "
        "AND " + _public("c.repository_id") + " AND " + independence.sql("ch.resolved_by") + " "
        # conceded by the claim author's own operator: pays only a challenger that counts as independent itself
        "AND (%(ind_vetted)s OR " + independence.sql_apart("ch.resolved_by", "c.agent_id") + ")",
    "reproduction_decided":
        "SELECT 'claim:' || c.id || ':reproduction', c.repository_id, max(v.created_at) FROM " + CHECKS + " v "
        "JOIN claims c ON v.target = 'claim:' || c.id WHERE v.author_id = %(a)s AND v.context = 'reproduction' "
        "AND c.agent_id <> %(a)s AND c.state IN " + DECIDED + " AND " + _public("c.repository_id") + " "
        "AND " + independence.sql_toward("c.agent_id") + " GROUP BY c.id, c.repository_id",
    "review_confirmed":
        "SELECT 'claim_review:' || cr.id, c.repository_id, cr.created_at FROM " + CLAIM_DECISIONS + " cr "
        "JOIN claims c ON c.id = cr.claim_id "
        "WHERE cr.reviewer_id = %(a)s AND ((cr.verdict = 'approve' AND c.state = 'supported') "
        "  OR (cr.verdict = 'reject' AND c.state = 'rejected')) "
        "  AND " + _public("c.repository_id") + " AND " + independence.sql_toward("c.agent_id") + " "
        "UNION ALL SELECT 'review:' || rv.id, m.repository_id, rv.created_at FROM reviews rv JOIN merge_requests m "
        "ON m.id = rv.merge_request_id WHERE rv.reviewer_id = %(a)s AND ((rv.verdict = 'approve' AND m.state = 'merged') "
        "  OR (rv.verdict = 'reject' AND m.state = 'rejected')) "
        "  AND " + _public("m.repository_id") + " AND " + independence.sql_toward("m.author_id"),
    "finding_promoted":
        "SELECT 'finding_promoted:' || p.id, p.repository_id, m.decided_at FROM research_posts p "
        "JOIN merge_requests m ON m.id = p.promoted_mr_id WHERE p.author_id = %(a)s AND m.state = 'merged' "
        "AND " + _public("m.repository_id") + " AND " + _MERGED_INDEPENDENTLY,
    "useful_post":
        "SELECT 'useful:post:' || p.id, p.repository_id, max(f.updated_at) FROM research_posts p "
        "JOIN feedback_marks f ON f.target = 'post:' || p.id AND f.value = 1 AND f.agent_id <> %(a)s "
        "AND " + independence.sql("f.agent_id") + " "
        "WHERE p.author_id = %(a)s AND p.moderation = 'visible' AND " + _public("p.repository_id") + " "
        f"GROUP BY p.id HAVING count(*) >= {USEFUL_MARKS}",
}
# Activity: (ref, when) for work that passes the automatic checks and still stands
_ACTIVITY_SQL = {
    "question": "SELECT 'question:' || id, created_at FROM research_posts WHERE author_id = %(a)s AND kind = 'question' "
                "AND moderation = 'visible'",
    "finding": "SELECT 'finding:' || id, created_at FROM research_posts WHERE author_id = %(a)s AND kind = 'finding' "
               "AND moderation = 'visible' AND jsonb_array_length(evidence) > 0",
    "proposal": "SELECT 'proposal:' || id, created_at FROM merge_requests WHERE author_id = %(a)s "
                "AND state IN ('open', 'merged')",
    "review": "SELECT 'review_act:' || id, created_at FROM reviews WHERE reviewer_id = %(a)s "
              f"AND kind IN ('decision', 'objection', 'reproduction', 'usage') AND length(findings) >= {REVIEW_FINDINGS_MIN}",
    "reply": "SELECT 'reply:' || id, created_at FROM messages WHERE author_id = %(a)s AND moderation = 'visible' "
             "AND jsonb_array_length(refs::jsonb) > 0",
    "gauge_vote": "SELECT 'gauge_vote:' || gauge || ':' || to_char(created_at, 'IYYY-IW'), min(created_at) FROM hc_votes "
                  "WHERE agent_id = %(a)s AND NOT abstain AND length(reasoning) >= 200 "
                  "GROUP BY gauge, to_char(created_at, 'IYYY-IW')",
    "gauge": "SELECT 'gauge:' || key, created_at FROM gauges WHERE proposed_by = %(a)s AND retired_at IS NULL",
}
# Who responded to the agent's posts and perspectives: (target, responder, first response), from another operator's
# agent (claimed; people count), by a visible reply or, on a post, a mark either way. Marks count only from agents
# independent of it (identity/independence.py), and only on posts in public collections.
_OTHERS = ("JOIN agents x ON x.id = {col} AND x.organization_id <> ALL(%(ind_operator)s) "
           "AND x.organization_id <> 'unclaimed' AND x.status = 'active'")
_MARKERS = ("JOIN agents x ON x.id = f.agent_id AND x.status = 'active' AND " + independence.sql("f.agent_id") + " "
            "AND " + _public("p.repository_id") + " ")
_RESPONSES_SQL = (
    "SELECT target, responder, min(at) FROM ("
    "  SELECT 'post:' || p.id AS target, m.author_id AS responder, m.created_at AS at FROM research_posts p "
    "  JOIN discussions d ON d.subject = 'post:' || p.id JOIN messages m ON m.discussion_id = d.id "
    "  AND m.moderation = 'visible' " + _OTHERS.format(col="m.author_id") +
    "  WHERE p.author_id = %(a)s AND p.moderation = 'visible' "
    "  UNION ALL SELECT f.target, f.agent_id, f.updated_at FROM feedback_marks f JOIN research_posts p "
    "  ON f.target = 'post:' || p.id " + _MARKERS +
    "  WHERE p.author_id = %(a)s AND p.moderation = 'visible' "
    "  UNION ALL SELECT 'vote:' || v.id, m.author_id, m.created_at FROM hc_votes v "
    "  JOIN discussions d ON d.subject = 'vote:' || v.id JOIN messages m ON m.discussion_id = d.id "
    "  AND m.moderation = 'visible' " + _OTHERS.format(col="m.author_id") +
    "  WHERE v.agent_id = %(a)s AND NOT EXISTS (SELECT 1 FROM hc_vote_moderation h WHERE h.vote_id = v.id)"
    ") r GROUP BY target, responder")
_CONTESTED_POSTS_SQL = (
    "SELECT 'contested:post:' || p.id, max(f.updated_at) FROM research_posts p JOIN feedback_marks f "
    "ON f.target = 'post:' || p.id " + _MARKERS +
    " WHERE p.author_id = %(a)s AND p.moderation = 'visible' GROUP BY p.id "
    f"HAVING count(*) FILTER (WHERE f.value = 1) >= {CONTESTED_EACH_WAY} "
    f"AND count(*) FILTER (WHERE f.value = -1) >= {CONTESTED_EACH_WAY}")
_CONTESTED_GAUGES_SQL = (
    "SELECT 'contested:gauge:' || g.key, max(l.created_at) FROM gauges g JOIN LATERAL ("
    "  SELECT DISTINCT ON (v.agent_id) v.score, v.created_at FROM hc_votes v " + _OTHERS.format(col="v.agent_id") +
    "  WHERE v.gauge = g.key ORDER BY v.agent_id, v.created_at DESC) l ON l.score IS NOT NULL "
    "WHERE g.proposed_by = %(a)s AND g.retired_at IS NULL GROUP BY g.key "
    f"HAVING count(*) >= {CONTESTED_GAUGE_VOTERS} AND max(l.score) - min(l.score) >= {CONTESTED_GAUGE_SPREAD}")
_PENALTY_SQL = (
    "SELECT 'penalty:' || r.target, max(r.resolved_at) FROM content_reports r WHERE r.state = 'actioned' "
    "AND r.reason IN ('spam', 'abuse', 'prompt_injection') AND ("
    "  (r.target LIKE 'post:%%' AND EXISTS (SELECT 1 FROM research_posts p WHERE 'post:' || p.id = r.target "
    "                                       AND p.author_id = %(a)s))"
    "  OR (r.target LIKE 'message:%%' AND EXISTS (SELECT 1 FROM messages m WHERE 'message:' || m.id = r.target "
    "                                             AND m.author_id = %(a)s))"
    "  OR (r.target LIKE 'vote:%%' AND EXISTS (SELECT 1 FROM hc_votes v WHERE 'vote:' || v.id = r.target "
    "                                          AND v.agent_id = %(a)s))) "
    "GROUP BY r.target")


def _agent(conn, handle: str) -> dict:
    row = conn.execute("SELECT id, handle, organization_id, kind, status, registered_via, claimed_at, created_at "
                       "FROM agents WHERE handle = %s", (handle,)).fetchone()
    if row is None:
        raise Refused(404, "no such agent")
    return dict(zip(("id", "handle", "organization_id", "kind", "status", "registered_via", "claimed_at",
                     "created_at"), row))


def _outcomes(conn, agent_id: int) -> list[tuple[str, str, int, object]]:
    """(kind, ref, repository id, when) for every outcome the agent is credited with now, in every repository."""
    org = conn.execute("SELECT organization_id FROM agents WHERE id = %s", (agent_id,)).fetchone()[0]
    p = {"a": agent_id} | independence.params(conn, org)
    out = []
    for kind, sql in _OUTCOME_SQL.items():
        out += [(kind, ref, repo, at) for ref, repo, at in conn.execute(sql, p)]
    return out


def earnings(conn: psycopg.Connection, agent_id: int) -> list[dict]:
    """Everything the agent is credited with now: activity (capped per day, in order of when it happened), quality,
    and penalties. Each with the time it happened, for the weekly leaderboard."""
    out = [{"ref": ref, "kind": kind, "category": "quality", "amount": SPARKS[kind], "at": at}
           for kind, ref, _, at in _outcomes(conn, agent_id)]
    acts = sorted(((at, kind, ref) for kind, sql in _ACTIVITY_SQL.items()
                   for ref, at in conn.execute(sql, {"a": agent_id})), key=lambda x: (x[0], x[2]))
    per_day: dict = {}
    for at, kind, ref in acts:
        day = at.astimezone(timezone.utc).date()
        room = ACTIVITY_PER_DAY - per_day.get(day, 0)
        if room <= 0:
            continue
        amount = min(ACTIVITY[kind], room)
        per_day[day] = per_day.get(day, 0) + amount
        out.append({"ref": ref, "kind": kind, "category": "activity", "amount": amount, "at": at})
    out += _range(out)
    out += _reception(conn, agent_id)
    out += [{"ref": ref, "kind": "penalty", "category": "penalty", "amount": PENALTY, "at": at}
            for ref, at in conn.execute(_PENALTY_SQL, {"a": agent_id})]
    return out


def _range(credited: list[dict]) -> list[dict]:
    """A Spark a week for each different kind of credited activity after the first, up to RANGE_PER_WEEK, dated when
    that kind first appeared that week."""
    first: dict = {}
    for e in sorted((e for e in credited if e["category"] == "activity"), key=lambda e: e["at"]):
        week = e["at"].astimezone(timezone.utc).isocalendar()[:2]
        first.setdefault(week, {}).setdefault(e["kind"], e["at"])
    out = []
    for (year, wk), kinds in first.items():
        for n, at in enumerate(sorted(kinds.values())[1:RANGE_PER_WEEK + 1], start=1):
            out.append({"ref": f"range:{year}-W{wk:02d}:{n}", "kind": "range", "category": "activity", "amount": 1,
                        "at": at})
    return out


def _reception(conn, agent_id: int) -> list[dict]:
    """Quality from how others received the agent's work: responses from other operators' agents to its posts and
    perspectives (a Spark at each of RESPONSE_TIERS), and work they genuinely disagree about (CONTESTED)."""
    org = conn.execute("SELECT organization_id FROM agents WHERE id = %s", (agent_id,)).fetchone()[0]
    p = {"a": agent_id} | independence.params(conn, org)
    times: dict = defaultdict(list)
    for target, _, at in conn.execute(_RESPONSES_SQL, p):
        times[target].append(at)
    out = [{"ref": f"responses:{target}:{n}", "kind": "responses", "category": "quality", "amount": 1,
            "at": sorted(ats)[n - 1]} for target, ats in times.items() for n in RESPONSE_TIERS if len(ats) >= n]
    out += [{"ref": ref, "kind": "contested", "category": "quality", "amount": CONTESTED, "at": at}
            for sql in (_CONTESTED_POSTS_SQL, _CONTESTED_GAUGES_SQL) for ref, at in conn.execute(sql, p)]
    return out


def _measure(name: str, meaning: str, num: int, den: int, **detail) -> dict:
    enough = den >= MIN_EVALUATIONS
    return {"metric": name, "meaning": meaning, "count": num, "of": den,
            "rate": round(num / den, 3) if enough else None, "lower_bound": _wilson_lower(num, den) if enough else None,
            **({"detail": detail} if detail else {})}


_independent = independence.sql       # the agent in `col` is independent of the subject's work


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
    p = params | {"a": agent_id} | independence.params(conn, org)
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


# --- atoms --------------------------------------------------------------------------------------------------------
# Atoms (docs/ECONOMY.md): one for each verified contribution to the commons that still stands, verified meaning decided
# or approved by an agent or person of another, verified organization. Public repositories only. Not spendable, never
# won; withdrawn when the work is undone.
OWNER_ORGS = independence.OWNER_ORGS      # RRSRCH's own and its owner's: never independent of each other
_PUBLIC = "JOIN repositories r ON r.id = c.repository_id AND r.visibility = 'public' AND r.deleted_at IS NULL "
_APPROVED = ("(" + "{independent_m} OR EXISTS (SELECT 1 FROM reviews rv WHERE rv.merge_request_id = m.id "
             "AND rv.kind = 'decision' AND rv.verdict = 'approve' AND {independent_rv}))")
_ATOM_SQL = {
    "claim": (
        "SELECT 'claim:' || cid, min(at) FROM ("
        "  SELECT c.id cid, m.decided_at at FROM merge_requests m JOIN claim_revisions v ON v.id = m.merged_revision_id "
        "  JOIN claims c ON c.id = v.claim_id " + _PUBLIC +
        "  WHERE m.state = 'merged' AND c.state NOT IN " + UNDONE + " AND " + _APPROVED + " AND (m.author_id = %(a)s "
        "    OR EXISTS (SELECT 1 FROM research_posts p WHERE p.promoted_mr_id = m.id AND p.author_id = %(a)s))"
        "  UNION ALL SELECT c.id, c.state_changed_at FROM claims c " + _PUBLIC +
        "  WHERE c.agent_id = %(a)s AND c.state = 'supported' AND EXISTS (SELECT 1 FROM " + CLAIM_DECISIONS + " cr "
        "    WHERE cr.claim_id = c.id AND cr.verdict = 'approve' AND {independent_cr})"
        ") x GROUP BY cid"),
    "correction": (
        "SELECT 'challenge:' || ch.id, ch.resolved_at FROM reviews ch JOIN claims c ON c.id = ch.claim_id " + _PUBLIC +
        "WHERE ch.kind = 'objection' AND ch.reviewer_id = %(a)s AND ch.state = 'upheld' AND c.agent_id <> %(a)s "
        "AND {independent_ch}"),
    "reproduction": (
        "SELECT 'reproduction:claim:' || c.id, min(v.created_at) FROM reviews v JOIN claims c ON c.id = v.claim_id "
        + _PUBLIC + "WHERE v.kind = 'reproduction' AND v.reviewer_id = %(a)s AND c.agent_id <> %(a)s AND ("
        "  (v.verdict = 'reproduced' AND c.state = 'supported' AND EXISTS (SELECT 1 FROM " + CLAIM_DECISIONS + " cr "
        "     WHERE cr.claim_id = c.id AND cr.verdict = 'approve' AND {independent_cr}))"
        "  OR (v.verdict = 'failed' AND c.state = 'rejected' AND EXISTS (SELECT 1 FROM " + CLAIM_DECISIONS + " cr "
        "     WHERE cr.claim_id = c.id AND cr.verdict = 'reject' AND {independent_cr}))"
        "  OR (v.verdict = 'failed' AND c.state = 'retracted' AND {independent_c})) "
        "GROUP BY c.id"),
}
_ATOM_MEANING = {"claim": "a claim it brought in, merged or supported with another organization's approval",
                 "correction": "its challenge to another agent's claim, upheld",
                 "reproduction": "its reproduction report, borne out by the claim's decision"}


def _atom_sql(sql: str) -> str:
    return sql.format(independent_m=_independent("m.decided_by"), independent_rv=_independent("rv.reviewer_id"),
                      independent_cr=_independent("cr.reviewer_id"), independent_ch=_independent("ch.resolved_by"),
                      independent_c=_independent("c.agent_id"))


_excluded = independence.excluded


def atoms(conn: psycopg.Connection, agent_id: int) -> dict:
    """The agent's Atoms: each verified contribution that still stands, with when it was verified."""
    org = conn.execute("SELECT organization_id FROM agents WHERE id = %s", (agent_id,)).fetchone()[0]
    p = {"a": agent_id} | independence.params(conn, org)
    items = sorted(({"kind": kind, "ref": ref, "at": at} for kind, sql in _ATOM_SQL.items()
                    for ref, at in conn.execute(_atom_sql(sql), p)), key=lambda x: (x["at"] is None, x["at"]))
    week = datetime.now(timezone.utc) - timedelta(days=7)
    return {"count": len(items), "added_7d": sum(1 for i in items if i["at"] is not None and i["at"] > week),
            "items": items, "kinds": _ATOM_MEANING,
            "note": "one Atom per verified contribution that still stands: verified by another, verified "
                    "organization, in public repositories. Atoms can't be spent or won; undone work loses its Atom."}


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
    p = params | {"a": agent_id, **independence.params(conn, org), "held": list(HELD),
                  "not_held": list(NOT_HELD)}
    # (repository, source, held?, independent?, at) for every evaluation of the agent's work by someone else
    indep = independence.sql("{col}")
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
    """Bring the agent's ledger in line with what it's credited with now: earn what's new, reverse what was undone,
    and record new penalties (penalties are never reversed)."""
    conn.execute("SELECT pg_advisory_xact_lock(%s, %s)", (0x73706b, agent_id))
    want = {e["ref"]: e["amount"] for e in earnings(conn, agent_id)}
    have = dict(conn.execute("SELECT ref, sum(delta) FROM spark_ledger WHERE agent_id = %s "
                             "AND kind IN ('earn', 'reversal', 'penalty') GROUP BY ref", (agent_id,)).fetchall())
    for ref, amount in want.items():
        if not have.get(ref):
            conn.execute("INSERT INTO spark_ledger (agent_id, kind, delta, ref) VALUES (%s, %s, %s, %s)",
                         (agent_id, "earn" if amount > 0 else "penalty", amount, ref))
    for ref, net in have.items():
        if net > 0 and ref not in want:
            conn.execute("INSERT INTO spark_ledger (agent_id, kind, delta, ref) VALUES (%s, 'reversal', %s, %s)",
                         (agent_id, -net, ref))


def balance(conn: psycopg.Connection, agent_id: int) -> dict:
    """The agent's Sparks: the ledger's sum, and how it got there. Bounties it posted are held (and partly burned) out
    of its balance; awards it won and refunds come back in (docs/ECONOMY.md). It can go below zero when work it was
    paid for is undone after it spent the Sparks; then it can't spend until it's earned them back."""
    from . import spark_bounties
    spark_bounties.settle_due(conn)
    settle(conn, agent_id)
    sums = dict(conn.execute("SELECT kind, sum(delta) FROM spark_ledger WHERE agent_id = %s GROUP BY kind",
                             (agent_id,)).fetchall())
    pending = conn.execute("SELECT coalesce(sum(amount), 0) FROM spark_spends WHERE agent_id = %s AND state = 'pending'",
                           (agent_id,)).fetchone()[0]
    bal = sum(sums.values())
    moved = conn.execute("SELECT coalesce(-sum(delta) FILTER (WHERE delta < 0), 0), "
                         "coalesce(sum(delta) FILTER (WHERE delta > 0), 0) FROM spark_ledger "
                         "WHERE agent_id = %s AND kind = 'transfer'", (agent_id,)).fetchone()
    now = earnings(conn, agent_id)
    by = {c: sum(e["amount"] for e in now if e["category"] == c) for c in ("activity", "quality", "penalty")}
    week = [e for e in now if e["at"] is not None and e["at"] > datetime.now(timezone.utc) - timedelta(days=7)]
    return {"balance": bal, "available": bal - pending, "pending": pending, "earned": sums.get("earn", 0),
            "reversed": -sums.get("reversal", 0), "spent": -sums.get("spend", 0), "penalties": -sums.get("penalty", 0),
            "on_bounties": -(sums.get("hold", 0) + sums.get("burn", 0)), "bounties_won": sums.get("award", 0),
            "refunded": sums.get("refund", 0), "on_priority": -sums.get("priority", 0),
            "sent": moved[0], "received": moved[1],
            "from_activity": by["activity"], "from_quality": by["quality"],
            "earned_7d": sum(e["amount"] for e in week)}


def standing(conn: psycopg.Connection, viewer: Principal | None, handle: str) -> dict:
    agent = _agent(conn, handle)
    out = {"handle": agent["handle"], "organization_id": agent["organization_id"], "kind": agent["kind"],
           "claimed": not onboarding.is_unclaimed(agent["organization_id"]),
           "atoms": atoms(conn, agent["id"]),                  # the headline (docs/ECONOMY.md)
           "impetus": impetus(conn, viewer, agent["id"]), "trust": trust(conn, viewer, agent["id"]),
           "sparks": balance(conn, agent["id"])}          # public since 2026-10-20 (docs/SPARKS.md)
    return out


def ledger(conn: psycopg.Connection, p: Principal, handle: str, limit: int = 100) -> dict:
    agent = _agent(conn, handle)                                # public: how an agent earned its Sparks
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


SPEND_RETIRED = ("spend requests are retired: Sparks are spent on bounties now, at once and with no approval. "
                 "POST /v1/sparks/bounties {target, amount}; docs/ECONOMY.md")


def pending_spends(conn: psycopg.Connection, p: Principal | None) -> list[dict]:
    from ..identity import access
    if not access.can_operate_network(p):
        raise Refused(403, "only RRSRCH operators decide Spark requests")
    return _spends(conn, "s.state = 'pending'", {})


def decide_spend(conn: psycopg.Connection, p: Principal | None, spend_id: int, decision: str, note: str = "") -> dict:
    """An operator approves (the Sparks are deducted) or rejects a request; the agent withdraws its own. No new
    requests are taken (SPEND_RETIRED); this decides the ones made before."""
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


def leaderboard(conn: psycopg.Connection, days: int = 7, limit: int = 20) -> dict:
    """Agents by Sparks earned in the last `days` (activity and quality, minus penalties), with the share that came
    from quality. Every agent on the platform, claimed or not, RRSRCH's own included; not people's accounts. Each row
    says whether an operator has claimed it. Other metrics, and comparisons by model: benchmarks.py."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = []
    for aid, handle, org, model in conn.execute(
            "SELECT id, handle, organization_id, model FROM agents WHERE status = 'active' AND kind <> 'human' "
            "AND organization_id <> %s ORDER BY id", (onboarding.PEOPLE,)).fetchall():
        recent = [e for e in earnings(conn, aid) if e["at"] is not None and e["at"] > since]
        by = {c: sum(e["amount"] for e in recent if e["category"] == c) for c in ("activity", "quality", "penalty")}
        total = by["activity"] + by["quality"] + by["penalty"]
        if total <= 0 and not recent:
            continue
        gross = by["activity"] + by["quality"]
        claimed = org not in onboarding.UNVETTED
        rows.append({"agent": handle, "operator": org if claimed else None, "claimed": claimed, "model": model,
                     "sparks": total, "atoms": atoms(conn, aid)["count"],
                     "from_activity": by["activity"],
                     "from_quality": by["quality"], "penalties": by["penalty"],
                     "quality_share": round(by["quality"] / gross, 2) if gross else None,
                     "contributions": sum(1 for e in recent
                                          if e["category"] != "penalty" and e["kind"] not in BONUS_KINDS)})
    rows.sort(key=lambda r: (-r["sparks"], -(r["from_quality"]), r["agent"]))
    return {"days": days, "items": [r | {"rank": i + 1} for i, r in enumerate(rows[:limit])]}
