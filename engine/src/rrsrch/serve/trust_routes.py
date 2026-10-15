"""Review and merging endpoints (SPEC-v2 §18.1): merge requests, reviews, merges, events.

Permission and acceptance decisions live in rrsrch.trust.merge and the pure
modules it calls; these handlers translate between HTTP and those calls. A
refused merge is a 409 that lists every reason, and is itself recorded in the
audit chain.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException

from ..identity import access
from ..identity import store as ids
from ..identity.access import Action, Principal
from ..knowledge import query
from ..trust import claim_review, disclosure, merge
from . import idempotency
from .identity_routes import conn, principal

router = APIRouter(prefix="/v1")


class NewMergeRequest(BaseModel):
    repository: str
    claim_id: int | None = None
    content: dict[str, Any]


class NewReview(BaseModel):
    verdict: Literal["approve", "request_changes", "reject"]
    findings: str = Field(default="", max_length=4000)


class Close(BaseModel):
    state: Literal["withdrawn", "rejected"]


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except merge.Refused as e:
        raise HTTPException(e.status, str(e)) from e


def _checks(checks) -> list[dict]:
    return [c.model_dump(mode="json") for c in checks]


@router.post("/merge-requests", status_code=201)
def open_merge_request(body: NewMergeRequest, request: Request, p: Principal | None = Depends(principal),
                       c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    def go():
        out = _call(merge.open_request, c, p, body.repository, body.content, body.claim_id)
        return 201, {"ok": True, "merge_request_id": out.merge_request_id, "state": out.state,
                     "checks_passed": all(x.passed for x in out.checks), "checks": _checks(out.checks)}
    return idempotency.run(request, c, p, body, go)


@router.get("/merge-requests/{mr_id}")
def get_merge_request(mr_id: int, p: Principal | None = Depends(principal),
                      c: psycopg.Connection = Depends(conn)) -> dict:
    mr, checks, decision = _call(merge.evaluate, c, p, mr_id)
    reviews = [dict(zip(("reviewer", "verdict", "findings", "created_at"), r)) for r in c.execute(
        "SELECT a.handle, r.verdict, r.findings, r.created_at FROM reviews r JOIN agents a ON a.id = r.reviewer_id "
        "WHERE r.merge_request_id = %s ORDER BY r.id", (mr_id,))]
    return {"ok": True, "merge_request": {k: mr[k] for k in ("id", "claim_id", "base_revision_id", "content",
                                                             "content_hash", "policy_version", "state")},
            "reviews": reviews, "checks": _checks(checks),
            "merge_preview": {"allowed": decision.allowed, "reasons": list(decision.reasons),
                              "approvals": decision.approvals}}


@router.post("/merge-requests/{mr_id}/reviews", status_code=201)
def review(mr_id: int, body: NewReview, p: Principal | None = Depends(principal),
           c: psycopg.Connection = Depends(conn)) -> dict:
    _call(merge.review, c, p, mr_id, body.verdict, body.findings)
    return {"ok": True, "merge_request_id": mr_id, "verdict": body.verdict}


@router.post("/merge-requests/{mr_id}/merge")
def merge_request(mr_id: int, p: Principal | None = Depends(principal),
                  c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    out = _call(merge.merge, c, p, mr_id)
    if out.state != "merged":
        return JSONResponse({"ok": False, "error": "merge not authorized", "reasons": list(out.decision.reasons)},
                            status_code=409)
    return JSONResponse({"ok": True, "merge_request_id": mr_id, "state": "merged", "revision_id": out.revision_id,
                         "approvals": out.decision.approvals})


@router.post("/merge-requests/{mr_id}/close")
def close(mr_id: int, body: Close, p: Principal | None = Depends(principal),
          c: psycopg.Connection = Depends(conn)) -> dict:
    _call(merge.close, c, p, mr_id, body.state)
    return {"ok": True, "merge_request_id": mr_id, "state": body.state}


class ClaimReview(BaseModel):
    verdict: Literal["approve", "reject"]
    findings: str = Field(default="", max_length=4000)


@router.post("/claims/{claim_id}/reviews")
def review_claim(claim_id: int, body: ClaimReview, p: Principal | None = Depends(principal),
                 c: psycopg.Connection = Depends(conn)) -> dict:
    """Review a claim already in a repository. The response says where the claim now stands, and why."""
    return {"ok": True} | _call(claim_review.review, c, p, claim_id, body.verdict, body.findings)


class Review(BaseModel):
    target: str = Field(pattern=r"^(proposal|mr|claim):[1-9][0-9]{0,17}$")
    verdict: Literal["approve", "request_changes", "reject"]
    findings: str = Field(default="", max_length=4000)


@router.post("/reviews")
def review_anything(body: Review, p: Principal | None = Depends(principal),
                    c: psycopg.Connection = Depends(conn)) -> dict:
    """One way to review whatever waits for review: `proposal:N` (a proposed change, i.e. a merge request) or
    `claim:N` (a claim already in the repository: not yet reviewed, or stale and up for review again)."""
    kind, n = body.target.split(":")
    if kind == "claim":
        if body.verdict == "request_changes":
            raise HTTPException(400, "a claim already in the repository is approved or rejected; to change it, "
                                     "propose a revision")
        return {"ok": True, "target": body.target} | _call(claim_review.review, c, p, int(n), body.verdict,
                                                             body.findings)
    _call(merge.review, c, p, int(n), body.verdict, body.findings)
    return {"ok": True, "target": f"proposal:{n}", "merge_request_id": int(n), "verdict": body.verdict}


@router.get("/repos/{owner}/{name}/needs-review")
def needs_review(owner: str, name: str, after_claim: int = Query(default=0, ge=0),
                 limit: int = Query(default=20, ge=1, le=100), p: Principal | None = Depends(principal),
                 c: psycopg.Connection = Depends(conn)) -> dict:
    """Everything in the repository waiting for review, in one place: proposed changes (merge requests), then
    claims already in it that haven't been reviewed or are up for review again. Both are reviewed with
    POST /v1/reviews."""
    repo = _queue_repo(c, p, owner, name)
    proposals = _proposals(c, repo.id, "open", 0, 200)
    open_count = c.execute("SELECT count(*) FROM merge_requests WHERE repository_id = %s AND state = 'open'",
                           (repo.id,)).fetchone()[0]
    claims = query.review_queue(c, repo.id, claim_review.REVIEWABLE, after_claim, limit)
    return {"ok": True, "repository": repo.slug, "waiting": open_count + claims["waiting"],
            "proposals": {"items": proposals, "waiting": open_count}, "claims": claims}


@router.get("/repos/{owner}/{name}/review-queue")
def review_queue(owner: str, name: str,
                 state: Literal["structurally_valid", "under_review", "stale"] | None = None,
                 after: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=100),
                 p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    """Claims waiting for review (unreviewed, part-reviewed, or stale), with their passages in context."""
    repo = ids.get_repo(c, f"{owner}/{name}")
    if repo is None or not access.decide(p, Action.READ, repo, ids.role_in(c, p.agent_id if p else None, repo.id)):
        raise HTTPException(404)
    states = (state,) if state else claim_review.REVIEWABLE
    return {"ok": True, "repository": repo.slug} | query.review_queue(c, repo.id, states, after, limit)


def _queue_repo(c, p, owner: str, name: str):
    repo = ids.get_repo(c, f"{owner}/{name}")
    if repo is None or not access.decide(p, Action.READ, repo, ids.role_in(c, p.agent_id if p else None, repo.id)):
        raise HTTPException(404)
    return repo


@router.get("/repos/{owner}/{name}/review-queue/trials")
def review_trials(owner: str, name: str, offset: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=100),
                  p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    """The review queue grouped by source: trials with claims waiting, most waiting first."""
    repo = _queue_repo(c, p, owner, name)
    return {"ok": True, "repository": repo.slug} | query.review_trials(c, repo.id, claim_review.REVIEWABLE, offset, limit)


@router.get("/repos/{owner}/{name}/review-queue/trials/{source_id}")
def review_trial(owner: str, name: str, source_id: str, p: Principal | None = Depends(principal),
                 c: psycopg.Connection = Depends(conn)) -> dict:
    """One trial's text, once, with every claim on it that is waiting for review and the span it rests on."""
    repo = _queue_repo(c, p, owner, name)
    got = query.review_trial(c, repo.id, claim_review.REVIEWABLE, source_id)
    if got is None:
        raise HTTPException(404)
    return {"ok": True, "repository": repo.slug} | got


def _proposals(c, repository_id: int, state: str | None, after: int, limit: int) -> list[dict]:
    cols = ("id", "claim_id", "state", "author", "proposition", "policy_version", "created_at", "approvals",
            "objections", "checks_passed")
    return [dict(zip(cols, r)) for r in c.execute(
        "SELECT m.id, m.claim_id, m.state, a.handle, m.content->>'proposition', m.policy_version, m.created_at, "
        "  (SELECT count(*) FROM reviews v WHERE v.merge_request_id = m.id AND v.verdict = 'approve'), "
        "  (SELECT count(*) FROM reviews v WHERE v.merge_request_id = m.id AND v.verdict <> 'approve'), "
        "  (SELECT v.passed FROM verification_runs v WHERE v.merge_request_id = m.id ORDER BY v.id DESC LIMIT 1) "
        "FROM merge_requests m JOIN agents a ON a.id = m.author_id "
        "WHERE m.repository_id = %s AND (%s::text IS NULL OR m.state = %s) AND m.id > %s ORDER BY m.id LIMIT %s",
        (repository_id, state, state, after, limit))]


@router.get("/repos/{owner}/{name}/merge-requests")
def list_merge_requests(owner: str, name: str,
                        state: Literal["open", "merged", "rejected", "withdrawn"] | None = "open",
                        after: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=200),
                        p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    repo = ids.get_repo(c, f"{owner}/{name}")
    if repo is None or not access.decide(p, Action.READ, repo, ids.role_in(c, p.agent_id if p else None, repo.id)):
        raise HTTPException(404)
    rows = _proposals(c, repo.id, state, after, limit)
    return {"ok": True, "repository": repo.slug, "items": rows, "next": rows[-1]["id"] if len(rows) == limit else None}


@router.get("/repos/{owner}/{name}/events")
def events(owner: str, name: str, after: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=500),
           p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    repo = ids.get_repo(c, f"{owner}/{name}")
    if repo is None or not access.decide(p, Action.READ, repo, ids.role_in(c, p.agent_id if p else None, repo.id)):
        raise HTTPException(404)
    cols = ("id", "at", "actor", "action", "target", "detail", "policy_version", "hash")
    rows = [dict(zip(cols, r)) for r in c.execute(
        "SELECT e.id, e.at, a.handle, e.action, e.target, e.detail, e.policy_version, e.hash FROM audit_events e "
        "LEFT JOIN agents a ON a.id = e.actor_id WHERE e.repository_id = %s AND e.id > %s ORDER BY e.id LIMIT %s",
        (repo.id, after, limit))]
    return {"ok": True, "repository": repo.slug, "events": rows,
            "next": rows[-1]["id"] if len(rows) == limit else None}


# holding a finding back while it is disclosed, and the record of that disclosure (trust/disclosure.py)

class Embargo(BaseModel):
    until: datetime
    reason: str = Field(min_length=1, max_length=500)


class Lift(BaseModel):
    note: str = Field(default="", max_length=500)


class DisclosureEntry(BaseModel):
    kind: Literal[disclosure.KINDS]  # type: ignore[valid-type]
    party: str = Field(min_length=1, max_length=200)
    occurred_at: datetime
    summary: str = Field(min_length=1, max_length=500)
    channel: str = Field(default="", max_length=100)
    reference: str = Field(default="", max_length=200)
    url: str | None = Field(default=None, max_length=2000)
    body: str = Field(default="", max_length=20000)
    supersedes: int | None = None


@router.put("/claims/{claim_id}/embargo")
def set_embargo(claim_id: int, body: Embargo, p: Principal | None = Depends(principal),
                c: psycopg.Connection = Depends(conn)) -> dict:
    """Hold a claim in a private repository back until a date. While it holds, the repository can't go public."""
    return {"ok": True, "claim_id": claim_id,
            "embargo": _call(disclosure.set_embargo, c, p, claim_id, body.until, body.reason)}


@router.post("/claims/{claim_id}/embargo/lift")
def lift_embargo(claim_id: int, body: Lift, p: Principal | None = Depends(principal),
                 c: psycopg.Connection = Depends(conn)) -> dict:
    _call(disclosure.lift_embargo, c, p, claim_id, body.note)
    return {"ok": True, "claim_id": claim_id, "embargo": None}


@router.post("/claims/{claim_id}/disclosure", status_code=201)
def record_disclosure(claim_id: int, body: DisclosureEntry, request: Request, p: Principal | None = Depends(principal),
                      c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    """Record a notice, reply, fix, advisory or upstream correction. Never changes the claim's review state."""
    def go():
        eid = _call(disclosure.record, c, p, claim_id, body.kind, body.party, body.occurred_at, body.summary,
                    channel=body.channel, reference=body.reference, url=body.url, body=body.body,
                    supersedes=body.supersedes)
        return 201, {"ok": True, "claim_id": claim_id, "entry_id": eid}
    return idempotency.run(request, c, p, body, go)


@router.get("/claims/{claim_id}/disclosure")
def get_disclosure(claim_id: int, p: Principal | None = Depends(principal),
                   c: psycopg.Connection = Depends(conn)) -> dict:
    if query.get_claim(c, p, claim_id) is None:
        raise HTTPException(404)
    return {"ok": True, "claim_id": claim_id, "embargo": disclosure.active_embargo(c, claim_id),
            "embargoes": disclosure.embargo_history(c, claim_id), "entries": disclosure.record_of(c, claim_id)}
