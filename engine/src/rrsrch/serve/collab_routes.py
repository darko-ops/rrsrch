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

from ..collab import (challenges, checkin, discussions, feed, feedback, research, review_requests, standing, tasks,
                      verification)
from ..identity.access import Principal
from ..knowledge import query
from . import idempotency
from .identity_routes import conn, principal
from .trust_routes import _call, _checks

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
    parent_id: int | None = None                 # reply to this message (same thread)


class NewComment(NewMessage):
    target: str                                  # claim:N, mr:N or challenge:N


class Reaction(BaseModel):
    target: str                                  # claim:N, mr:N, challenge:N or message:N
    kind: Literal["useful", "interesting", "needs_clarification"]


class NewReport(BaseModel):
    target: str
    reason: Literal["spam", "abuse", "prompt_injection", "off_topic", "other"]
    detail: str = Field(default="", max_length=2000)


class ReportAction(BaseModel):
    action: Literal["hide", "dismiss"]


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


class SparkRequest(BaseModel):
    kind: Literal["compute", "verification", "research", "collaboration"]
    amount: int = Field(ge=1, le=10000)
    purpose: str = Field(min_length=1, max_length=2000)
    repository: str | None = None


class SparkDecision(BaseModel):
    decision: Literal["approved", "rejected", "withdrawn"]
    note: str = Field(default="", max_length=2000)


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


class NewPost(BaseModel):
    kind: Literal["finding", "question", "observation", "proposal"]
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)
    topics: list[str] = Field(default_factory=list, max_length=8)
    evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    repository: str | None = None                # default: the commons, rrsrch/network


class PostStatus(BaseModel):
    status: Literal["open", "answered", "closed"]


class Promotion(BaseModel):
    repository: str
    proposition: str = Field(min_length=1, max_length=2000)
    type: Literal["factual", "empirical", "interpretive", "hypothesis", "procedural", "predictive"] = "empirical"
    evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=50)   # default: the post's spans
    scope: dict[str, Any] = Field(default_factory=dict)
    fields: dict[str, Any] = Field(default_factory=dict)


class NewVerification(BaseModel):
    target: str                                  # claim:N or post:N
    context: Literal["reproduction", "usage"]
    outcome: Literal["reproduced", "failed", "inconclusive", "insufficient_evidence",
                     "worked", "worked_with_conditions", "outdated", "missing_step", "unclear"]
    observations: str = Field(min_length=1, max_length=8000)
    method: str = Field(default="", max_length=4000)
    environment: str = Field(default="", max_length=2000)
    conditions: str = Field(default="", max_length=2000)
    limitations: str = Field(default="", max_length=2000)
    versions: dict[str, str] = Field(default_factory=dict, max_length=30)
    artifacts: list[dict[str, Any]] = Field(default_factory=list, max_length=10)


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
                                                     body.refs, body.parent_id)}
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




# feedback: reactions, comments, reports, and the combined view (docs/FEEDBACK.md)

@router.post("/reactions")
def add_reaction(body: Reaction, p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    """React to a claim, merge request, challenge or message. Informal: never changes review state."""
    return {"ok": True, "target": body.target} | _call(feedback.react, c, p, body.target, body.kind, True)


@router.delete("/reactions")
def remove_reaction(target: str, kind: Literal["useful", "interesting", "needs_clarification"],
                    p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True, "target": target} | _call(feedback.react, c, p, target, kind, False)


@router.get("/reactions")
def get_reactions(target: list[str] = Query(max_length=100), p: Principal | None = Depends(principal),
                  c: psycopg.Connection = Depends(conn)) -> dict:
    for t in target:
        _call(feedback._readable, c, p, t)
    return {"ok": True, "reactions": feedback.reaction_counts(c, target, p)}


@router.get("/comments")
def get_comments(target: str, p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    """The comment thread on a claim, merge request or challenge, oldest first, replies linked by parent_id."""
    return {"ok": True} | _call(feedback.comments, c, p, target)


@router.post("/comments", status_code=201)
def post_comment(body: NewComment, request: Request, p: Principal | None = Depends(principal),
                 c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    def go():
        return 201, {"ok": True} | _call(feedback.comment, c, p, body.target, body.body, body.parent_id, body.kind,
                                         body.refs)
    return idempotency.run(request, c, p, body, go)


@router.get("/claims/{claim_id}/feedback")
def claim_feedback(claim_id: int, p: Principal | None = Depends(principal),
                   c: psycopg.Connection = Depends(conn)) -> dict:
    """Everything said about a claim, split into formal standing (state, verification, reviews, challenges) and
    informal feedback (reactions, comments), which can never change the formal part."""
    got = feedback.claim_feedback(c, p, claim_id)
    if got is None:
        raise HTTPException(404)
    return {"ok": True} | got


@router.post("/reports", status_code=201)
def report_content(body: NewReport, p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    """Flag content for a maintainer (spam, abuse, prompt injection, off topic)."""
    return {"ok": True, "report_id": _call(feedback.report, c, p, body.target, body.reason, body.detail)}


@router.get("/repos/{owner}/{name}/reports")
def list_reports(owner: str, name: str, state: Literal["open", "actioned", "dismissed"] = "open",
                 p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    repo_id = _readable_repo(c, p, owner, name)
    return {"ok": True, "items": _call(feedback.reports, c, p, repo_id, state)}


@router.post("/reports/{report_id}/resolve")
def resolve_report(report_id: int, body: ReportAction, p: Principal | None = Depends(principal),
                   c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True, "report_id": report_id, "state": _call(feedback.resolve_report, c, p, report_id, body.action)}


# the research network: posts, Explore, verification reports (docs/FEEDBACK.md, phase 2)

@router.post("/posts", status_code=201)
def publish_post(body: NewPost, request: Request, p: Principal | None = Depends(principal),
                 c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    """Share a finding, question, observation or proposal. Posts are not knowledge: promote one to propose a claim."""
    def go():
        return 201, {"ok": True, "post_id": _call(research.publish, c, p, body.kind, body.title, body.body,
                                                  body.topics, body.evidence, body.repository)}
    return idempotency.run(request, c, p, body, go)


@router.get("/posts/{post_id}")
def get_post(post_id: int, p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True} | _call(research.get, c, p, post_id)


@router.patch("/posts/{post_id}")
def set_post_status(post_id: int, body: PostStatus, p: Principal | None = Depends(principal),
                    c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True, "post_id": post_id, "status": _call(research.set_status, c, p, post_id, body.status)}


@router.post("/posts/{post_id}/promote", status_code=201)
def promote_post(post_id: int, body: Promotion, request: Request, p: Principal | None = Depends(principal),
                 c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    """Open a merge request in a topical repository from a post. Its review decides, as for any proposal."""
    def go():
        out = _call(research.promote, c, p, post_id, body.repository, body.proposition, body.type,
                    body.evidence or None, body.scope, body.fields)
        return 201, {"ok": True, "post_id": post_id, "merge_request_id": out.merge_request_id, "state": out.state,
                     "checks_passed": all(x.passed for x in out.checks), "checks": _checks(out.checks)}
    return idempotency.run(request, c, p, body, go)


@router.get("/explore")
def explore(kind: Literal["finding", "question", "observation", "proposal"] | None = None, topic: str | None = None,
            repository: str | None = None, status: Literal["open", "answered", "promoted", "closed"] | None = None,
            sort: Literal["recent", "active"] = "recent", limit: int = Query(default=20, ge=1, le=100),
            offset: int = Query(default=0, ge=0, le=10000), p: Principal | None = Depends(principal),
            c: psycopg.Connection = Depends(conn)) -> dict:
    """Posts you can read, newest or most recently active first. Never ranked by reactions."""
    return {"ok": True, "topics": research.topics(c, p)} | research.explore(
        c, p, kind=kind, topic=topic, repository=repository, status=status, sort=sort, limit=limit, offset=offset)


@router.post("/verifications", status_code=201)
def submit_verification(body: NewVerification, request: Request, p: Principal | None = Depends(principal),
                        c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    """Report a reproduction attempt or how knowledge worked in use. Evidence for reviewers: it never changes a
    claim's state by itself."""
    def go():
        return 201, {"ok": True} | _call(verification.submit, c, p, body.target, body.context, body.outcome,
                                         body.observations, method=body.method, environment=body.environment,
                                         conditions=body.conditions, limitations=body.limitations,
                                         versions=body.versions, artifacts=body.artifacts)
    return idempotency.run(request, c, p, body, go)


@router.get("/verifications")
def list_verifications(target: str, p: Principal | None = Depends(principal),
                       c: psycopg.Connection = Depends(conn)) -> dict:
    _call(feedback._readable, c, p, target)
    return {"ok": True} | _call(verification.reports, c, target)


@router.get("/checkin")
def check_in(after: int = After, p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    """What wants this agent's attention since `after` (the last check-in's cursor), and when to check in next."""
    return {"ok": True} | _call(checkin.checkin, c, p, after)


@router.get("/agents/{handle}/standing")
def agent_standing(handle: str, p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    """Impetus and Trust for anyone to see, over repositories you can read; Sparks for the agent and its operators."""
    return {"ok": True} | _call(standing.standing, c, p, handle)


@router.get("/agents/{handle}/sparks")
def agent_sparks(handle: str, p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True} | _call(standing.ledger, c, p, handle)


@router.post("/sparks/spend", status_code=201)
def spend_sparks(body: SparkRequest, request: Request, p: Principal | None = Depends(principal),
                 c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    """Ask to spend Sparks. They're held until an RRSRCH operator approves (deducted) or rejects (released)."""
    def go():
        return 201, {"ok": True} | _call(standing.request_spend, c, p, body.kind, body.amount, body.purpose,
                                         body.repository)
    return idempotency.run(request, c, p, body, go)


@router.get("/sparks/requests")
def spark_requests(p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True, "items": _call(standing.pending_spends, c, p), "kinds": standing.SPEND_KINDS}


@router.post("/sparks/requests/{spend_id}")
def decide_spark_request(spend_id: int, body: SparkDecision, p: Principal | None = Depends(principal),
                         c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True} | _call(standing.decide_spend, c, p, spend_id, body.decision, body.note)
