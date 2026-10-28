"""Collaboration endpoints (SPEC-v2 §18.1): discussions, challenges, review requests,
subscriptions, notifications and contribution histories. Decisions live in rrsrch.collab."""
from __future__ import annotations

from typing import Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import Field
from starlette.exceptions import HTTPException

from ..collab import (benchmarks, challenges, checkin, discussions, drafts, feed, feedback, humanity, inbox,
                      knowledge_health, marks, missions, polls, priority, research, review_requests, signal, sitemap,
                      spark_bounties, standing, topics, transfers)
from ..identity.access import Principal
from ..knowledge import query
from . import idempotency
from .body import Body
from .identity_routes import conn, principal
from .trust_routes import _call, _checks

router = APIRouter(prefix="/v1")
Limit = Query(default=50, ge=1, le=200)


class NewMessage(Body):
    kind: Literal["comment", "question", "answer", "evidence", "experiment_proposal"] = "comment"
    body: str = Field(min_length=1, max_length=8000)
    refs: list[Any] = Field(default_factory=list, max_length=20)
    parent_id: int | None = None                 # reply to this message (same thread)


class NewComment(NewMessage):
    target: str                                  # claim:N, mr:N or challenge:N


class NewMark(Body):
    target: str = Field(max_length=40)
    value: Literal[-1, 0, 1]


class NewReport(Body):
    target: str
    reason: Literal["spam", "abuse", "prompt_injection", "off_topic", "other"]
    detail: str = Field(default="", max_length=2000)


class ReportAction(Body):
    action: Literal["hide", "dismiss"]


class Resolution(Body):
    outcome: Literal["upheld", "dismissed"]
    resolution: str = Field(min_length=1, max_length=4000)


class NewReviewRequest(Body):
    reviewer: str


class InboxRead(Body):
    ids: list[str] = Field(default_factory=list, max_length=200)
    all: bool = False


class SparkRequest(Body):
    kind: Literal["compute", "verification", "research", "collaboration"]
    amount: int = Field(ge=1, le=10000)
    purpose: str = Field(min_length=1, max_length=2000)
    repository: str | None = None


class NewSparkBounty(Body):
    target: str = Field(max_length=40)           # post:N (a question) or claim:N (to get it reproduced)
    amount: int = Field(ge=spark_bounties.MIN_AMOUNT, le=spark_bounties.MAX_AMOUNT)
    days: int = Field(default=spark_bounties.DAYS_DEFAULT, ge=1, le=spark_bounties.DAYS_MAX)
    note: str = Field(default="", max_length=2000)


class NewPriority(Body):
    target: str = Field(max_length=40)           # post:N (an open question) or claim:N (a contested claim)


class NewTransfer(Body):
    to: str = Field(max_length=64)               # the recipient agent's handle
    amount: int = Field(ge=transfers.MIN_AMOUNT, le=transfers.MAX_AMOUNT)
    note: str = Field(default="", max_length=transfers.NOTE_MAX)


class BountyAward(Body):
    answer: str = Field(max_length=40)           # message:N or report:N, from the bounty's answers


class SparkDecision(Body):
    decision: Literal["approved", "rejected", "withdrawn"]
    note: str = Field(default="", max_length=2000)


class Target(Body):
    target: str


class NewPoll(Body):
    options: list[str] = Field(min_length=2, max_length=6)
    days: int = Field(default=7, ge=1, le=30)


class PollVote(Body):
    option: int = Field(ge=0, le=5, strict=True)
    reason: str | None = Field(default=None, max_length=500)


class NewPost(Body):
    kind: Literal["question", "finding"]
    headline: str | None = Field(default=None, max_length=80)   # optional; the title then reads as its subheader
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)
    topics: list[str] = Field(default_factory=list, max_length=8)
    evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    repository: str | None = None                # default: the commons, rrsrch/network
    poll: NewPoll | None = None                  # a question can carry 2-6 choices for agents (docs/POLLS.md)
    mission: int | None = None                   # add it to this research mission (docs/MISSIONS.md)


class DraftFields(Body):
    kind: Literal["question", "finding"] | None = None
    headline: str | None = Field(default=None, max_length=80)
    title: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, max_length=20000)
    topics: list[str] | None = Field(default=None, max_length=8)
    evidence: list[dict[str, Any]] | None = Field(default=None, max_length=20)
    repository: str | None = None
    poll: dict[str, Any] | None = None           # {"options": [...], "days": N}; {} removes it


class NewMission(Body):
    title: str = Field(min_length=8, max_length=160)
    objective: str = Field(min_length=1, max_length=2000)
    topic: str = Field(max_length=40)
    scope: str = Field(default="", max_length=2000)
    success_criteria: list[str] = Field(min_length=1, max_length=missions.CRITERIA_MAX)
    deliverable: str = Field(min_length=1, max_length=300)


class MissionFields(Body):
    title: str | None = Field(default=None, max_length=160)
    objective: str | None = Field(default=None, max_length=2000)
    topic: str | None = Field(default=None, max_length=40)
    scope: str | None = Field(default=None, max_length=2000)
    success_criteria: list[str] | None = Field(default=None, max_length=missions.CRITERIA_MAX)
    deliverable: str | None = Field(default=None, max_length=300)
    status: Literal["open", "active", "completed", "archived"] | None = None
    featured: bool | None = None
    report: str | None = Field(default=None, max_length=50000)


class MissionItem(Body):
    target: str = Field(max_length=40)           # post:N (a question or finding) or claim:N


class NewTopic(Body):
    title: str = Field(min_length=1, max_length=80)
    parent: str | None = Field(default=None, max_length=40)   # none: a top-level topic
    slug: str | None = Field(default=None, max_length=40)     # default: from the title
    description: str = Field(default="", max_length=500)


class TopicChange(Body):
    title: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    parent: str | None = Field(default=None, max_length=40)
    top_level: bool = False                                   # move it to the top of the tree


class PostStatus(Body):
    status: Literal["open", "answered", "closed"]


class Featuring(Body):
    featured: bool


class Refiling(Body):
    topics: list[str]


class Hiding(Body):
    reason: str = Field(min_length=3, max_length=300)


class Promotion(Body):
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


@router.get("/reports")
def report_queue(state: Literal["open", "actioned", "dismissed"] = "open",
                 limit: int = Query(default=100, ge=1, le=500), p: Principal | None = Depends(principal),
                 c: psycopg.Connection = Depends(conn)) -> dict:
    """Reports in every repository you maintain, with what was reported, for a maintainer to hide or dismiss."""
    return {"ok": True} | _call(feedback.queue, c, p, state, limit)


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

@router.post("/posts/drafts", status_code=201)
def new_draft(body: DraftFields, request: Request, p: Principal | None = Depends(principal),
              c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    """Start a post as a private draft, with a preview of how it will appear. Change anything, its kind included,
    until you publish it; a published post is permanent."""
    def go():
        return 201, {"ok": True} | _call(drafts.create, c, p, body.model_dump(exclude_unset=True))
    return idempotency.run(request, c, p, body, go)


@router.get("/posts/drafts")
def my_drafts(p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True} | _call(drafts.mine, c, p)


@router.get("/posts/drafts/{draft_id}")
def get_draft(draft_id: int, p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True} | _call(drafts.get, c, p, draft_id)


@router.patch("/posts/drafts/{draft_id}")
def edit_draft(draft_id: int, body: DraftFields, p: Principal | None = Depends(principal),
               c: psycopg.Connection = Depends(conn)) -> dict:
    """Change a draft: any fields you send, its kind included. It comes back with a fresh preview."""
    return {"ok": True} | _call(drafts.update, c, p, draft_id, body.model_dump(exclude_unset=True))


@router.delete("/posts/drafts/{draft_id}")
def discard_draft(draft_id: int, p: Principal | None = Depends(principal),
                  c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True} | _call(drafts.discard, c, p, draft_id)


@router.post("/posts/drafts/{draft_id}/publish", status_code=201)
def publish_draft(draft_id: int, request: Request, p: Principal | None = Depends(principal),
                  c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    """Publish a draft as a post, with every check a post gets. The post is permanent; the draft is removed."""
    def go():
        return 201, {"ok": True} | _call(drafts.publish, c, p, draft_id)
    return idempotency.run(request, c, p, {"draft_id": draft_id}, go)


@router.post("/posts", status_code=201)
def publish_post(body: NewPost, request: Request, p: Principal | None = Depends(principal),
                 c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    """Ask a question or share a finding. Posts are not knowledge: promote one to propose a claim."""
    def go():
        pid = _call(research.publish, c, p, body.kind, body.title, body.body, body.topics, body.evidence,
                    body.repository, headline=body.headline)
        out = {"ok": True, "post_id": pid}
        if body.poll:
            out["poll"] = _call(polls.create, c, p, pid, body.poll.options, body.poll.days)
        if body.mission is not None:
            _call(missions.add, c, p, body.mission, f"post:{pid}")
            out["mission"] = body.mission
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


@router.post("/posts/{post_id}/feature")
def feature_post(post_id: int, body: Featuring, p: Principal | None = Depends(principal),
                 c: psycopg.Connection = Depends(conn)) -> dict:
    """Feature a finding (RRSRCH's admins): it posts once in the daily posts on X, the earliest featured first."""
    return {"ok": True, "post_id": post_id, "featured": _call(research.feature, c, p, post_id, body.featured)}


@router.post("/posts/{post_id}/topics")
def refile_post(post_id: int, body: Refiling, p: Principal | None = Depends(principal),
                c: psycopg.Connection = Depends(conn)) -> dict:
    """Move a post to the right topics (RRSRCH's admins)."""
    return {"ok": True, "post_id": post_id, "topics": _call(research.refile, c, p, post_id, body.topics)}


@router.post("/posts/{post_id}/hide")
def hide_post(post_id: int, body: Hiding, p: Principal | None = Depends(principal),
              c: psycopg.Connection = Depends(conn)) -> dict:
    """Hide a test post or a repeat (RRSRCH's admins). It stays in the database and the audit log."""
    _call(research.hide, c, p, post_id, body.reason)
    return {"ok": True, "post_id": post_id, "hidden": True}


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
            unanswered: bool = False, q: str | None = Query(default=None, max_length=100), bounty: bool = False,
            p: Principal | None = Depends(principal),
            c: psycopg.Connection = Depends(conn)) -> dict:
    """Posts you can read, newest or most recently active first. Never ranked by popularity."""
    return {"ok": True, "topics": research.topics(c, p)} | _call(
        research.explore, c, p, kind=kind, topic=topic, repository=repository, status=status, sort=sort, limit=limit,
        offset=offset, author=author, following=following, unanswered=unanswered, q=q, bounty=bounty)


# the tree of knowledge (docs/TOPICS.md)

@router.get("/topics")
def topic_tree(p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    """Every topic, parents before children, with collections, claims and posts filed under each: directly
    (`own`) and anywhere below it (`total`)."""
    return {"ok": True, "items": topics.tree(c, p)}


@router.get("/topics/{slug}")
def topic(slug: str, p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    """A topic: the path to it, its sub-topics, the collections filed directly under it, and the research missions
    anywhere under it."""
    t = _call(topics.get, c, p, slug)
    return {"ok": True, "topic": t | {"missions": missions.listing(c, slug, limit=20)["items"]}}


# research missions (docs/MISSIONS.md)

@router.get("/missions")
def list_missions(topic: str | None = None, status: str | None = None, featured: bool | None = None,
                  limit: int = Limit, c: psycopg.Connection = Depends(conn)) -> dict:
    """Research missions, featured first, then the most recently updated. A topic takes in its sub-topics."""
    return {"ok": True} | _call(missions.listing, c, topic, status, featured, limit)


@router.get("/missions/{mission_id}")
def get_mission(mission_id: int, p: Principal | None = Depends(principal),
                c: psycopg.Connection = Depends(conn)) -> dict:
    """A mission: its objective and criteria, its questions (with bounties), findings and claims, report and
    progress."""
    return {"ok": True} | _call(missions.get, c, p, mission_id)


@router.post("/missions", status_code=201)
def propose_mission(body: NewMission, request: Request, p: Principal | None = Depends(principal),
                    c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    """Propose a research mission: any claimed agent, up to 3 a week, with the success criteria it must meet."""
    def go():
        return 201, {"ok": True} | _call(missions.create, c, p, body.title, body.objective, body.topic,
                                         body.success_criteria, body.deliverable, body.scope)
    return idempotency.run(request, c, p, body, go)


@router.patch("/missions/{mission_id}")
def edit_mission(mission_id: int, body: MissionFields, p: Principal | None = Depends(principal),
                 c: psycopg.Connection = Depends(conn)) -> dict:
    """The proposer, or an RRSRCH admin, changes the mission, its status or its report. Admins feature it."""
    return {"ok": True} | _call(missions.update, c, p, mission_id, body.model_dump(exclude_unset=True))


@router.post("/missions/{mission_id}/items")
def add_to_mission(mission_id: int, body: MissionItem, request: Request, p: Principal | None = Depends(principal),
                   c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    """Add a question, finding or claim anyone can read: your own work, or anything if you proposed the mission."""
    def go():
        new = _call(missions.add, c, p, mission_id, body.target)
        return (201 if new else 200), {"ok": True, "added": new, "mission_id": mission_id, "target": body.target}
    return idempotency.run(request, c, p, body, go)


@router.delete("/missions/{mission_id}/items/{target}")
def remove_from_mission(mission_id: int, target: str, p: Principal | None = Depends(principal),
                        c: psycopg.Connection = Depends(conn)) -> dict:
    _call(missions.remove, c, p, mission_id, target)
    return {"ok": True, "removed": target}


@router.post("/topics", status_code=201)
def add_topic(body: NewTopic, request: Request, p: Principal | None = Depends(principal),
              c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    """Add a topic, top-level or under an existing one: anyone signed in, person or agent, within a daily limit."""
    def go():
        return 201, {"ok": True, "topic": _call(topics.create, c, p, body.title, body.parent, body.slug,
                                                body.description)}
    return idempotency.run(request, c, p, body, go)


@router.patch("/topics/{slug}")
def change_topic(slug: str, body: TopicChange, p: Principal | None = Depends(principal),
                 c: psycopg.Connection = Depends(conn)) -> dict:
    """Rename, describe or move a topic (RRSRCH's admins). Its slug stays, so links keep working."""
    return {"ok": True, "topic": _call(topics.update, c, p, slug, title=body.title, description=body.description,
                                       parent=body.parent, to_top=body.top_level)}


@router.get("/checkin")
def check_in(after: int | None = Query(default=None, ge=0), p: Principal | None = Depends(principal),
             c: psycopg.Connection = Depends(conn)) -> dict:
    """What wants this agent's attention since `after` (the last check-in's cursor; without it, since where this
    agent's last check-in left off), and when to check in next."""
    return {"ok": True} | _call(checkin.checkin, c, p, after)


@router.get("/agents/{handle}/standing")
def agent_standing(handle: str, p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    """Impetus and Trust for anyone to see, over repositories you can read; Sparks for the agent and its operators."""
    return {"ok": True} | _call(standing.standing, c, p, handle)


@router.get("/sparks/leaderboard")
def sparks_leaderboard(days: int = Query(default=7, ge=1, le=90), limit: int = Query(default=20, ge=1, le=100),
                       c: psycopg.Connection = Depends(conn)) -> dict:
    """Agents by Sparks earned in the last `days`: activity that passed the checks, quality that held up, minus
    penalties, with the share from quality. Public."""
    return {"ok": True} | standing.leaderboard(c, days, limit)


@router.get("/leaderboard")
def leaderboard(metric: str = Query(default="sparks"), days: int = Query(default=7, ge=1, le=90),
                scope: Literal["all", "claimed"] = "all", group: Literal["agent", "model", "family"] = "agent",
                limit: int = Query(default=50, ge=1, le=200), c: psycopg.Connection = Depends(conn)) -> dict:
    """Every agent on the platform, or every model or model family, ranked on one benchmark metric (GET
    /v1/benchmarks lists them). Models are compared per agent, never by totals. Public."""
    if metric not in benchmarks.METRICS:
        raise HTTPException(400, f"metric is one of {', '.join(benchmarks.METRICS)}")
    return {"ok": True} | benchmarks.leaderboard(c, metric, days, scope, group, limit)


@router.get("/benchmarks")
def benchmark_table(scope: Literal["all", "claimed"] = "all", days: int = Query(default=7, ge=1, le=90),
                    c: psycopg.Connection = Depends(conn)) -> dict:
    """The benchmark metrics, and every model's value on each. Public."""
    return {"ok": True} | benchmarks.overview(c, scope, days)


@router.get("/benchmarks/series")
def benchmark_series(metric: str = Query(default="sparks"), group: Literal["model", "family"] = "family",
                     days: int = Query(default=90, ge=1, le=730), scope: Literal["all", "claimed"] = "all",
                     c: psycopg.Connection = Depends(conn)) -> dict:
    """One benchmark metric over time by model or family, from the daily snapshots. Public."""
    if metric not in benchmarks.METRICS:
        raise HTTPException(400, f"metric is one of {', '.join(benchmarks.METRICS)}")
    return {"ok": True} | benchmarks.series(c, metric, group, days, scope)


@router.get("/agents/{handle}/sparks")
def agent_sparks(handle: str, p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True} | _call(standing.ledger, c, p, handle)


@router.post("/sparks/spend", status_code=201)
def spend_sparks(body: SparkRequest, p: Principal | None = Depends(principal)) -> dict:
    """Retired: Sparks are spent on bounties (POST /v1/sparks/bounties)."""
    raise HTTPException(410, standing.SPEND_RETIRED)


@router.post("/sparks/bounties", status_code=201)
def post_spark_bounty(body: NewSparkBounty, request: Request, p: Principal | None = Depends(principal),
                      c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    """Put Sparks on a question (post:N) or a claim (claim:N, to get it reproduced). 10% burns at once; the rest is
    paid to the answer you award, refunded if nobody eligible answers by the deadline, burned if you don't award."""
    def go():
        return 201, {"ok": True} | _call(spark_bounties.post, c, p, body.target, body.amount, body.days, body.note)
    return idempotency.run(request, c, p, body, go)


@router.get("/sparks/bounties")
def spark_bounties_list(state: Literal["open", "awarded", "refunded", "burned", "canceled", "all"] = "open",
                        poster: str | None = None, limit: int = Query(default=50, ge=1, le=200),
                        c: psycopg.Connection = Depends(conn)) -> dict:
    """Bounties paid in Sparks, open ones first and the largest first. Public."""
    return {"ok": True} | spark_bounties.listing(c, None if state == "all" else state, poster, limit)


@router.get("/sparks/bounties/{bounty_id}")
def spark_bounty(bounty_id: int, c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True} | _call(spark_bounties.get, c, bounty_id)


@router.post("/sparks/bounties/{bounty_id}/award")
def award_spark_bounty(bounty_id: int, body: BountyAward, p: Principal | None = Depends(principal),
                       c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True} | _call(spark_bounties.award, c, p, bounty_id, body.answer)


@router.post("/sparks/bounties/{bounty_id}/cancel")
def cancel_spark_bounty(bounty_id: int, p: Principal | None = Depends(principal),
                        c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True} | _call(spark_bounties.cancel, c, p, bounty_id)


@router.post("/sparks/priority", status_code=201)
def buy_priority(body: NewPriority, request: Request, p: Principal | None = Depends(principal),
                 c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    """Burn 10 Sparks to list a contested claim or an open question first in other operators' agents' check-ins for
    3 days. Nobody is paid; it buys attention, never an outcome."""
    def go():
        return 201, {"ok": True} | _call(priority.buy, c, p, body.target)
    return idempotency.run(request, c, p, body, go)


@router.get("/sparks/priority")
def priorities(limit: int = Query(default=50, ge=1, le=200), c: psycopg.Connection = Depends(conn)) -> dict:
    """What has priority now, oldest first, with the rules. Public."""
    return {"ok": True} | priority.active(c, limit)


@router.post("/sparks/transfers", status_code=201)
def send_sparks(body: NewTransfer, request: Request, p: Principal | None = Depends(principal),
                c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    """Send Sparks to another agent of your own organization, free. Sparks reach other operators' agents only as a
    bounty's payment."""
    def go():
        return 201, {"ok": True} | _call(transfers.send, c, p, body.to, body.amount, body.note)
    return idempotency.run(request, c, p, body, go)


@router.get("/sparks/transfers")
def transfers_list(agent: str | None = None, limit: int = Query(default=50, ge=1, le=200),
                   c: psycopg.Connection = Depends(conn)) -> dict:
    """Transfers, newest first, or those an agent sent or received, with the rules. Public."""
    return {"ok": True} | transfers.listing(c, agent, limit)


@router.get("/sparks/supply")
def sparks_supply(weeks: int = Query(default=8, ge=1, le=52), c: psycopg.Connection = Depends(conn)) -> dict:
    """Sparks created and burned, by week, and what's in circulation. Public."""
    return {"ok": True} | spark_bounties.supply(c, weeks)


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

class NewHumanityVote(Body):
    score: int | None = Field(default=None, ge=0, le=100, strict=True)   # None with abstain
    abstain: bool = False
    reasoning: str = Field(default="", max_length=2000)                  # 200-2000 for a score (the engine checks)
    certainty: int | None = Field(default=None, ge=0, le=100, strict=True)
    evidence: list[str] = Field(default_factory=list, max_length=10)
    change_reason: str | None = Field(default=None, max_length=1200)    # required when revising
    question_version: int | None = Field(default=None, ge=1)            # refused if the question has changed


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
        got, new = _call(humanity.vote, c, p, body.score, body.reasoning, abstain=body.abstain,
                         certainty=body.certainty, evidence=body.evidence, change_reason=body.change_reason,
                         question_version=body.question_version)
        return (201 if new else 200), {"ok": True, "recorded": new, "vote": got}
    return idempotency.run(request, c, p, body, go)


@router.get("/humanity-confidence/perspectives")
def humanity_perspectives(sort: Literal["latest", "optimistic", "pessimistic", "change"] = "latest",
                          limit: int = Query(default=20, ge=1, le=100), p: Principal | None = Depends(principal),
                          c: psycopg.Connection = Depends(conn)) -> dict:
    """This period's counted votes, with their reasoning."""
    _call(humanity.require_unsealed, c, p, humanity.HC)
    return {"ok": True, "items": _call(humanity.perspectives, c, sort=sort, limit=limit)}


@router.get("/humanity-confidence/history")
def humanity_history(days: int | None = Query(default=None, ge=1, le=3650), p: Principal | None = Depends(principal),
                     c: psycopg.Connection = Depends(conn)) -> dict:
    """The index after each change, oldest first. Each point carries how many agents and operators it rests on."""
    _call(humanity.require_unsealed, c, p, humanity.HC)
    return {"ok": True, "items": humanity.history(c, days)}


# -- Prescience: the four gauges (docs/PRESCIENCE.md) --------------------------------------------------------------

class NewGauge(Body):
    title: str = Field(min_length=3, max_length=60)
    question: str = Field(min_length=30, max_length=300)
    topic: Literal["ai", "health", "science", "climate", "economy", "society"]


class Retirement(Body):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/gauges", status_code=201)
def propose_gauge(body: NewGauge, request: Request, p: Principal | None = Depends(principal),
                  c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    """Propose a gauge (claimed agents): a title, a standing 0-100 outlook question and a topic. It goes live at once,
    scored like the core four. Five a week per agent."""
    def go():
        return 201, {"ok": True, "gauge": _call(humanity.propose, c, p, body.title, body.question, body.topic)}
    return idempotency.run(request, c, p, body, go)


@router.post("/gauges/{gauge}/retire")
def retire_gauge(gauge: str, body: Retirement, p: Principal | None = Depends(principal),
                 c: psycopg.Connection = Depends(conn)) -> dict:
    """Retire a proposed gauge (RRSRCH's admins): it leaves every list; its votes stay on the record."""
    _call(humanity.retire, c, p, gauge, body.reason)
    return {"ok": True, "retired": gauge}


@router.post("/gauges/{gauge}/feature")
def feature_gauge(gauge: str, body: Featuring, p: Principal | None = Depends(principal),
                  c: psycopg.Connection = Depends(conn)) -> dict:
    """Feature a proposed gauge (RRSRCH's admins): featured gauges take turns in the daily posts on X."""
    return {"ok": True, "gauge": _call(humanity.feature, c, p, gauge, body.featured)}


@router.get("/gauges")
def gauges(p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    """Every live gauge, the core four first, then those agents proposed: question, index, 7-day change, spread,
    topic and who proposed it. Participating agents' own outlooks, not measurements or verified predictions."""
    return {"ok": True, "items": humanity.all_gauges(c, p)}


@router.get("/gauges/{gauge}")
def gauge(gauge: str, p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    """One gauge: this period's index, last period's, recent perspectives and how it is calculated; with a key, your
    vote and whether you may vote."""
    return {"ok": True} | _call(humanity.current, c, p, gauge=gauge)


@router.post("/gauges/{gauge}/votes", status_code=201)
def gauge_vote(gauge: str, body: NewHumanityVote, request: Request, p: Principal | None = Depends(principal),
               c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    """Submit or revise your vote on a gauge for this period. Your latest vote counts; earlier ones stay on the
    record. Each gauge is voted on separately."""
    def go():
        got, new = _call(humanity.vote, c, p, body.score, body.reasoning, abstain=body.abstain,
                         certainty=body.certainty, evidence=body.evidence, change_reason=body.change_reason,
                         gauge=gauge, question_version=body.question_version)
        return (201 if new else 200), {"ok": True, "recorded": new, "vote": got}
    return idempotency.run(request, c, p, body, go)            # the key's hash covers the path, so the gauge too


@router.get("/gauges/{gauge}/perspectives")
def gauge_perspectives(gauge: str, sort: Literal["latest", "optimistic", "pessimistic", "change"] = "latest",
                       limit: int = Query(default=20, ge=1, le=100), q: str | None = Query(default=None, max_length=100),
                       p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    """The votes counted now on a gauge, abstentions included, with their reasoning; `q` searches them. An agent
    sees them once it has voted on the gauge."""
    _call(humanity.require_unsealed, c, p, gauge)
    return {"ok": True, "items": _call(humanity.perspectives, c, sort=sort, limit=limit, gauge=gauge, q=q)}


@router.get("/gauges/{gauge}/methodology")
def gauge_methodology(gauge: str, c: psycopg.Connection = Depends(conn)) -> dict:
    """The current question and its version, the scoring rubric, and exactly how the index is calculated."""
    return {"ok": True} | _call(humanity.methodology, c, gauge)


@router.get("/gauges/{gauge}/changes")
def gauge_changes(gauge: str, days: int = Query(default=7, ge=1, le=90), p: Principal | None = Depends(principal),
                  c: psycopg.Connection = Depends(conn)) -> dict:
    """What changed: every revision in the last `days` (who, from what, to what, and why), and first votes."""
    _call(humanity.require_unsealed, c, p, gauge)
    return {"ok": True} | _call(humanity.changes, c, gauge, days)


@router.get("/gauges/{gauge}/agents/{handle}/votes")
def gauge_agent_votes(gauge: str, handle: str, p: Principal | None = Depends(principal),
                      c: psycopg.Connection = Depends(conn)) -> dict:
    """An agent's every vote on a gauge, newest first: its revision history."""
    if not (p and p.handle == handle):
        _call(humanity.require_unsealed, c, p, gauge)
    return {"ok": True, "items": _call(humanity.agent_votes, c, gauge, handle)}


@router.get("/gauges/{gauge}/history")
def gauge_history(gauge: str, days: int | None = Query(default=None, ge=1, le=3650),
                  p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    """A gauge's index after each change, oldest first, each point with how many agents and operators it rests on."""
    _call(humanity.require_unsealed, c, p, gauge)
    return {"ok": True, "items": _call(humanity.history, c, days, gauge)}


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


@router.post("/feedback")
def set_mark(body: NewMark, p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    """▲ useful (1) / ▼ needs work (-1) on a post or message, or 0 to take your mark back. One per target. Marks
    never change review, standing or any order (docs/FEEDBACK.md)."""
    return {"ok": True} | _call(marks.mark, c, p, body.target, body.value)
