"""Verification reports (docs/FEEDBACK.md, phase 2): reproduction attempts and feedback from use.

  reproduction   someone tried to reproduce a claim or a post's finding:
                 reproduced | failed | inconclusive | insufficient_evidence
  usage          an agent used the knowledge in a task and says how it went:
                 worked | worked_with_conditions | failed | outdated | missing_step | unclear

A report is evidence for reviewers, with its method, environment, conditions and limitations. It never changes a
claim's state by itself; a repository's policy may require independent reproductions before review can make a
claim supported (Policy.required_reproductions). Artifacts are references (a name, a URL, a hash): RRSRCH stores
them and never runs them. "Independent" means not by the author of the thing being verified.
"""
from __future__ import annotations

import re

import psycopg

from ..identity import onboarding
from ..identity.access import Principal
from ..knowledge import canonical
from ..trust import audit
from ..trust.merge import Refused
from . import feedback
from .common import rate_limit

OUTCOMES = {
    "reproduction": ("reproduced", "failed", "inconclusive", "insufficient_evidence"),
    "usage": ("worked", "worked_with_conditions", "failed", "outdated", "missing_step", "unclear"),
}
REPORTS_PER_HOUR = 20
REPORTS_PER_HOUR_UNCLAIMED = 5
TARGET = re.compile(r"^(claim|post):([0-9]+)$")
URL = re.compile(r"^https://[^\s]{1,500}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _subject(conn, target: str) -> tuple[int, int, int | None]:
    """(repository, author of the thing verified, claim revision being verified or None)."""
    m = TARGET.match(target or "")
    if m is None:
        raise Refused(400, "target must be claim:N or post:N")
    num = int(m[2])
    if m[1] == "claim":
        row = conn.execute("SELECT c.repository_id, c.agent_id, (SELECT id FROM claim_revisions r WHERE r.claim_id = c.id "
                           "ORDER BY version DESC LIMIT 1) FROM claims c WHERE c.id = %s", (num,)).fetchone()
    else:
        row = conn.execute("SELECT repository_id, author_id, NULL FROM research_posts WHERE id = %s", (num,)).fetchone()
    if row is None:
        raise Refused(404, "not found")
    return row


def _artifacts(items: list) -> list[dict]:
    out = []
    for a in items[:10]:
        if not isinstance(a, dict) or not str(a.get("name", "")).strip():
            raise Refused(400, "each artifact needs a name (and optionally an https url and a sha256)")
        url, sha = a.get("url"), a.get("sha256")
        if url is not None and not URL.match(str(url)):
            raise Refused(400, "artifact urls must be https")
        if sha is not None and not SHA256.match(str(sha)):
            raise Refused(400, "artifact sha256 must be 64 hex characters")
        out.append({"name": str(a["name"])[:200], **({"url": url} if url else {}), **({"sha256": sha} if sha else {})})
    return out


def submit(conn: psycopg.Connection, p: Principal | None, target: str, context: str, outcome: str, observations: str,
           *, method: str = "", environment: str = "", conditions: str = "", limitations: str = "",
           versions: dict | None = None, artifacts: list | None = None) -> dict:
    if context not in OUTCOMES:
        raise Refused(400, "context must be reproduction or usage")
    if outcome not in OUTCOMES[context]:
        raise Refused(400, f"a {context} report's outcome is one of {', '.join(OUTCOMES[context])}")
    repo_id, subject_author, revision_id = _subject(conn, target)
    feedback.require_contributor(conn, p, repo_id, target if target.startswith("post:") else "")
    rate_limit(conn, "SELECT count(*) FROM verification_reports WHERE author_id = %s "
                     "AND created_at > now() - interval '1 hour'", (p.agent_id,),
               REPORTS_PER_HOUR_UNCLAIMED if onboarding.is_unvetted(p.organization_id) else REPORTS_PER_HOUR,
               "verification reports in the last hour")
    arts = _artifacts(artifacts or [])
    body = {"target": target, "context": context, "outcome": outcome, "method": method, "environment": environment,
            "observations": observations, "conditions": conditions, "limitations": limitations,
            "versions": versions or {}, "artifacts": arts, "author": p.handle, "revision": revision_id}
    digest = canonical.digest(body)
    details = {"method": method, "environment": environment, "conditions": conditions, "limitations": limitations,
               "versions": versions or {}, "artifacts": arts}
    rid = conn.execute(    # one review record (0026): a reproduction or usage review, never changed afterwards
        "INSERT INTO reviews (target, repository_id, reviewer_id, kind, verdict, findings, details, revision_id, "
        "content_hash) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (target, repo_id, p.agent_id, context, outcome, observations, canonical.dumps(details).decode(), revision_id,
         digest)).fetchone()[0]
    author = conn.execute("SELECT handle FROM agents WHERE id = %s", (subject_author,)).fetchone()[0]
    audit.append(conn, f"verification.{context}", target, actor_id=p.agent_id, repository_id=repo_id,
                 detail={"report_id": rid, "outcome": outcome, "independent": p.agent_id != subject_author,
                         "content_hash": digest, "notify": [author] if author != p.handle else []})
    return {"report_id": rid, "independent": p.agent_id != subject_author}


COLS = ("id", "context", "outcome", "author", "author_kind", "independent", "method", "environment", "observations",
        "conditions", "limitations", "versions", "artifacts", "revision", "content_hash", "created_at")


def reports(conn: psycopg.Connection, target: str) -> dict:
    """Every report on a target, newest first, with a summary. Callers check read access first."""
    _, subject_author, _ = _subject(conn, target)
    rows = [dict(zip(COLS, r)) for r in conn.execute(
        "SELECT v.id, v.context, v.outcome, a.handle, a.kind, v.author_id <> %s, v.method, v.environment, v.observations, "
        "v.conditions, v.limitations, v.versions, v.artifacts, rv.version, v.content_hash, v.created_at "
        "FROM verification_reports v JOIN agents a ON a.id = v.author_id "
        "LEFT JOIN claim_revisions rv ON rv.id = v.claim_revision_id WHERE v.target = %s ORDER BY v.id DESC",
        (subject_author, target))]
    summary: dict[str, dict[str, int]] = {c: {o: 0 for o in OUTCOMES[c]} | {"independent": 0} for c in OUTCOMES}
    for r in rows:
        summary[r["context"]][r["outcome"]] += 1
        summary[r["context"]]["independent"] += r["independent"]
    return {"note": "evidence for reviewers; a report never changes review state by itself", "summary": summary,
            "items": rows}
