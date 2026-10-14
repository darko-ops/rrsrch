"""Collaboration endpoints (SPEC-v2 §18.1): discussions, challenges, review requests, research tasks,
subscriptions, notifications and contribution histories. Decisions live in rrsrch.collab."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException

from ..collab import challenges, discussions, feed, review_requests, tasks
from ..identity.access import Principal
from ..knowledge import query
from . import idempotency
from .identity_routes import conn, principal
from .trust_routes import _call

router = APIRouter(prefix="/v1")
After = Query(default=0, ge=0)
Limit = Query(default=50, ge=1, le=200)


class NewDiscussion(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    subject: str = "repo"
    body: str = Field(min_length=1, max_length=8000)


class NewMessage(BaseModel):
    kind: Literal["comment", "question", "answer", "evidence", "experiment_proposal"] = "comment"
    body: str = Field(min_length=1, max_length=8000)
    refs: list[Any] = Field(default_factory=list, max_length=20)


class NewChallenge(BaseModel):
    kind: Literal["contradiction", "missing_assumption", "evidence_problem", "scope", "other"]
    statement: str = Field(min_length=1, max_length=4000)
    evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    blocking: bool = True


class Resolution(BaseModel):
    outcome: Literal["upheld", "dismissed"]
    resolution: str = Field(min_length=1, max_length=4000)


class NewReviewRequest(BaseModel):
    reviewer: str


class NewTask(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    deliverable: str = Field(min_length=1, max_length=2000)
    budget: dict[str, Any] = Field(default_factory=dict)
    due_at: datetime | None = None


class TaskMove(BaseModel):
    to: Literal["authorized", "assigned", "in_progress", "awaiting_review", "completed", "failed", "canceled"]
    assignee: str | None = None


class TaskResponse(BaseModel):
    body: str = Field(min_length=1, max_length=8000)
    merge_request_id: int | None = None


class Target(BaseModel):
    target: str


def _readable_repo(c, p: Principal | None, owner: str, name: str) -> int:
    repo = query.get_repo(c, p, f"{owner}/{name}")
    if repo is None:
        raise HTTPException(404)
    return repo["id"]


# discussions

@router.post("/repos/{owner}/{name}/discussions", status_code=201)
def open_discussion(owner: str, name: str, body: NewDiscussion, request: Request,
                    p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    def go():
        did, mid = _call(discussions.open_discussion, c, p, f"{owner}/{name}", body.title, body.subject, body.body)
        return 201, {"ok": True, "discussion_id": did, "message_id": mid}
    return idempotency.run(request, c, p, body, go)


@router.get("/repos/{owner}/{name}/discussions")
def list_discussions(owner: str, name: str, subject: str | None = None, after: int = After, limit: int = Limit,
                     p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True} | discussions.list_for_repo(c, _readable_repo(c, p, owner, name), subject, after, limit)


@router.get("/discussions/{discussion_id}")
def get_discussion(discussion_id: int, after: int = After, limit: int = Query(default=100, ge=1, le=500),
                   p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True, "discussion": _call(discussions.get, c, p, discussion_id, after, limit)}


@router.post("/discussions/{discussion_id}/messages", status_code=201)
def post_message(discussion_id: int, body: NewMessage, request: Request, p: Principal | None = Depends(principal),
                 c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    def go():
        return 201, {"ok": True, "message_id": _call(discussions.post, c, p, discussion_id, body.kind, body.body,
                                                     body.refs)}
    return idempotency.run(request, c, p, body, go)


@router.post("/discussions/{discussion_id}/close")
def close_discussion(discussion_id: int, p: Principal | None = Depends(principal),
                     c: psycopg.Connection = Depends(conn)) -> dict:
    _call(discussions.close, c, p, discussion_id)
    return {"ok": True, "discussion_id": discussion_id, "state": "closed"}


@router.post("/messages/{message_id}/hide")
def hide_message(message_id: int, p: Principal | None = Depends(principal),
                 c: psycopg.Connection = Depends(conn)) -> dict:
    _call(discussions.hide, c, p, message_id)
    return {"ok": True, "message_id": message_id, "moderation": "hidden"}


# challenges

@router.post("/claims/{claim_id}/challenges", status_code=201)
def open_challenge(claim_id: int, body: NewChallenge, request: Request, p: Principal | None = Depends(principal),
                   c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    def go():
        cid = _call(challenges.open_challenge, c, p, claim_id, body.kind, body.statement, body.evidence, body.blocking)
        state = c.execute("SELECT state FROM claims WHERE id = %s", (claim_id,)).fetchone()[0]
        return 201, {"ok": True, "challenge_id": cid, "claim_state": state}
    return idempotency.run(request, c, p, body, go)


@router.get("/claims/{claim_id}/challenges")
def list_challenges(claim_id: int, p: Principal | None = Depends(principal),
                    c: psycopg.Connection = Depends(conn)) -> dict:
    if query.get_claim(c, p, claim_id) is None:
        raise HTTPException(404)
    return {"ok": True, "claim_id": claim_id, "challenges": challenges.list_for_claim(c, claim_id)}


@router.post("/challenges/{challenge_id}/resolve")
def resolve_challenge(challenge_id: int, body: Resolution, p: Principal | None = Depends(principal),
                      c: psycopg.Connection = Depends(conn)) -> dict:
    state = _call(challenges.resolve, c, p, challenge_id, body.outcome, body.resolution)
    return {"ok": True, "challenge_id": challenge_id, "state": body.outcome, "claim_state": state}


@router.post("/challenges/{challenge_id}/withdraw")
def withdraw_challenge(challenge_id: int, p: Principal | None = Depends(principal),
                       c: psycopg.Connection = Depends(conn)) -> dict:
    state = _call(challenges.withdraw, c, p, challenge_id)
    return {"ok": True, "challenge_id": challenge_id, "state": "withdrawn", "claim_state": state}


# review requests

@router.post("/merge-requests/{mr_id}/review-requests", status_code=201)
def request_review(mr_id: int, body: NewReviewRequest, p: Principal | None = Depends(principal),
                   c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True, "review_request_id": _call(review_requests.request, c, p, mr_id, body.reviewer)}


@router.post("/review-requests/{request_id}/decline")
def decline_review(request_id: int, p: Principal | None = Depends(principal),
                   c: psycopg.Connection = Depends(conn)) -> dict:
    _call(review_requests.decline, c, p, request_id)
    return {"ok": True, "review_request_id": request_id, "state": "declined"}


@router.get("/review-requests")
def my_review_requests(p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    if p is None:
        raise HTTPException(401, "authentication required")
    return {"ok": True, "items": review_requests.mine(c, p)}


# research tasks

@router.post("/repos/{owner}/{name}/tasks", status_code=201)
def open_task(owner: str, name: str, body: NewTask, request: Request, p: Principal | None = Depends(principal),
              c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    def go():
        tid = _call(tasks.open_task, c, p, f"{owner}/{name}", body.question, body.deliverable, body.budget,
                    body.due_at)
        return 201, {"ok": True, "task_id": tid, "state": "proposed"}
    return idempotency.run(request, c, p, body, go)


@router.get("/repos/{owner}/{name}/tasks")
def list_tasks(owner: str, name: str, state: str | None = None, after: int = After, limit: int = Limit,
               p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True} | tasks.list_for_repo(c, _readable_repo(c, p, owner, name), state, after, limit)


@router.get("/tasks/{task_id}")
def get_task(task_id: int, p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True, "task": _call(tasks.get, c, p, task_id)}


@router.post("/tasks/{task_id}/transition")
def move_task(task_id: int, body: TaskMove, p: Principal | None = Depends(principal),
              c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True, "task_id": task_id, "state": _call(tasks.transition, c, p, task_id, body.to, body.assignee)}


@router.post("/tasks/{task_id}/responses", status_code=201)
def respond(task_id: int, body: TaskResponse, request: Request, p: Principal | None = Depends(principal),
            c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    def go():
        return 201, {"ok": True, "response_id": _call(tasks.respond, c, p, task_id, body.body, body.merge_request_id)}
    return idempotency.run(request, c, p, body, go)


# subscriptions, notifications, contributions

@router.post("/subscriptions", status_code=201)
def subscribe(body: Target, p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    _call(feed.subscribe, c, p, body.target)
    return {"ok": True, "subscriptions": feed.subscriptions(c, p)}


@router.delete("/subscriptions")
def unsubscribe(target: str, p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    removed = _call(feed.unsubscribe, c, p, target)
    return {"ok": True, "removed": removed, "subscriptions": feed.subscriptions(c, p)}


@router.get("/notifications")
def notifications(after: int = After, limit: int = Limit, p: Principal | None = Depends(principal),
                  c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True} | _call(feed.notifications, c, p, after, limit)


@router.get("/agents/{handle}/contributions")
def contributions(handle: str, p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    got = feed.contributions(c, p, handle)
    if got is None:
        raise HTTPException(404)
    return {"ok": True} | got


