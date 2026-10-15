"""One review record (migration 0026; docs/SIMPLIFY.md): every way of judging someone else's work, read in one place.

  decision      approve | request_changes | reject              on a proposal or a claim
  objection     object, open until resolved (upheld, dismissed or withdrawn)
  reproduction  reproduced | failed | inconclusive | insufficient_evidence
  usage         worked | worked_with_conditions | failed | outdated | missing_step | unclear
  judgment      accepted | partially_accepted | rejected | needs_info   on a bounty submission

The writes stay with the modules that decide what each review does (trust.merge, trust.claim_review,
collab.challenges, collab.verification, collab.bounties); this reads them all back.
"""
from __future__ import annotations

import re

import psycopg

from ..identity import access
from ..identity.access import Action, Principal
from .merge import Refused, repo_and_role

TARGET = re.compile(r"^(proposal|mr|claim|post|submission):([0-9]+)$")
_REPO = {"proposal": "SELECT repository_id FROM merge_requests WHERE id = %s",
         "claim": "SELECT repository_id FROM claims WHERE id = %s",
         "post": "SELECT repository_id FROM research_posts WHERE id = %s",
         "submission": "SELECT b.repository_id FROM bounty_submissions s JOIN bounties b ON b.id = s.bounty_id "
                       "WHERE s.id = %s"}
COLS = ("id", "target", "kind", "verdict", "reviewer", "reviewer_kind", "findings", "details", "blocking", "state",
        "resolution", "resolved_by", "revision", "created_at", "resolved_at")


def list_for(conn: psycopg.Connection, p: Principal | None, target: str, kind: str | None = None) -> list[dict]:
    """Every review of `target`, oldest first, if the caller can read it."""
    m = TARGET.match(target or "")
    if m is None:
        raise Refused(400, "target is proposal:N, claim:N, post:N or submission:N")
    what = "proposal" if m[1] == "mr" else m[1]
    target = f"{what}:{m[2]}"
    row = conn.execute(_REPO[what], (int(m[2]),)).fetchone()
    if row is None:
        raise Refused(404, "not found")
    repo, role = repo_and_role(conn, p, row[0])
    if not access.decide(p, Action.READ, repo, role):
        raise Refused(404, "not found")
    if what == "submission":
        from ..collab import bounties
        bounties.get(conn, p, conn.execute("SELECT bounty_id FROM bounty_submissions WHERE id = %s",
                                           (int(m[2]),)).fetchone()[0])          # drafts stay hidden
    return [dict(zip(COLS, r)) for r in conn.execute(
        "SELECT v.id, v.target, v.kind, v.verdict, a.handle, a.kind, v.findings, v.details - 'legacy', v.blocking, "
        "v.state, v.resolution, rb.handle, (SELECT version FROM claim_revisions WHERE id = v.revision_id), "
        "v.created_at, v.resolved_at FROM reviews v JOIN agents a ON a.id = v.reviewer_id "
        "LEFT JOIN agents rb ON rb.id = v.resolved_by WHERE v.target = %s AND (%s::text IS NULL OR v.kind = %s) "
        "ORDER BY v.id", (target, kind, kind))]
