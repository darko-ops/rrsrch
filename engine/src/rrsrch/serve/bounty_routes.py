"""Bounty endpoints (docs/BOUNTIES.md §5): contracts, submissions, judgments, challenges and appeals.

The decisions live in rrsrch.collab.bounties; these handlers translate HTTP. Nothing a client sends sets a state,
a judge, an independence result or a recognition: the engine decides them. With RRSRCH_BOUNTIES off every call
refuses, and the list says so (`mode`).
"""
from __future__ import annotations

from typing import Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException

from ..collab import bounties
from ..identity.access import Principal
from . import idempotency
from .identity_routes import conn, principal
from .trust_routes import _call

router = APIRouter(prefix="/v1")


class NewBounty(BaseModel):
    repository: str
    question_post_id: int | None = None
    question: str | None = Field(default=None, min_length=1, max_length=2000)
    contract: dict[str, Any]


class DraftChange(BaseModel):
    contract: dict[str, Any]


class BountyMove(BaseModel):
    to: Literal["pending_approval", "open", "draft", "paused", "in_review", "resolved", "closed", "canceled"]
    note: str = Field(default="", max_length=500)


class NewSubmission(BaseModel):
    content: dict[str, Any]


class Judgment(BaseModel):
    decision: Literal["accepted", "partially_accepted", "rejected", "needs_info"]
    reasons: str = Field(min_length=1, max_length=4000)


class SubmissionChallenge(BaseModel):
    statement: str = Field(min_length=1, max_length=4000)
    evidence: list[str] = Field(default_factory=list, max_length=20)


class ChallengeResolution(BaseModel):
    outcome: Literal["upheld", "dismissed"]
    resolution: str = Field(default="", max_length=2000)


class Appeal(BaseModel):
    reason: str = Field(min_length=1, max_length=4000)


def _on():
    if bounties.mode() == "off":
        raise HTTPException(404, "bounties aren't enabled on this server")


@router.get("/bounties")
def list_bounties(repository: str | None = None,
                  state: Literal["draft", "pending_approval", "open", "paused", "in_review", "resolved", "closed",
                                 "canceled", "expired"] | None = None,
                  category: Literal["correction", "verification"] | None = None, claim: int | None = None,
                  after: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=100),
                  p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    """Bounties you can see, open ones first. `mode` says whether bounties are on here at all."""
    if bounties.mode() == "off":
        return {"ok": True, "mode": "off", "items": [], "next": None}
    return {"ok": True} | bounties.list_bounties(c, p, repository=repository, state=state, category=category,
                                                 claim=claim, after=after, limit=limit)


@router.get("/bounties/{bounty_id}")
def get_bounty(bounty_id: int, p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    _on()
    return {"ok": True, "bounty": _call(bounties.get, c, p, bounty_id)}


@router.get("/bounties/{bounty_id}/activity")
def bounty_activity(bounty_id: int, after: int = Query(default=0, ge=0), p: Principal | None = Depends(principal),
                    c: psycopg.Connection = Depends(conn)) -> dict:
    _on()
    return {"ok": True} | _call(bounties.activity, c, p, bounty_id, after)


@router.post("/bounties", status_code=201)
def create_bounty(body: NewBounty, request: Request, p: Principal | None = Depends(principal),
                  c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    """A draft bounty on a question in a repository you own. An RRSRCH operator approves it before it opens."""
    _on()

    def go():
        bid = _call(bounties.create, c, p, body.repository, body.contract, body.question_post_id, body.question)
        return 201, {"ok": True, "bounty_id": bid, "state": "draft"}
    return idempotency.run(request, c, p, body, go)


@router.patch("/bounties/{bounty_id}")
def edit_bounty(bounty_id: int, body: DraftChange, p: Principal | None = Depends(principal),
                c: psycopg.Connection = Depends(conn)) -> dict:
    _on()
    _call(bounties.update_draft, c, p, bounty_id, body.contract)
    return {"ok": True, "bounty_id": bounty_id}


@router.post("/bounties/{bounty_id}/transition")
def move_bounty(bounty_id: int, body: BountyMove, p: Principal | None = Depends(principal),
                c: psycopg.Connection = Depends(conn)) -> dict:
    _on()
    return {"ok": True, "bounty_id": bounty_id, "state": _call(bounties.transition, c, p, bounty_id, body.to, body.note)}


@router.post("/bounties/{bounty_id}/submissions", status_code=201)
def submit(bounty_id: int, body: NewSubmission, request: Request, p: Principal | None = Depends(principal),
           c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    """Take on the bounty's question: answer, verdict, method, limitations, and links to your proposals, reproduction
    reports and challenges in the bounty's repository."""
    _on()

    def go():
        sid = _call(bounties.submit, c, p, bounty_id, body.content)
        return 201, {"ok": True, "submission_id": sid, "state": "under_review"}
    return idempotency.run(request, c, p, body, go)


@router.get("/submissions/{submission_id}")
def get_submission(submission_id: int, p: Principal | None = Depends(principal),
                   c: psycopg.Connection = Depends(conn)) -> dict:
    _on()
    row = c.execute("SELECT bounty_id FROM bounty_submissions WHERE id = %s", (submission_id,)).fetchone()
    if row is None:
        raise HTTPException(404)
    b = _call(bounties.get, c, p, row[0])
    sub = next(s for s in b["submissions_detail"] if s["id"] == submission_id)
    return {"ok": True, "bounty_id": row[0], "submission": sub}


@router.post("/submissions/{submission_id}/revisions", status_code=201)
def amend(submission_id: int, body: NewSubmission, request: Request, p: Principal | None = Depends(principal),
          c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    _on()

    def go():
        return 201, {"ok": True, "revision_id": _call(bounties.amend, c, p, submission_id, body.content)}
    return idempotency.run(request, c, p, body, go)


@router.post("/submissions/{submission_id}/withdraw")
def withdraw(submission_id: int, p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    _on()
    _call(bounties.withdraw, c, p, submission_id)
    return {"ok": True, "submission_id": submission_id, "state": "withdrawn"}


@router.post("/submissions/{submission_id}/judgments", status_code=201)
def judge(submission_id: int, body: Judgment, p: Principal | None = Depends(principal),
          c: psycopg.Connection = Depends(conn)) -> dict:
    """Whether the submission meets the rubric, with reasons. It never changes any claim's review state."""
    _on()
    return {"ok": True, "submission_id": submission_id,
            "state": _call(bounties.judge, c, p, submission_id, body.decision, body.reasons)}


@router.post("/submissions/{submission_id}/challenges", status_code=201)
def challenge(submission_id: int, body: SubmissionChallenge, p: Principal | None = Depends(principal),
              c: psycopg.Connection = Depends(conn)) -> dict:
    _on()
    return {"ok": True, "challenge_id": _call(bounties.challenge, c, p, submission_id, body.statement, body.evidence)}


@router.post("/bounty-challenges/{challenge_id}/resolve")
def resolve(challenge_id: int, body: ChallengeResolution, p: Principal | None = Depends(principal),
            c: psycopg.Connection = Depends(conn)) -> dict:
    _on()
    return {"ok": True, "challenge_id": challenge_id,
            "state": _call(bounties.resolve_challenge, c, p, challenge_id, body.outcome, body.resolution)}


@router.post("/submissions/{submission_id}/appeal", status_code=201)
def appeal(submission_id: int, body: Appeal, p: Principal | None = Depends(principal),
           c: psycopg.Connection = Depends(conn)) -> dict:
    _on()
    _call(bounties.appeal, c, p, submission_id, body.reason)
    return {"ok": True, "submission_id": submission_id, "state": "appealed"}

