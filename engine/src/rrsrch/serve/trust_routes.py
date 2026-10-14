"""Review and merging endpoints (SPEC-v2 §18.1): merge requests, reviews, merges, events.

Permission and acceptance decisions live in rrsrch.trust.merge and the pure
modules it calls; these handlers translate between HTTP and those calls. A
refused merge is a 409 that lists every reason, and is itself recorded in the
audit chain.
"""
from __future__ import annotations

from typing import Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException

from ..identity import access
from ..identity import store as ids
from ..identity.access import Action, Principal
from ..trust import merge
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


def _call(fn, *args):
    try:
        return fn(*args)
    except merge.Refused as e:
        raise HTTPException(e.status, str(e)) from e


def _checks(checks) -> list[dict]:
    return [c.model_dump(mode="json") for c in checks]


@router.post("/merge-requests", status_code=201)
def open_merge_request(body: NewMergeRequest, p: Principal | None = Depends(principal),
                       c: psycopg.Connection = Depends(conn)) -> dict:
    out = _call(merge.open_request, c, p, body.repository, body.content, body.claim_id)
    return {"ok": True, "merge_request_id": out.merge_request_id, "state": out.state,
            "checks_passed": all(x.passed for x in out.checks), "checks": _checks(out.checks)}


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
