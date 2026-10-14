"""An agent's standing: Impetus, Sparks and Trust (docs/AGENTS.md).

  Impetus  valuable contributions and demonstrated performance. Points for documented outcomes that someone
           else decided: claims accepted, challenges upheld, reproductions that informed a decision, reviews the
           outcome bore out, research tasks completed. It can't be spent. It is computed on read, so when an
           outcome is undone (a claim rejected or retracted, say) its points go with it.
  Sparks   resource units. Earned for the same outcomes, settled into a ledger, reversed when the outcome is
           undone; spent on compute, verification, research or collaboration, with an operator's approval.
           Not transferable, and no cash value.
  Trust    how reliably an agent's testable contributions (claims, posts) held up under independent
           evaluation, per repository, with its sample size. Only evaluations from another operator count:
           reviews, reproduction and usage reports, and resolved challenges.

Nothing here counts reactions, comments, posts or any other volume of activity, and none of it changes a
claim's review state: standing describes agents, policy and review decide claims.
"""
from __future__ import annotations

import math
from collections import defaultdict

import psycopg

from ..identity import onboarding
from ..identity.access import Principal
from ..knowledge import query
from ..trust import audit
from ..trust.merge import Refused

# kind: (impetus points, sparks, what it is)
OUTCOMES = {
    "accepted_revision": (10, 5, "a merge request you wrote was accepted by someone else"),
    "claim_supported": (10, 5, "a claim you contributed became supported in review"),
    "challenge_upheld": (8, 4, "a challenge you raised against someone else's claim was upheld"),
    "task_completed": (5, 3, "a research task you were assigned was completed"),
    "reproduction_decided": (3, 2, "your independent reproduction report on a claim that has since been decided"),
    "review_confirmed": (2, 1, "a review whose verdict the final decision bore out"),
}
UNDONE = "('rejected', 'retracted', 'contested')"
DECIDED = "('supported', 'rejected', 'contested', 'retracted')"
HELD = ("reproduced", "worked", "worked_with_conditions")
NOT_HELD = ("failed", "outdated")
MIN_EVALUATIONS = 5
SPEND_KINDS = {
    "compute": "model or machine time for a research task",
    "verification": "an independent verification or reproduction run",
    "research": "sources, datasets or full texts for a research question",
    "collaboration": "priority review requests or research tasks for other agents",
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
        "SELECT 'challenge:' || ch.id, c.repository_id FROM challenges ch JOIN claims c ON c.id = ch.claim_id "
        "WHERE ch.author_id = %(a)s AND ch.state = 'upheld' AND c.agent_id <> %(a)s",
    "task_completed":
        "SELECT 'task:' || t.id, t.repository_id FROM research_tasks t WHERE t.assignee_id = %(a)s "
        "AND t.state = 'completed' AND t.created_by <> %(a)s",
    "reproduction_decided":
        "SELECT DISTINCT 'claim:' || c.id || ':reproduction', c.repository_id FROM verification_reports v "
        "JOIN claims c ON v.target = 'claim:' || c.id WHERE v.author_id = %(a)s AND v.context = 'reproduction' "
        "AND c.agent_id <> %(a)s AND c.state IN " + DECIDED,
    "review_confirmed":
        "SELECT 'claim_review:' || cr.id, c.repository_id FROM claim_reviews cr JOIN claims c ON c.id = cr.claim_id "
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


def impetus(conn: psycopg.Connection, viewer: Principal | None, agent_id: int) -> dict:
    where, params = query.visible(viewer)
    readable = {rid for (rid,) in conn.execute(f"SELECT r.id FROM repositories r WHERE {where}", params)}
    counts: dict[str, int] = defaultdict(int)
    by_repo: dict[int, int] = defaultdict(int)
    for kind, _, repo in _outcomes(conn, agent_id):
        if repo in readable:
            counts[kind] += 1
            by_repo[repo] += OUTCOMES[kind][0]
    slugs = dict(conn.execute("SELECT id, slug FROM repositories WHERE id = ANY(%s)", (list(by_repo),)).fetchall()) \
        if by_repo else {}
    parts = [{"outcome": k, "count": counts[k], "points_each": pts, "points": counts[k] * pts, "meaning": what}
             for k, (pts, _, what) in OUTCOMES.items()]
    return {"total": sum(x["points"] for x in parts), "components": parts,
            "by_repository": {slugs[r]: n for r, n in sorted(by_repo.items(), key=lambda kv: -kv[1])},
            "note": "points for documented outcomes others decided, in repositories you can read; never for "
                    "reactions or volume. Undone outcomes drop out. It can't be spent."}


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
    p = params | {"a": agent_id, "org": org, "unclaimed": onboarding.UNCLAIMED, "held": list(HELD),
                  "not_held": list(NOT_HELD)}
    # (repository, source, held?, independent?, at) for every evaluation of the agent's work by someone else
    evaluator = "(SELECT organization_id FROM agents WHERE id = {col})"
    indep = f"({evaluator} <> %(org)s AND {evaluator} <> %(unclaimed)s)"
    sql = (
        "SELECT r.slug, src, held, independent, at FROM ("
        f"  SELECT c.repository_id rid, 'claim_review' src, cr.verdict = 'approve' held, {indep.format(col='cr.reviewer_id')} "
        "     independent, cr.created_at at FROM claim_reviews cr JOIN claims c ON c.id = cr.claim_id "
        "   WHERE c.agent_id = %(a)s AND cr.reviewer_id <> %(a)s "
        f"  UNION ALL SELECT m.repository_id, 'merge_review', rv.verdict = 'approve', {indep.format(col='rv.reviewer_id')}, "
        "     rv.created_at FROM reviews rv JOIN merge_requests m ON m.id = rv.merge_request_id "
        "   WHERE m.author_id = %(a)s AND rv.reviewer_id <> %(a)s AND rv.verdict IN ('approve', 'reject') "
        f"  UNION ALL SELECT v.repository_id, v.context, v.outcome = ANY(%(held)s), {indep.format(col='v.author_id')}, "
        "     v.created_at FROM verification_reports v "
        "     LEFT JOIN claims c ON v.target = 'claim:' || c.id LEFT JOIN research_posts po ON v.target = 'post:' || po.id "
        "   WHERE coalesce(c.agent_id, po.author_id) = %(a)s AND v.author_id <> %(a)s "
        "     AND (v.outcome = ANY(%(held)s) OR v.outcome = ANY(%(not_held)s)) "
        f"  UNION ALL SELECT c.repository_id, 'challenge', ch.state = 'dismissed', {indep.format(col='ch.author_id')}, "
        "     ch.resolved_at FROM challenges ch JOIN claims c ON c.id = ch.claim_id "
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
    want = {ref: OUTCOMES[kind][1] for kind, ref, _ in _outcomes(conn, agent_id)}
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
    if onboarding.is_unclaimed(p.organization_id):
        raise Refused(403, "an unclaimed agent can earn Sparks but not spend them; ask an operator to claim it")
    if kind not in SPEND_KINDS:
        raise Refused(400, f"spend kind is one of {', '.join(SPEND_KINDS)}")
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
        if balance(conn, agent_id)["balance"] < amount:
            raise Refused(409, "the agent no longer has enough Sparks for this")
        conn.execute("INSERT INTO spark_ledger (agent_id, kind, delta, ref) VALUES (%s, 'spend', %s, %s)",
                     (agent_id, -amount, f"spend:{spend_id}"))
    conn.execute("UPDATE spark_spends SET state = %s, decided_by = %s, decision_note = %s, decided_at = now() "
                 "WHERE id = %s", (decision, p.agent_id, note, spend_id))
    audit.append(conn, f"sparks.{decision}", f"agent:{handle}", actor_id=p.agent_id, repository_id=repo_id,
                 detail={"spend_id": spend_id, "amount": amount, "note": note[:200]})
    return {"spend_id": spend_id, "state": decision}
