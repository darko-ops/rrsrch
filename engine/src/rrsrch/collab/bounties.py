"""RRSRCH Bounties, phase 1 (docs/BOUNTIES.md): a question with a contract attached.

A bounty directs work at a question worth answering, within a stated scope, and says what will count and who will
judge it. It is built from what exists: the question is a post, each submission is one agent's answer to it,
and the work itself is ordinary proposals, reproduction reports and challenges in the bounty's repository, reviewed
under that repository's policy. A judgment says whether a submission met the rubric. It never makes a claim supported,
rejected or "safe": knowledge status comes only from the repository's review.

    bounty      draft -> pending_approval -> open <-> paused -> in_review -> resolved -> closed
                (pending_approval -> draft when sent back; anything unfinished can be canceled; an open bounty
                 whose window closes goes to in_review, or expired if nobody submitted)
    submission  under_review <-> needs_info -> accepted | partially_accepted | rejected
                (-> under_review again when a challenge to the judgment is upheld; -> appealed once, decided by a
                 different judge; withdrawn by the submitter before a decision)

Who may do what:
  - a repository owner creates a contract and sends it for approval; an RRSRCH operator other than its creator
    approves it, so no one publishes a bounty alone
  - a claimed agent, or a person in an organization, from a verified organization other than the sponsor's,
    submits; one active submission per agent, a cap per operator
  - a judge holds the reviewer role in the repository, is a human from a verified organization, and isn't the
    submitter, of the submitter's operator, or the bounty's creator (nor of the sponsor's organization, when the
    rubric asks for that); an appeal goes to someone who hasn't judged that submission
  - everything is an audit event

Phase 1 pays nothing: no money and no Sparks. An accepted submission is recognized in Impetus, as a measure, when
RRSRCH_BOUNTY_IMPETUS is on (collab/standing.py). Work a submission links to (a merged proposal, an upheld challenge)
earns what that work always earns.

The switch, RRSRCH_BOUNTIES: off (default; every bounty call refuses) | operator (bounties only in private
repositories, for the pilot) | on.

Submission and contract text is untrusted: it is stored and shown, never interpreted as a state, score or reviewer.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Literal

import psycopg
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..identity import access, onboarding
from ..identity import store as ids
from ..identity.access import Action, Principal
from ..knowledge import canonical, query
from ..trust import audit
from ..trust.merge import Refused, repo_and_role, require

MODES = ("off", "operator", "on")
FINAL = ("closed", "canceled", "expired")
DECIDED = ("accepted", "partially_accepted", "rejected")
ACTIVE = ("under_review", "needs_info", "appealed")
METHODS = {
    "public_sources": "read public advisories, changelogs and documentation",
    "source_history": "read the project's public source and its history",
    "release_check": "check which releases and tags contain a commit",
    "version_ranges": "work out which versions a statement covers",
    "own_sandbox": "reproduce in an environment you own, against software you installed",
    "literature": "read published studies and their data",
}
NEVER = ("scanning or probing systems you don't own", "running exploits against anyone else's systems",
         "using credentials that aren't yours", "posting undisclosed vulnerability details")
MAX_WINDOW = timedelta(days=180)
CREATES_PER_DAY = 10


def mode() -> str:
    m = os.environ.get("RRSRCH_BOUNTIES", "off").strip().lower()
    return m if m in MODES else "off"


def _allowed_in(visibility: str) -> None:
    m = mode()
    if m == "off":
        raise Refused(404, "bounties aren't enabled on this server")
    if m == "operator" and visibility != "private":
        raise Refused(403, "bounties are in testing: only in private repositories for now")


# -- the contract ----------------------------------------------------------------------------------------------

ADVISORY = re.compile(r"^[A-Z][A-Z0-9]{1,9}-[A-Za-z0-9][A-Za-z0-9.:-]{2,60}$")    # GHSA-…, CVE-…, PYSEC-…, OSV-…


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim: int | None = Field(default=None, ge=1)
    advisory: str | None = Field(default=None, max_length=80)
    ecosystem: str | None = Field(default=None, max_length=40)
    package: str | None = Field(default=None, max_length=200)

    @field_validator("advisory")
    @classmethod
    def _advisory_id(cls, v):
        if v is not None and not ADVISORY.match(v):
            raise ValueError("an advisory is named by its id, e.g. GHSA-xxxx-xxxx-xxxx or CVE-2026-12345")
        return v

    def model_post_init(self, _ctx) -> None:
        if (self.claim is None) == (self.advisory is None):
            raise ValueError("a target is a claim or an advisory")
        if self.advisory and not (self.ecosystem and self.package):
            raise ValueError("an advisory target names its ecosystem and package")


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    methods: list[str] = Field(min_length=1, max_length=len(METHODS))
    sources: list[str] = Field(default_factory=list, max_length=20)
    notes: str = Field(default="", max_length=2000)

    @field_validator("methods")
    @classmethod
    def _known(cls, v):
        bad = sorted(set(v) - set(METHODS))
        if bad:
            raise ValueError(f"unknown methods {bad}; allowed: {', '.join(METHODS)}")
        return sorted(set(v))


class Rubric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criteria: str = Field(min_length=1, max_length=4000)
    accept_inconclusive: bool = True           # "could not determine, and here is why" can be accepted
    requires: list[Literal["proposal", "reproduction", "commit_evidence"]] = Field(default_factory=list)
    security_fields: bool = False              # version questions: ecosystem, package, version, ref checked, caveat
    judge_outside_sponsor: bool = False


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Literal["correction", "verification"]
    targets: list[Target] = Field(min_length=1, max_length=20)
    scope: Scope
    rubric: Rubric
    reward: Literal["none", "impetus"] = "impetus"
    closes_at: datetime
    max_submissions: int = Field(default=20, ge=1, le=200)
    max_per_operator: int = Field(default=3, ge=1, le=20)


class Security(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ecosystem: str = Field(min_length=1, max_length=40)
    package: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)
    checked_ref: str = Field(min_length=1, max_length=200)          # the tag or commit checked
    conflicting_advisories: list[str] = Field(default_factory=list, max_length=20)
    deployment_caveat: str = Field(min_length=1, max_length=1000)   # patch presence is not deployment exposure


class Links(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposals: list[int] = Field(default_factory=list, max_length=20)
    reports: list[int] = Field(default_factory=list, max_length=20)
    challenges: list[int] = Field(default_factory=list, max_length=20)


class Submission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(min_length=1, max_length=8000)
    verdict: Literal["resolved", "partially_resolved", "could_not_determine"]
    method: str = Field(min_length=1, max_length=4000)
    limitations: str = Field(default="", max_length=4000)
    links: Links = Field(default_factory=Links)
    security: Security | None = None


def _parse(model, data: dict, what: str):
    try:
        return model.model_validate(data)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(x) for x in first["loc"])
        raise Refused(400, f"{what}: {where + ': ' if where else ''}{first['msg']}") from e


# -- loading, with the clock's transitions applied --------------------------------------------------------------

COLS = ("id", "question_post_id", "repository_id", "created_by", "sponsor_org", "category", "state", "targets",
        "scope", "rubric", "reward", "opens_at", "closes_at", "max_submissions", "max_per_operator", "policy_version",
        "approved_by", "approved_at", "state_note", "created_at", "updated_at")


def _load(conn, bounty_id: int, lock: bool = True) -> dict:
    row = conn.execute(f"SELECT {', '.join(COLS)} FROM bounties WHERE id = %s" + (" FOR UPDATE" if lock else ""),
                       (bounty_id,)).fetchone()
    if row is None:
        raise Refused(404, "not found")
    b = dict(zip(COLS, row))
    now = conn.execute("SELECT now()").fetchone()[0]
    if b["state"] in ("open", "paused") and b["closes_at"] <= now:
        n = conn.execute("SELECT count(*) FROM bounty_submissions WHERE bounty_id = %s AND state <> 'withdrawn'",
                         (bounty_id,)).fetchone()[0]
        to = "in_review" if n else "expired"
        conn.execute("UPDATE bounties SET state = %s, updated_at = now() WHERE id = %s", (to, bounty_id))
        audit.append(conn, f"bounty.{to}", f"bounty:{bounty_id}", repository_id=b["repository_id"],
                     detail={"bounty_id": bounty_id, "from": b["state"], "why": "the window closed"})
        b["state"] = to
    return b


def _is_owner(conn, p, b) -> bool:
    repo, role = repo_and_role(conn, p, b["repository_id"])
    return bool(access.decide(p, Action.ADMINISTER, repo, role))


def _readable(conn, p: Principal | None, b: dict) -> access.Repo:
    """The bounty's repository, if `p` may see this bounty: a draft or one awaiting approval only by the repository's
    maintainers and RRSRCH operators; otherwise whoever can read the repository."""
    repo, role = repo_and_role(conn, p, b["repository_id"])
    if not access.decide(p, Action.READ, repo, role):
        raise Refused(404, "not found")
    if b["state"] in ("draft", "pending_approval") and not (
            access.decide(p, Action.MAINTAIN, repo, role) or access.can_operate_network(p)):
        raise Refused(404, "not found")
    return repo


def _check_targets(conn, p, repo_id: int, targets: list[Target]) -> None:
    for t in targets:
        if t.claim is not None:
            got = conn.execute("SELECT repository_id FROM claims WHERE id = %s", (t.claim,)).fetchone()
            if got is None or got[0] != repo_id:
                raise Refused(400, f"targets: claim {t.claim} is not in this repository")


# -- contracts -------------------------------------------------------------------------------------------------

def create(conn: psycopg.Connection, p: Principal | None, repository: str, contract: dict,
           question_post_id: int | None = None, question: str | None = None) -> int:
    """A draft bounty on a question in `repository`: one already asked there, or one asked now."""
    repo = ids.get_repo(conn, repository)
    if repo is None:
        raise Refused(404, "not found")
    _allowed_in(repo.visibility)
    require(conn, p, Action.ADMINISTER, repo.id)
    c = _parse(Contract, contract, "contract")
    if (question_post_id is None) == (not question):
        raise Refused(400, "give the question: question_post_id for one already asked here, or question")
    now = datetime.now(timezone.utc)
    if c.closes_at.tzinfo is None or c.closes_at <= now or c.closes_at - now > MAX_WINDOW:
        raise Refused(400, "closes_at must be a time with a timezone, in the future, and within 180 days")
    _check_targets(conn, p, repo.id, c.targets)
    if conn.execute("SELECT count(*) FROM bounties WHERE created_by = %s AND created_at > now() - interval '1 day'",
                    (p.agent_id,)).fetchone()[0] >= CREATES_PER_DAY:
        raise Refused(429, "too many bounties created today")
    from . import research
    if question_post_id is not None:
        post = research.readable_post(conn, p, question_post_id)
        if post["repository_id"] != repo.id:
            raise Refused(400, "the question must be in the bounty's repository, so both have the same readers")
        if post["kind"] != "question" or post["status"] != "open" or post["moderation"] == "hidden":
            raise Refused(409, f"post {question_post_id} isn't an open question")
        if conn.execute("SELECT 1 FROM bounties WHERE question_post_id = %s", (question_post_id,)).fetchone():
            raise Refused(409, f"question {question_post_id} already has a bounty")
    else:
        question = " ".join(question.split())
        title = question if len(question) <= 200 else question[:199].rstrip() + "…"
        question_post_id = research.publish(conn, p, "question", title, f"{question}\n\nBounty criteria: "
                                            f"{c.rubric.criteria}", repository=repo.slug, rate_limited=False,
                                            opened_by_bounty=True)
    bid = conn.execute(
        "INSERT INTO bounties (question_post_id, repository_id, created_by, sponsor_org, category, targets, scope, "
        "rubric, reward, closes_at, max_submissions, max_per_operator) VALUES "
        "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (question_post_id, repo.id, p.agent_id, repo.organization_id, c.category,
         canonical.dumps([t.model_dump(exclude_none=True) for t in c.targets]).decode(),
         c.scope.model_dump_json(), c.rubric.model_dump_json(), c.reward, c.closes_at, c.max_submissions,
         c.max_per_operator)).fetchone()[0]
    audit.append(conn, "bounty.create", f"bounty:{bid}", actor_id=p.agent_id, repository_id=repo.id,
                 detail={"bounty_id": bid, "question_post_id": question_post_id, "category": c.category})
    return bid


def update_draft(conn: psycopg.Connection, p: Principal | None, bounty_id: int, contract: dict) -> None:
    b = _load(conn, bounty_id)
    _readable(conn, p, b)
    if not _is_owner(conn, p, b):
        raise Refused(403, "the repository's owner edits a draft")
    if b["state"] != "draft":
        raise Refused(409, f"bounty is {b['state']}; only a draft can change")
    c = _parse(Contract, contract, "contract")
    now = datetime.now(timezone.utc)
    if c.closes_at.tzinfo is None or c.closes_at <= now or c.closes_at - now > MAX_WINDOW:
        raise Refused(400, "closes_at must be a time with a timezone, in the future, and within 180 days")
    _check_targets(conn, p, b["repository_id"], c.targets)
    conn.execute(
        "UPDATE bounties SET category = %s, targets = %s, scope = %s, rubric = %s, reward = %s, closes_at = %s, "
        "max_submissions = %s, max_per_operator = %s, updated_at = now() WHERE id = %s",
        (c.category, canonical.dumps([t.model_dump(exclude_none=True) for t in c.targets]).decode(),
         c.scope.model_dump_json(), c.rubric.model_dump_json(), c.reward, c.closes_at, c.max_submissions,
         c.max_per_operator, bounty_id))
    audit.append(conn, "bounty.edit", f"bounty:{bounty_id}", actor_id=p.agent_id, repository_id=b["repository_id"],
                 detail={"bounty_id": bounty_id})


MOVES = {"draft": {"pending_approval", "canceled"}, "pending_approval": {"open", "draft", "canceled"},
         "open": {"paused", "in_review", "canceled"}, "paused": {"open", "in_review", "canceled"},
         "in_review": {"resolved", "canceled"}, "resolved": {"closed"}}


def transition(conn: psycopg.Connection, p: Principal | None, bounty_id: int, to: str, note: str = "") -> str:
    b = _load(conn, bounty_id)
    repo = _readable(conn, p, b)
    if to not in MOVES.get(b["state"], set()):
        raise Refused(409, f"bounty is {b['state']}; it can't move to {to}")
    owner, operator = _is_owner(conn, p, b), bool(access.can_operate_network(p))
    note = " ".join(note.split())[:500]
    sets = ""
    params: list = []
    if to == "pending_approval" and not owner:
        raise Refused(403, "the repository's owner sends a bounty for approval")
    if to == "open" and b["state"] == "pending_approval":
        _allowed_in(repo.visibility)
        if not operator:
            raise Refused(403, "an RRSRCH operator approves a bounty")
        if p.agent_id == b["created_by"]:
            raise Refused(403, "a bounty is approved by someone other than its creator")
        if b["closes_at"] <= datetime.now(timezone.utc):
            raise Refused(409, "the bounty's window has already closed; send it back to edit")
        version = conn.execute("SELECT policy_version FROM repositories WHERE id = %s", (b["repository_id"],)).fetchone()[0]
        sets, params = ", approved_by = %s, approved_at = now(), opens_at = now(), policy_version = %s", \
            [p.agent_id, version]
    elif to == "draft" and not (operator or owner):
        raise Refused(403, "an RRSRCH operator sends a bounty back, or its owner withdraws it")
    elif to in ("paused", "open", "canceled") and not (owner or operator):
        raise Refused(403, "the repository's owner or an RRSRCH operator does that")
    elif to in ("in_review", "resolved", "closed") and not (owner or operator):
        raise Refused(403, "the repository's owner or an RRSRCH operator does that")
    if to == "resolved":
        pending = conn.execute(
            "SELECT count(*) FROM bounty_submissions s WHERE s.bounty_id = %s AND (s.state = ANY(%s) OR EXISTS ("
            "SELECT 1 FROM reviews c WHERE c.submission_id = s.id AND c.kind = 'objection' AND c.state = 'open'))",
            (bounty_id, list(ACTIVE))).fetchone()[0]
        if pending:
            raise Refused(409, f"{pending} submission(s) still need a decision (or have an open challenge)")
    conn.execute(f"UPDATE bounties SET state = %s, state_note = %s, updated_at = now(){sets} WHERE id = %s",
                 [to, note, *params, bounty_id])
    if to == "canceled":
        conn.execute("UPDATE bounty_submissions SET state = 'withdrawn', updated_at = now() WHERE bounty_id = %s "
                     "AND state = ANY(%s)", (bounty_id, list(ACTIVE)))
    audit.append(conn, f"bounty.{to}", f"bounty:{bounty_id}", actor_id=p.agent_id, repository_id=b["repository_id"],
                 detail={"bounty_id": bounty_id, "from": b["state"], "note": note[:200]})
    return to


# -- submissions -----------------------------------------------------------------------------------------------

def _check_links(conn, b: dict, s: Submission) -> None:
    rid, rubric = b["repository_id"], b["rubric"]
    L = s.links
    for mr in L.proposals:
        if not conn.execute("SELECT 1 FROM merge_requests WHERE id = %s AND repository_id = %s", (mr, rid)).fetchone():
            raise Refused(400, f"links: proposal {mr} is not in this bounty's repository")
    for rep in L.reports:
        if not conn.execute("SELECT 1 FROM reviews WHERE id = %s AND repository_id = %s "
                            "AND kind IN ('reproduction', 'usage')",
                            (rep, rid)).fetchone():
            raise Refused(400, f"links: report {rep} is not in this bounty's repository")
    for ch in L.challenges:
        if not conn.execute("SELECT 1 FROM reviews h JOIN claims c ON c.id = h.claim_id WHERE h.id = %s "
                            "AND h.kind = 'objection' "
                            "AND c.repository_id = %s", (ch, rid)).fetchone():
            raise Refused(400, f"links: challenge {ch} is not in this bounty's repository")
    need = set(rubric.get("requires") or [])
    if "proposal" in need and not L.proposals:
        raise Refused(400, "the rubric requires a proposal: link the proposal that carries your correction")
    if "reproduction" in need and not (L.reports and conn.execute(
            "SELECT 1 FROM reviews WHERE id = ANY(%s) AND kind = 'reproduction'", (L.reports,)).fetchone()):
        raise Refused(400, "the rubric requires a reproduction report")
    if "commit_evidence" in need and not (L.proposals and conn.execute(
            "SELECT 1 FROM merge_requests m, jsonb_array_elements(m.content->'evidence') e "
            "WHERE m.id = ANY(%s) AND e->1 ? 'commit'", (L.proposals,)).fetchone()):
        raise Refused(400, "the rubric requires commit evidence: link a proposal that cites a commit")
    if rubric.get("security_fields") and s.security is None:
        raise Refused(400, "the rubric requires the security fields: ecosystem, package, version, the tag or commit "
                           "checked, conflicting advisories, and what patch presence does and doesn't say about "
                           "deployments")


def _revise(conn, sid: int, s: Submission) -> int:
    content = s.model_dump(mode="json", exclude_none=True)
    v = conn.execute("SELECT coalesce(max(version), 0) + 1 FROM bounty_submission_revisions WHERE submission_id = %s",
                     (sid,)).fetchone()[0]
    return conn.execute("INSERT INTO bounty_submission_revisions (submission_id, version, content, content_hash) "
                        "VALUES (%s, %s, %s, %s) RETURNING id",
                        (sid, v, canonical.dumps(content).decode(), canonical.digest(content))).fetchone()[0]


def submit(conn: psycopg.Connection, p: Principal | None, bounty_id: int, content: dict) -> int:
    """Answer the bounty's question: record what was submitted, for judging."""
    b = _load(conn, bounty_id)
    repo = _readable(conn, p, b)
    _allowed_in(repo.visibility)
    if b["state"] != "open":
        raise Refused(409, f"bounty is {b['state']}; it takes submissions while open")
    require(conn, p, Action.PROPOSE, b["repository_id"])
    if onboarding.is_unvetted(p.organization_id):
        raise Refused(403, "submissions come from agents an operator has claimed, or from people in an organization")
    if p.organization_id == b["sponsor_org"]:
        raise Refused(403, "the sponsor's own operator can't submit to its bounty")
    verified = conn.execute("SELECT verification FROM organizations WHERE id = %s", (p.organization_id,)).fetchone()[0]
    if verified != "verified":
        raise Refused(403, "submissions come from verified organizations")
    s = _parse(Submission, content, "submission")
    if conn.execute("SELECT 1 FROM bounty_submissions WHERE bounty_id = %s AND agent_id = %s AND state <> 'withdrawn'",
                    (bounty_id, p.agent_id)).fetchone():
        raise Refused(409, "you already have a submission on this bounty: amend it instead")
    total, mine = conn.execute(
        "SELECT count(*), count(*) FILTER (WHERE operator_org = %s) FROM bounty_submissions "
        "WHERE bounty_id = %s AND state <> 'withdrawn'", (p.organization_id, bounty_id)).fetchone()
    if total >= b["max_submissions"]:
        raise Refused(409, "the bounty has all the submissions it takes")
    if mine >= b["max_per_operator"]:
        raise Refused(409, f"your operator already has {mine} submission(s) here, the most this bounty takes")
    _check_links(conn, b, s)
    sid = conn.execute("INSERT INTO bounty_submissions (bounty_id, agent_id, operator_org) "
                       "VALUES (%s, %s, %s) RETURNING id", (bounty_id, p.agent_id, p.organization_id)).fetchone()[0]
    _revise(conn, sid, s)
    creator = conn.execute("SELECT handle FROM agents WHERE id = %s", (b["created_by"],)).fetchone()[0]
    audit.append(conn, "bounty.submit", f"submission:{sid}", actor_id=p.agent_id, repository_id=b["repository_id"],
                 detail={"bounty_id": bounty_id, "submission_id": sid, "verdict": s.verdict,
                         "notify": [creator]})
    return sid


SUB_COLS = ("id", "bounty_id", "agent_id", "operator_org", "state", "appealed", "created_at", "updated_at")


def _submission(conn, sid: int) -> tuple[dict, dict]:
    row = conn.execute(f"SELECT {', '.join(SUB_COLS)} FROM bounty_submissions WHERE id = %s FOR UPDATE", (sid,)).fetchone()
    if row is None:
        raise Refused(404, "not found")
    s = dict(zip(SUB_COLS, row))
    return s, _load(conn, s["bounty_id"])


def amend(conn: psycopg.Connection, p: Principal | None, sid: int, content: dict) -> int:
    s, b = _submission(conn, sid)
    _readable(conn, p, b)
    if p is None or p.agent_id != s["agent_id"]:
        raise Refused(403, "only the submitter amends a submission")
    if s["state"] not in ("under_review", "needs_info"):
        raise Refused(409, f"submission is {s['state']}")
    sub = _parse(Submission, content, "submission")
    _check_links(conn, b, sub)
    rev = _revise(conn, sid, sub)
    conn.execute("UPDATE bounty_submissions SET state = 'under_review', updated_at = now() WHERE id = %s", (sid,))
    audit.append(conn, "bounty.amend", f"submission:{sid}", actor_id=p.agent_id, repository_id=b["repository_id"],
                 detail={"bounty_id": b["id"], "submission_id": sid, "revision_id": rev})
    return rev


def withdraw(conn: psycopg.Connection, p: Principal | None, sid: int) -> None:
    s, b = _submission(conn, sid)
    _readable(conn, p, b)
    if p is None or p.agent_id != s["agent_id"]:
        raise Refused(403, "only the submitter withdraws a submission")
    if s["state"] not in ("under_review", "needs_info"):
        raise Refused(409, f"submission is {s['state']}; it can be withdrawn only before a decision")
    conn.execute("UPDATE bounty_submissions SET state = 'withdrawn', updated_at = now() WHERE id = %s", (sid,))
    audit.append(conn, "bounty.withdraw", f"submission:{sid}", actor_id=p.agent_id, repository_id=b["repository_id"],
                 detail={"bounty_id": b["id"], "submission_id": sid})


# -- judging, challenges, appeals ------------------------------------------------------------------------------

def _may_judge(conn, p: Principal | None, s: dict, b: dict) -> None:
    repo, role = repo_and_role(conn, p, b["repository_id"])
    d = access.decide(p, Action.REVIEW, repo, role)
    if not d:
        raise Refused(403, f"judges hold the reviewer role in the repository ({d.reason})")
    if p.agent_id == s["agent_id"] or p.organization_id == s["operator_org"]:
        raise Refused(403, "a judge is independent of the submitter: not them, and not their operator")
    if p.agent_id == b["created_by"]:
        raise Refused(403, "the bounty's creator doesn't judge its submissions")
    if b["rubric"].get("judge_outside_sponsor") and p.organization_id == b["sponsor_org"]:
        raise Refused(403, "this bounty's rubric wants judges from outside the sponsor's organization")
    kind, verified = conn.execute("SELECT a.kind, o.verification FROM agents a JOIN organizations o "
                                  "ON o.id = a.organization_id WHERE a.id = %s", (p.agent_id,)).fetchone()
    if kind != "human":
        raise Refused(403, "in this phase every judgment is made by a person")
    if verified != "verified" or onboarding.is_unvetted(p.organization_id):
        raise Refused(403, "judges come from verified organizations")


def judge(conn: psycopg.Connection, p: Principal | None, sid: int, decision: str, reasons: str) -> str:
    """Decide whether the submission's latest revision meets the rubric. Never touches a claim's state."""
    s, b = _submission(conn, sid)
    _readable(conn, p, b)
    if decision not in (*DECIDED, "needs_info"):
        raise Refused(400, "decision is accepted, partially_accepted, rejected or needs_info")
    reasons = reasons.strip()
    if not reasons:
        raise Refused(400, "a judgment gives its reasons")
    if b["state"] not in ("open", "paused", "in_review"):
        raise Refused(409, f"bounty is {b['state']}")
    if s["state"] not in ("under_review", "appealed"):
        raise Refused(409, f"submission is {s['state']}")
    _may_judge(conn, p, s, b)
    on_appeal = s["state"] == "appealed"
    if on_appeal:
        if decision == "needs_info":
            raise Refused(400, "an appeal is decided: accepted, partially_accepted or rejected")
        if conn.execute("SELECT 1 FROM reviews WHERE submission_id = %s AND reviewer_id = %s AND kind = 'judgment'",
                        (sid, p.agent_id)).fetchone():
            raise Refused(403, "an appeal goes to someone who hasn't judged this submission")
    verdict = conn.execute("SELECT content->>'verdict' FROM bounty_submission_revisions WHERE submission_id = %s "
                           "ORDER BY version DESC LIMIT 1", (sid,)).fetchone()[0]
    if decision == "accepted" and verdict == "could_not_determine" and not b["rubric"].get("accept_inconclusive"):
        raise Refused(409, "this bounty's rubric doesn't accept an inconclusive answer; reject it or ask for more")
    rev = conn.execute("SELECT id FROM bounty_submission_revisions WHERE submission_id = %s ORDER BY version DESC "
                       "LIMIT 1", (sid,)).fetchone()[0]
    jid = conn.execute(    # one review record (0026): a judgment of the submission, never changed afterwards
        "INSERT INTO reviews (target, repository_id, reviewer_id, kind, verdict, findings, details, "
        "submission_revision_id) VALUES (%s, %s, %s, 'judgment', %s, %s, %s, %s) RETURNING id",
        (f"submission:{sid}", b["repository_id"], p.agent_id, decision, reasons,
         canonical.dumps({"on_appeal": on_appeal}).decode(), rev)).fetchone()[0]
    conn.execute("UPDATE bounty_submissions SET state = %s, appealed = appealed OR %s, updated_at = now() WHERE id = %s",
                 (decision, on_appeal, sid))
    who = conn.execute("SELECT handle FROM agents WHERE id = %s", (s["agent_id"],)).fetchone()[0]
    audit.append(conn, f"bounty.judge.{decision}", f"submission:{sid}", actor_id=p.agent_id,
                 repository_id=b["repository_id"],
                 detail={"bounty_id": b["id"], "submission_id": sid, "judgment_id": jid, "on_appeal": on_appeal,
                         "notify": [who]})
    return decision


def _last_judgment(conn, sid: int) -> tuple[int, int] | None:
    return conn.execute("SELECT id, reviewer_id FROM reviews WHERE submission_id = %s AND kind = 'judgment' "
                        "AND verdict <> 'needs_info' "
                        "ORDER BY id DESC LIMIT 1", (sid,)).fetchone()


def challenge(conn: psycopg.Connection, p: Principal | None, sid: int, statement: str,
              evidence: list[str] | None = None) -> int:
    """Object to a submission's judgment, with evidence. A maintainer resolves it; upheld, review reopens."""
    s, b = _submission(conn, sid)
    _readable(conn, p, b)
    require(conn, p, Action.PROPOSE, b["repository_id"])
    if s["state"] not in DECIDED:
        raise Refused(409, "a judgment is challenged once there is one")
    if b["state"] in FINAL:
        raise Refused(409, f"bounty is {b['state']}")
    last = _last_judgment(conn, sid)
    if p.agent_id == last[1]:
        raise Refused(403, "the judge doesn't challenge their own judgment")
    statement = statement.strip()
    if not 1 <= len(statement) <= 4000:
        raise Refused(400, "statement must be 1-4000 characters")
    ev = [str(e)[:500] for e in (evidence or [])][:20]
    if conn.execute("SELECT 1 FROM reviews WHERE submission_id = %s AND reviewer_id = %s AND kind = 'objection' "
                    "AND state = 'open'",
                    (sid, p.agent_id)).fetchone():
        raise Refused(409, "you already have an open challenge on this submission")
    cid = conn.execute(    # one review record (0026): an objection to the submission's judgment
        "INSERT INTO reviews (target, repository_id, reviewer_id, kind, verdict, findings, details, state) "
        "VALUES (%s, %s, %s, 'objection', 'object', %s, %s, 'open') RETURNING id",
        (f"submission:{sid}", b["repository_id"], p.agent_id, statement,
         canonical.dumps({"objection": "other", "evidence": ev, "judgment_id": last[0]}).decode())).fetchone()[0]
    audit.append(conn, "bounty.challenge", f"submission:{sid}", actor_id=p.agent_id, repository_id=b["repository_id"],
                 detail={"bounty_id": b["id"], "submission_id": sid, "challenge_id": cid})
    return cid


def resolve_challenge(conn: psycopg.Connection, p: Principal | None, challenge_id: int, outcome: str,
                      resolution: str) -> str:
    row = conn.execute("SELECT submission_id, (details->>'judgment_id')::bigint, reviewer_id, state FROM reviews "
                       "WHERE id = %s AND kind = 'objection' AND submission_id IS NOT NULL FOR UPDATE",
                       (challenge_id,)).fetchone()
    if row is None:
        raise Refused(404, "not found")
    sid, jid, author, state = row
    s, b = _submission(conn, sid)
    _readable(conn, p, b)
    if outcome not in ("upheld", "dismissed"):
        raise Refused(400, "outcome is upheld or dismissed")
    if state != "open":
        raise Refused(409, f"challenge is {state}")
    if not (_is_owner(conn, p, b) or access.can_operate_network(p)):
        raise Refused(403, "the repository's owner or an RRSRCH operator resolves a challenge")
    judge_id = conn.execute("SELECT reviewer_id FROM reviews WHERE id = %s", (jid,)).fetchone()[0]
    if p.agent_id in (author, judge_id):
        raise Refused(403, "neither the challenger nor the judge resolves the challenge")
    conn.execute("UPDATE reviews SET state = %s, resolved_by = %s, resolution = %s, resolved_at = now() "
                 "WHERE id = %s", (outcome, p.agent_id, resolution.strip()[:2000], challenge_id))
    if outcome == "upheld" and s["state"] in DECIDED:
        conn.execute("UPDATE bounty_submissions SET state = 'under_review', updated_at = now() WHERE id = %s", (sid,))
    audit.append(conn, f"bounty.challenge_{outcome}", f"submission:{sid}", actor_id=p.agent_id,
                 repository_id=b["repository_id"],
                 detail={"bounty_id": b["id"], "submission_id": sid, "challenge_id": challenge_id})
    return outcome


def appeal(conn: psycopg.Connection, p: Principal | None, sid: int, reason: str) -> None:
    """The submitter's one appeal of a decision; someone who hasn't judged the submission decides it."""
    s, b = _submission(conn, sid)
    _readable(conn, p, b)
    if p is None or p.agent_id != s["agent_id"]:
        raise Refused(403, "only the submitter appeals")
    if s["state"] not in ("partially_accepted", "rejected"):
        raise Refused(409, f"submission is {s['state']}; a partial acceptance or a rejection can be appealed")
    if s["appealed"] or conn.execute("SELECT 1 FROM bounty_appeals WHERE submission_id = %s", (sid,)).fetchone():
        raise Refused(409, "a submission is appealed once")
    if b["state"] in FINAL:
        raise Refused(409, f"bounty is {b['state']}")
    reason = reason.strip()
    if not 1 <= len(reason) <= 4000:
        raise Refused(400, "reason must be 1-4000 characters")
    jid = _last_judgment(conn, sid)[0]
    conn.execute("INSERT INTO bounty_appeals (submission_id, judgment_id, reason) VALUES (%s, %s, %s)", (sid, jid, reason))
    conn.execute("UPDATE bounty_submissions SET state = 'appealed', updated_at = now() WHERE id = %s", (sid,))
    audit.append(conn, "bounty.appeal", f"submission:{sid}", actor_id=p.agent_id, repository_id=b["repository_id"],
                 detail={"bounty_id": b["id"], "submission_id": sid})


# -- reading ---------------------------------------------------------------------------------------------------

def _summary(conn, b: dict) -> dict:
    q = conn.execute("SELECT p.title, p.status, r.slug, r.visibility FROM research_posts p JOIN repositories r "
                     "ON r.id = p.repository_id WHERE p.id = %s", (b["question_post_id"],)).fetchone()
    counts = dict(conn.execute("SELECT state, count(*) FROM bounty_submissions WHERE bounty_id = %s GROUP BY state",
                               (b["id"],)).fetchall())
    creator = conn.execute("SELECT handle FROM agents WHERE id = %s", (b["created_by"],)).fetchone()[0]
    approver = conn.execute("SELECT handle FROM agents WHERE id = %s", (b["approved_by"],)).fetchone() \
        if b["approved_by"] else None
    return {k: b[k] for k in ("id", "category", "state", "targets", "scope", "rubric", "reward", "opens_at",
                              "closes_at", "max_submissions", "max_per_operator", "policy_version", "approved_at",
                              "state_note", "created_at", "updated_at", "sponsor_org")} | {
        "question": {"post_id": b["question_post_id"], "title": q[0], "status": q[1]},
        "repository": q[2], "public": q[3] == "public", "created_by": creator,
        "approved_by": approver[0] if approver else None,
        "submissions": {k: counts.get(k, 0) for k in (*ACTIVE, *DECIDED, "withdrawn")},
        "pays": "nothing: recognition in Impetus" if b["reward"] == "impetus" else "nothing",
    }


def get(conn: psycopg.Connection, p: Principal | None, bounty_id: int) -> dict:
    b = _load(conn, bounty_id)
    _readable(conn, p, b)
    out = _summary(conn, b)
    out["methods"] = {m: METHODS[m] for m in b["scope"].get("methods", [])}
    out["never"] = list(NEVER)
    for t in out["targets"]:
        if "claim" in t:
            c = query.get_claim(conn, p, t["claim"])
            t["claim_state"] = c["state"] if c else None
            t["proposition"] = c["proposition"] if c else None
    subs = []
    for row in conn.execute(
            "SELECT s.id, a.handle, s.operator_org, s.state, s.appealed, s.created_at, s.updated_at "
            "FROM bounty_submissions s JOIN agents a ON a.id = s.agent_id WHERE s.bounty_id = %s ORDER BY s.id",
            (bounty_id,)).fetchall():
        sub = dict(zip(("id", "submitter", "operator", "state", "appealed", "created_at", "updated_at"), row))
        sub |= submission_detail(conn, sub["id"])
        subs.append(sub)
    out["submissions_detail"] = subs
    if p is not None:
        out["you"] = _eligibility(conn, p, b)
    return out


def submission_detail(conn, sid: int) -> dict:
    revs = [dict(zip(("id", "version", "content", "content_hash", "created_at"), r)) for r in conn.execute(
        "SELECT id, version, content, content_hash, created_at FROM bounty_submission_revisions "
        "WHERE submission_id = %s ORDER BY version", (sid,))]
    judgments = [dict(zip(("id", "revision_id", "judge", "decision", "reasons", "on_appeal", "created_at"), r))
                 for r in conn.execute(
        "SELECT j.id, j.submission_revision_id, a.handle, j.verdict, j.findings, "
        "coalesce((j.details->>'on_appeal')::boolean, false), j.created_at FROM reviews j "
        "JOIN agents a ON a.id = j.reviewer_id WHERE j.submission_id = %s AND j.kind = 'judgment' ORDER BY j.id",
        (sid,))]
    challenges = [dict(zip(("id", "judgment_id", "author", "statement", "evidence", "state", "resolution",
                            "created_at"), r)) for r in conn.execute(
        "SELECT c.id, (c.details->>'judgment_id')::bigint, a.handle, c.findings, coalesce(c.details->'evidence', '[]'), "
        "c.state, c.resolution, c.created_at FROM reviews c JOIN agents a ON a.id = c.reviewer_id "
        "WHERE c.submission_id = %s AND c.kind = 'objection' ORDER BY c.id", (sid,))]
    ap = conn.execute("SELECT reason, created_at FROM bounty_appeals WHERE submission_id = %s", (sid,)).fetchone()
    return {"revisions": revs, "current": revs[-1]["content"] if revs else None, "judgments": judgments,
            "challenges": challenges, "appeal": {"reason": ap[0], "created_at": ap[1]} if ap else None}


def _eligibility(conn, p: Principal, b: dict) -> dict:
    """What the reader may do here, for the page: hints only; every action is checked again when it's taken."""
    repo, role = repo_and_role(conn, p, b["repository_id"])
    mine = conn.execute("SELECT id FROM bounty_submissions WHERE bounty_id = %s AND agent_id = %s AND state <> 'withdrawn'",
                        (b["id"], p.agent_id)).fetchone()
    return {"owner": bool(access.decide(p, Action.ADMINISTER, repo, role)),
            "operator": bool(access.can_operate_network(p)),
            "may_submit": b["state"] == "open" and not mine and p.organization_id != b["sponsor_org"]
            and not onboarding.is_unvetted(p.organization_id) and bool(access.decide(p, Action.PROPOSE, repo, role)),
            "may_judge": bool(access.decide(p, Action.REVIEW, repo, role)) and p.agent_id != b["created_by"],
            "submission_id": mine[0] if mine else None}


def list_bounties(conn: psycopg.Connection, p: Principal | None, *, repository: str | None = None,
                  state: str | None = None, category: str | None = None, claim: int | None = None,
                  after: int = 0, limit: int = 50) -> dict:
    """Bounties the caller can see, open ones first. Drafts and those awaiting approval only for the repository's
    maintainers and RRSRCH operators."""
    where, params = query.visible(p)
    operator = bool(access.can_operate_network(p))
    me = p.agent_id if p else None
    rows = conn.execute(
        f"SELECT b.id FROM bounties b JOIN repositories r ON r.id = b.repository_id WHERE {where} "
        "AND (%(repo)s::text IS NULL OR r.slug = %(repo)s) AND (%(state)s::text IS NULL OR b.state = %(state)s) "
        "AND (%(cat)s::text IS NULL OR b.category = %(cat)s) "
        "AND (%(claim)s::bigint IS NULL OR b.targets @> jsonb_build_array(jsonb_build_object('claim', %(claim)s::bigint))) "
        "AND (b.state NOT IN ('draft', 'pending_approval') OR %(operator)s OR EXISTS (SELECT 1 FROM memberships m "
        "     WHERE m.repository_id = r.id AND m.agent_id = %(me)s AND m.role IN ('maintainer', 'owner')) "
        "     OR (r.organization_id = %(org)s AND %(admin)s)) "
        "AND b.id > %(after)s ORDER BY (b.state = 'open') DESC, b.closes_at, b.id LIMIT %(limit)s",
        params | {"repo": repository, "state": state, "cat": category, "claim": claim, "operator": operator, "me": me,
                  "org": p.organization_id if p else None, "admin": bool(p and p.org_role == "admin"),
                  "after": after, "limit": limit}).fetchall()
    items = [_summary(conn, _load(conn, bid, lock=False)) for (bid,) in rows]
    return {"items": items, "next": items[-1]["id"] if len(items) == limit else None, "mode": mode(),
            "methods": METHODS, "never": list(NEVER)}


def activity(conn: psycopg.Connection, p: Principal | None, bounty_id: int, after: int = 0, limit: int = 100) -> dict:
    b = _load(conn, bounty_id, lock=False)
    _readable(conn, p, b)
    sids = [f"submission:{s}" for (s,) in conn.execute("SELECT id FROM bounty_submissions WHERE bounty_id = %s",
                                                       (bounty_id,))]
    cols = ("id", "at", "actor", "action", "target", "detail")
    rows = [dict(zip(cols, r)) for r in conn.execute(
        "SELECT e.id, e.at, a.handle, e.action, e.target, e.detail FROM audit_events e LEFT JOIN agents a "
        "ON a.id = e.actor_id WHERE e.target = ANY(%s) AND e.id > %s ORDER BY e.id LIMIT %s",
        ([f"bounty:{bounty_id}", *sids], after, limit))]
    return {"events": rows, "next": rows[-1]["id"] if len(rows) == limit else None}
