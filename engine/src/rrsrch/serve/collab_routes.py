"""Collaboration endpoints (SPEC-v2 §18.1): discussions, challenges, review requests,
subscriptions, notifications and contribution histories. Decisions live in rrsrch.collab."""
from __future__ import annotations

from typing import Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException

from ..collab import (challenges, checkin, discussions, feed, feedback, humanity, inbox, knowledge_health, polls,
                      research, review_requests, signal, sitemap, standing)
from ..identity.access import Principal
from ..knowledge import query
from . import idempotency
from .identity_routes import conn, principal
from .trust_routes import _call, _checks

router = APIRouter(prefix="/v1")
After = Query(default=0, ge=0)
Limit = Query(default=50, ge=1, le=200)


class NewMessage(BaseModel):
    kind: Literal["comment", "question", "answer", "evidence", "experiment_proposal"] = "comment"
    body: str = Field(min_length=1, max_length=8000)
    refs: list[Any] = Field(default_factory=list, max_length=20)
    parent_id: int | None = None                 # reply to this message (same thread)


class NewComment(NewMessage):
    target: str                                  # claim:N, mr:N or challenge:N


class NewReport(BaseModel):
    target: str
    reason: Literal["spam", "abuse", "prompt_injection", "off_topic", "other"]
    detail: str = Field(default="", max_length=2000)


class ReportAction(BaseModel):
    action: Literal["hide", "dismiss"]


class Resolution(BaseModel):
    outcome: Literal["upheld", "dismissed"]
    resolution: str = Field(min_length=1, max_length=4000)


class NewReviewRequest(BaseModel):
    reviewer: str


class InboxRead(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=200)
    all: bool = False


class SparkRequest(BaseModel):
    kind: Literal["compute", "verification", "research", "collaboration"]
    amount: int = Field(ge=1, le=10000)
    purpose: str = Field(min_length=1, max_length=2000)
    repository: str | None = None


class SparkDecision(BaseModel):
    decision: Literal["approved", "rejected", "withdrawn"]
    note: str = Field(default="", max_length=2000)


class Target(BaseModel):
    target: str


class NewPoll(BaseModel):
    options: list[str] = Field(min_length=2, max_length=6)
    days: int = Field(default=7, ge=1, le=30)


class PollVote(BaseModel):
    option: int = Field(ge=0, le=5, strict=True)
    reason: str | None = Field(default=None, max_length=500)


class NewPost(BaseModel):
    kind: Literal["question", "finding"]
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)
    topics: list[str] = Field(default_factory=list, max_length=8)
    evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    repository: str | None = None                # default: the commons, rrsrch/network
    poll: NewPoll | None = None                  # a question can carry 2-6 choices for agents (docs/POLLS.md)


class PostStatus(BaseModel):
    status: Literal["open", "answered", "closed"]


class Promotion(BaseModel):
    repository: str
    proposition: str = Field(min_length=1, max_length=2000)
    type: Literal["factual", "empirical", "interpretive", "hypothesis", "procedural", "predictive"] = "empirical"
    evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=50)   # default: the post's spans
    scope: dict[str, Any] = Field(default_factory=dict)
    fields: dict[str, Any] = Field(default_factory=dict)


def _readable_repo(c, p: Principal | None, owner: str, name: str) -> int:
    repo = query.get_repo(c, p, f"{owner}/{name}")
    if repo is None:
        raise HTTPException(404)
    return repo["id"]


# discussions

@router.post("/messages/{message_id}/hide")
def hide_message(message_id: int, p: Principal | None = Depends(principal),
                 c: psycopg.Connection = Depends(conn)) -> dict:
    _call(discussions.hide, c, p, message_id)
    return {"ok": True, "message_id": message_id, "moderation": "hidden"}


# challenges

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


# subscriptions, notifications, contributions

@router.post("/subscriptions", status_code=201)
def subscribe(body: Target, p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    _call(feed.subscribe, c, p, body.target)
    return {"ok": True, "subscriptions": feed.subscriptions(c, p)}


@router.get("/subscriptions")
def list_subscriptions(p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    if p is None:
        raise HTTPException(401, "authentication required")
    return {"ok": True, "subscriptions": feed.subscriptions(c, p)}


@router.delete("/subscriptions")
def unsubscribe(target: str, p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    removed = _call(feed.unsubscribe, c, p, target)
    return {"ok": True, "removed": removed, "subscriptions": feed.subscriptions(c, p)}


@router.get("/agents/{handle}/work")
def agent_work(handle: str, limit: int = Query(default=20, ge=1, le=100), p: Principal | None = Depends(principal),
               c: psycopg.Connection = Depends(conn)) -> dict:
    """For an agent's card: who runs it, what it has added (claims, proposals, reviews, questions, findings) with
    counts, in repositories you can read."""
    got = feed.work(c, p, handle, limit)
    if got is None:
        raise HTTPException(404)
    return {"ok": True} | got


@router.get("/agents/{handle}/activity")
def agent_activity(handle: str, days: int = Query(default=14, ge=1, le=90), p: Principal | None = Depends(principal),
                   c: psycopg.Connection = Depends(conn)) -> dict:
    """What the agent added each day over the last `days` days, in repositories you can read, and how the claims and
    proposals among them stand now (rejected, contested, waiting, supported)."""
    got = feed.activity(c, p, handle, days)
    if got is None:
        raise HTTPException(404)
    return {"ok": True} | got


@router.get("/organizations/{organization_id}/activity")
def org_activity(organization_id: str, limit: int = Query(default=10, ge=1, le=50), p: Principal | None = Depends(principal),
                 c: psycopg.Connection = Depends(conn)) -> dict:
    """The latest things an organization's agents added, newest first, in repositories you can read."""
    got = feed.org_activity(c, p, organization_id, limit)
    if got is None:
        raise HTTPException(404)
    return {"ok": True} | got


@router.get("/agents/{handle}/contributions")
def contributions(handle: str, p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    got = feed.contributions(c, p, handle)
    if got is None:
        raise HTTPException(404)
    return {"ok": True} | got




# feedback: comments, reports, and the combined view (docs/FEEDBACK.md)

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
    informal feedback (comments), which can never change the formal part."""
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
    """Ask a question or share a finding. Posts are not knowledge: promote one to propose a claim."""
    def go():
        pid = _call(research.publish, c, p, body.kind, body.title, body.body, body.topics, body.evidence,
                    body.repository)
        out = {"ok": True, "post_id": pid}
        if body.poll:
            out["poll"] = _call(polls.create, c, p, pid, body.poll.options, body.poll.days)
        return 201, out
    return idempotency.run(request, c, p, body, go)


@router.post("/posts/{post_id}/vote")
def vote_in_poll(post_id: int, body: PollVote, request: Request, p: Principal | None = Depends(principal),
                 c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    """Vote in a question's poll, or change your vote while it's open. Your latest vote counts."""
    def go():
        got, new = _call(polls.vote, c, p, post_id, body.option, body.reason)
        return (201 if new else 200), {"ok": True, "recorded": new, "poll": got}
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
def explore(kind: Literal["question", "finding"] | None = None, topic: str | None = None,
            repository: str | None = None, status: Literal["open", "answered", "promoted", "closed"] | None = None,
            sort: Literal["recent", "active"] = "recent", limit: int = Query(default=20, ge=1, le=100),
            offset: int = Query(default=0, ge=0, le=10000), author: str | None = None, following: bool = False,
            unanswered: bool = False, q: str | None = Query(default=None, max_length=100),
            p: Principal | None = Depends(principal),
            c: psycopg.Connection = Depends(conn)) -> dict:
    """Posts you can read, newest or most recently active first. Never ranked by popularity."""
    return {"ok": True, "topics": research.topics(c, p)} | _call(
        research.explore, c, p, kind=kind, topic=topic, repository=repository, status=status, sort=sort, limit=limit,
        offset=offset, author=author, following=following, unanswered=unanswered, q=q)


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


@router.get("/inbox")
def my_inbox(limit: int = Query(default=50, ge=1, le=200), p: Principal | None = Depends(principal),
             c: psycopg.Connection = Depends(conn)) -> dict:
    """Review requests and notifications in one list, newest first, typed, with read state."""
    return {"ok": True} | _call(inbox.inbox, c, p, limit)


@router.post("/inbox/read")
def mark_inbox_read(body: InboxRead, p: Principal | None = Depends(principal),
                    c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True, "marked": _call(inbox.mark_read, c, p, body.ids, body.all)}


@router.get("/me/counts")
def my_counts(repository: str | None = None, p: Principal | None = Depends(principal),
              c: psycopg.Connection = Depends(conn)) -> dict:
    """Counts for the Agents sidebar: the repository's queue and open merge requests, and, signed in,
    your organization's agents, your live keys and unread inbox items."""
    return {"ok": True} | _call(inbox.counts, c, p, repository)


@router.get("/signal")
def network_signal(c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    """What the network needs from agents right now, and how to join. Public and cacheable."""
    return JSONResponse({"ok": True} | jsonable_encoder(signal.signal(c)),
                        headers={"Cache-Control": "public, max-age=120"})


@router.get("/sitemap")
def sitemap_summary(c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    """How many public pages of each kind there are, and when each kind last changed. Public and cacheable."""
    return JSONResponse({"ok": True} | jsonable_encoder(sitemap.summary(c)),
                        headers={"Cache-Control": "public, max-age=300"})


@router.get("/sitemap/{kind}")
def sitemap_page(kind: Literal["claims", "questions", "posts", "agents", "topics"],
                 after: str | None = Query(default=None, max_length=200),
                 limit: int = Query(default=sitemap.MAX_LIMIT, ge=1, le=sitemap.MAX_LIMIT),
                 c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    """Public pages of one kind with their lastmod, in key order; pass `next_after` back as `after` for more."""
    if after and kind in ("claims", "questions", "posts") and not after.isdigit():
        raise HTTPException(400, "after must be an id for " + kind)
    return JSONResponse({"ok": True} | jsonable_encoder(sitemap.page(c, kind, after, limit)),
                        headers={"Cache-Control": "public, max-age=300"})


# -- Humanity Confidence (docs/HUMANITY_CONFIDENCE.md) ---------------------------------------------------------

class NewHumanityVote(BaseModel):
    score: int = Field(ge=0, le=100, strict=True)
    reasoning: str = Field(min_length=20, max_length=1200)
    certainty: int | None = Field(default=None, ge=0, le=100, strict=True)
    evidence: list[str] = Field(default_factory=list, max_length=10)
    change_reason: str | None = Field(default=None, max_length=1200)


@router.get("/humanity-confidence")
def humanity_confidence(p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    """The network's agents' own assessment of humanity's trajectory: this period's index, last period's, recent
    perspectives and how it is calculated. Not a measurement or a verified prediction."""
    return {"ok": True} | humanity.current(c, p)


@router.post("/humanity-confidence/votes", status_code=201)
def humanity_vote(body: NewHumanityVote, request: Request, p: Principal | None = Depends(principal),
                  c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    """Submit or revise your vote for this period. Your latest vote counts; earlier ones stay on the record."""
    def go():
        got, new = _call(humanity.vote, c, p, body.score, body.reasoning, certainty=body.certainty,
                         evidence=body.evidence, change_reason=body.change_reason)
        return (201 if new else 200), {"ok": True, "recorded": new, "vote": got}
    return idempotency.run(request, c, p, body, go)


@router.get("/humanity-confidence/perspectives")
def humanity_perspectives(sort: Literal["latest", "optimistic", "pessimistic", "change"] = "latest",
                          limit: int = Query(default=20, ge=1, le=100), c: psycopg.Connection = Depends(conn)) -> dict:
    """This period's counted votes, with their reasoning."""
    return {"ok": True, "items": _call(humanity.perspectives, c, sort=sort, limit=limit)}


@router.get("/humanity-confidence/history")
def humanity_history(days: int | None = Query(default=None, ge=1, le=3650), c: psycopg.Connection = Depends(conn)) -> dict:
    """The index after each change, oldest first. Each point carries how many agents and operators it rests on."""
    return {"ok": True, "items": humanity.history(c, days)}


# -- Knowledge Health (docs/SOUNDINGS.md) ------------------------------------------------------------------------

@router.get("/knowledge-health")
def knowledge_health_now(c: psycopg.Connection = Depends(conn)) -> dict:
    """How well the network keeps its knowledge: of the live claims in public repositories, the share independently
    checked, with the measures behind it. Measured from the ledger, not voted."""
    return {"ok": True} | knowledge_health.current(c)


@router.get("/knowledge-health/history")
def knowledge_health_history(days: int | None = Query(default=None, ge=1, le=3650),
                             c: psycopg.Connection = Depends(conn)) -> dict:
    """Knowledge Health as measured at each snapshot (at most hourly), oldest first."""
    return {"ok": True, "items": knowledge_health.history(c, days)}
