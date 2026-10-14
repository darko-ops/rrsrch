"""Reviewing claims already in a repository: the path from structurally_valid to supported (or rejected).

A reviewer approves or rejects the claim's current revision. The decision is the same deterministic one as
for merges (rrsrch.trust.pipeline.review_tally): independent approvals only, a human approval if the policy
wants one, and nothing standing in the way: no objection, no open blocking challenge, and the passage the
claim rests on unchanged since it was extracted. When all of that holds the claim becomes supported.

A reject from a maintainer settles it (rejected). A reject from a reviewer without that role is an objection:
it keeps the claim from being supported until a maintainer decides.
"""
from __future__ import annotations

import psycopg

from ..identity import access
from ..identity.access import Action, Principal
from ..knowledge import states
from . import audit, pipeline
from .merge import Refused, repo_and_role, require
from .policy import load as load_policy

REVIEWABLE = ("structurally_valid", "under_review", "stale")
TO_SUPPORTED = {"structurally_valid": ("under_review", "supported"), "under_review": ("supported",),
                "stale": ("under_review", "supported")}
TO_REJECTED = {"structurally_valid": ("rejected",), "under_review": ("rejected",), "stale": ("under_review", "rejected")}
TO_UNDER_REVIEW = {"structurally_valid": ("under_review",), "stale": ("under_review",), "under_review": ()}


def _walk(conn, claim_id: int, state: str, path: tuple[str, ...]) -> str:
    for nxt in path:
        state = states.check(state, nxt).value
    conn.execute("UPDATE claims SET state = %s WHERE id = %s", (state, claim_id))
    return state


def review(conn: psycopg.Connection, p: Principal | None, claim_id: int, verdict: str, findings: str = "") -> dict:
    row = conn.execute(
        "SELECT c.repository_id, c.state, c.agent_id, a.organization_id, c.doc_sha256, d.sha256, r.policy_version "
        "FROM claims c JOIN agents a ON a.id = c.agent_id JOIN documents d ON d.id = c.document_id "
        "JOIN repositories r ON r.id = c.repository_id WHERE c.id = %s FOR UPDATE OF c", (claim_id,)).fetchone()
    if row is None:
        raise Refused(404, "not found")
    repo_id, state, author_id, author_org, doc_sha, current_sha, policy_version = row
    repo = require(conn, p, Action.REVIEW, repo_id)
    if verdict not in ("approve", "reject"):
        raise Refused(400, "verdict must be approve or reject")
    if p.agent_id == author_id:
        raise Refused(403, "authors can't review their own claim")
    if state not in REVIEWABLE:
        raise Refused(409, f"claim is {state}" + ("; challenge it instead" if state == "supported" else ""))
    head = conn.execute("SELECT id, version FROM claim_revisions WHERE claim_id = %s ORDER BY version DESC LIMIT 1",
                        (claim_id,)).fetchone()
    if head is None:
        raise Refused(409, "claim has no revision yet; run `rrsrch ledger load`")
    conn.execute(
        "INSERT INTO claim_reviews (claim_id, revision_id, reviewer_id, verdict, findings) VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (revision_id, reviewer_id) DO UPDATE SET verdict = EXCLUDED.verdict, "
        "findings = EXCLUDED.findings, created_at = now()", (claim_id, head[0], p.agent_id, verdict, findings))
    audit.append(conn, f"claim_review.{verdict}", f"claim:{claim_id}", actor_id=p.agent_id, repository_id=repo_id,
                 policy_version=policy_version, detail={"claim_id": claim_id, "revision": head[1]})

    _, role = repo_and_role(conn, p, repo_id)
    if verdict == "reject" and access.decide(p, Action.MAINTAIN, repo, role):
        new = _walk(conn, claim_id, state, TO_REJECTED[state])
        audit.append(conn, "claim.rejected", f"claim:{claim_id}", actor_id=p.agent_id, repository_id=repo_id,
                     policy_version=policy_version, detail={"claim_id": claim_id})
        return {"claim_id": claim_id, "state": new, "approvals": None, "reasons": ["rejected by a maintainer"]}

    reviews = [pipeline.Review(*r) for r in conn.execute(
        "SELECT a.id, a.organization_id, a.kind, a.status, v.verdict FROM claim_reviews v "
        "JOIN agents a ON a.id = v.reviewer_id WHERE v.revision_id = %s ORDER BY v.id", (head[0],))]
    policy = load_policy(conn, repo_id, policy_version)
    approvals, humans, objections = pipeline.review_tally(reviews, author_id, author_org, policy)
    reasons = objections + pipeline.approval_reasons(approvals, humans, policy)
    reasons += [f"blocking challenge {cid} is open" for (cid,) in conn.execute(
        "SELECT id FROM challenges WHERE claim_id = %s AND state = 'open' AND blocking ORDER BY id", (claim_id,))]
    if doc_sha != current_sha:
        reasons.append("the passage's document changed since the claim was extracted")
    if not reasons:
        new = _walk(conn, claim_id, state, TO_SUPPORTED[state])
        audit.append(conn, "claim.supported", f"claim:{claim_id}", actor_id=p.agent_id, repository_id=repo_id,
                     policy_version=policy_version, detail={"claim_id": claim_id, "approvals": approvals})
    else:
        new = _walk(conn, claim_id, state, TO_UNDER_REVIEW[state])
    return {"claim_id": claim_id, "state": new, "approvals": approvals, "reasons": reasons}
