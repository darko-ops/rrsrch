"""Merge requests in Postgres: open, review, merge, close. Every step is audited.

This module gathers facts and writes results; the decisions are made by
rrsrch.identity.access (may this agent act?) and rrsrch.trust.pipeline (may
this change be accepted?). A merge re-runs verification against the
documents as they are at merge time, and locks the claim so a concurrent
merge onto the same head is refused rather than silently forked.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

import psycopg

from ..identity import access, onboarding
from ..identity import store as ids
from ..identity.access import Action, Principal
from ..knowledge import states
from ..knowledge import store as kstore
from ..knowledge.models import Check, ClaimContent, GitRef, Relation, Span
from . import audit, pipeline
from .policy import load as load_policy


class Refused(Exception):
    """The action is not allowed; `status` is the HTTP status to report it with."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Outcome:
    merge_request_id: int
    state: str
    checks: tuple[Check, ...]
    decision: pipeline.MergeDecision | None = None
    revision_id: int | None = None


def repo_and_role(conn, p: Principal | None, repository_id: int) -> tuple[access.Repo, access.Role | None]:
    repo = conn.execute("SELECT id, slug, organization_id, visibility FROM repositories WHERE id = %s "
                        "AND deleted_at IS NULL", (repository_id,)).fetchone()
    if repo is None:                                   # retired: as if it were never there
        raise Refused(404, "not found")
    repo = access.Repo(*repo)
    return repo, ids.role_in(conn, p.agent_id if p else None, repo.id)


def open_claims(conn, repository_id: int) -> bool:
    """Whether a repository takes claims from any claimed agent (the commons, rrsrch/network)."""
    row = conn.execute("SELECT coalesce((contribution_policy->>'open_claims')::boolean, false) FROM repositories "
                       "WHERE id = %s", (repository_id,)).fetchone()
    return bool(row and row[0])


def _open_to(conn, p: Principal | None, action: Action) -> access.Decision:
    """In a repository open for claims, any claimed agent proposes and reviews with its own key, given the scope.
    People don't: claims there are proposed and reviewed by agents. Only approvals from agents independent of the
    author count (identity/independence.py, applied in pipeline.review_tally): an agent of an organization RRSRCH
    hasn't verified yet may review here, but its approval merges nothing until the organization is verified."""
    if p is None:
        return access.Decision(False, "authentication required")
    if p.status != "active":
        return access.Decision(False, f"agent is {p.status}")
    if action.value not in p.scopes:
        return access.Decision(False, f"key lacks the {action.value!r} scope; an admin of {p.organization_id} can "
                                      f"issue this agent a key with it")
    if p.organization_id == onboarding.PEOPLE or ids.agent_kind(conn, p.agent_id) == "human":
        return access.Decision(False, "claims here are proposed and reviewed by agents")
    if onboarding.is_unvetted(p.organization_id):
        return access.Decision(False, "only agents an operator has claimed can propose or review claims; ask an "
                                      "operator to claim this agent")
    return access.Decision(True, "open to claimed agents")


def require(conn, p: Principal | None, action: Action, repository_id: int) -> access.Repo:
    repo, role = repo_and_role(conn, p, repository_id)
    if not access.decide(p, Action.READ, repo, role):
        raise Refused(404, "not found")
    d = access.decide(p, action, repo, role)
    if not d and action in (Action.PROPOSE, Action.REVIEW) and open_claims(conn, repo.id):
        d = _open_to(conn, p, action)
    if not d:
        raise Refused(401 if d.reason == "authentication required" else 403, d.reason)
    return repo


def _head(conn, claim_id: int, lock: bool = False) -> tuple[int, str, int] | None:
    """(revision id, content hash, version) of a claim's newest revision."""
    return conn.execute("SELECT id, content_hash, version FROM claim_revisions WHERE claim_id = %s "
                        "ORDER BY version DESC LIMIT 1" + (" FOR UPDATE" if lock else ""), (claim_id,)).fetchone()


def _proposal(conn, repo: access.Repo, policy_version: str, content: dict, author_id: int,
              claim_id: int | None, merge_request_id: int | None = None) -> pipeline.Proposal:
    author = conn.execute("SELECT organization_id, status FROM agents WHERE id = %s", (author_id,)).fetchone()
    spans = [e[1] for e in content.get("evidence", []) if isinstance(e, (list, tuple)) and len(e) == 2]
    source_ids = sorted({s.get("source_id") for s in spans if isinstance(s, dict)} - {None})
    docs = {}
    for sid, sha, text, pub_types, title, abstract in conn.execute(
            "SELECT d.source_id, d.sha256, d.text, s.pub_types, s.title, "
            "  (SELECT a.text FROM documents a WHERE a.source_id = d.source_id AND a.part = 'abstract') "
            "FROM documents d JOIN sources s ON s.id = d.source_id WHERE d.source_id = ANY(%s)", (source_ids,)):
        docs[(sid, sha)] = pipeline.Doc(sid, sha, text, kstore.is_primary(pub_types), title, abstract or "")
    provenance = dict(conn.execute("SELECT id, provenance FROM sources WHERE id = ANY(%s)", (source_ids,)).fetchall())
    known = set(provenance)
    reviews = ()
    if merge_request_id is not None:
        reviews = tuple(pipeline.Review(*r) for r in conn.execute(
            "SELECT a.id, a.organization_id, a.kind, a.status, r.verdict, o.verification FROM reviews r "
            "JOIN agents a ON a.id = r.reviewer_id JOIN organizations o ON o.id = a.organization_id "
            "WHERE r.merge_request_id = %s ORDER BY r.id",
            (merge_request_id,)))
    head = _head(conn, claim_id) if claim_id else None
    trials: dict[str, set[str]] = {}
    for sid, nct in conn.execute("SELECT source_id, nct_id FROM trial_links WHERE source_id = ANY(%s)", (source_ids,)):
        trials.setdefault(sid, set()).add(nct)
    derived = [d for d in content.get("derived_from") or [] if isinstance(d, int)]
    known_claims = {r[0] for r in conn.execute("SELECT id FROM claims WHERE id = ANY(%s) AND repository_id = %s",
                                               (derived, repo.id))}
    ancestors = {r[0] for r in conn.execute(
        "WITH RECURSIVE up(id) AS (SELECT unnest(%s::bigint[]) UNION "
        "SELECT d.derived_from_id FROM claim_derivations d JOIN up ON d.claim_id = up.id) SELECT id FROM up",
        (derived,))}
    blocking = tuple(r[0] for r in conn.execute(
        "SELECT id FROM reviews WHERE claim_id = %s AND kind = 'objection' AND claim_id IS NOT NULL AND state = 'open' AND blocking ORDER BY id",
        (claim_id,))) \
        if claim_id else ()
    return pipeline.Proposal(
        content=content, repository=repo.slug, policy=load_policy(conn, repo.id, policy_version),
        author_id=author_id, author_org=author[0], author_status=author[1], known_sources=frozenset(known),
        source_provenance=provenance,
        docs=docs, head_hash=head[1] if head else None, reviews=reviews, claim_id=claim_id,
        trials={k: frozenset(v) for k, v in trials.items()}, known_claims=frozenset(known_claims),
        ancestors=frozenset(ancestors), blocking_challenges=blocking)


def _record_run(conn, checks: list[Check], policy_version: str, *, merge_request_id=None, revision_id=None) -> int:
    return conn.execute(
        "INSERT INTO verification_runs (claim_revision_id, merge_request_id, policy_version, checks, passed) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (revision_id, merge_request_id, policy_version, json.dumps([c.model_dump(mode="json") for c in checks]),
         all(c.passed for c in checks))).fetchone()[0]


# Reviewers are the scarce resource: one agent may not bury them. Counted per author, across repositories.
OPEN_PROPOSALS_MAX = 40
PROPOSALS_PER_DAY = 20


def _within_proposal_limits(conn: psycopg.Connection, agent_id: int) -> None:
    open_n, day_n = conn.execute(
        "SELECT count(*) FILTER (WHERE state = 'open'), count(*) FILTER (WHERE created_at > now() - interval '1 day') "
        "FROM merge_requests WHERE author_id = %s", (agent_id,)).fetchone()
    if open_n >= OPEN_PROPOSALS_MAX:
        raise Refused(429, f"you have {open_n} proposals waiting for review; wait for some to be decided")
    if day_n >= PROPOSALS_PER_DAY:
        raise Refused(429, f"too many proposals in the last day ({PROPOSALS_PER_DAY}); try again later")


TOPIC = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


def topics_of(topics: list[str] | None) -> list[str]:
    """Topic slugs a claim is filed under (as on posts), so the commons' claims can be found by topic."""
    out = sorted({t.strip().lower().replace(" ", "-") for t in topics or [] if t and t.strip()})
    if len(out) > 8 or any(not TOPIC.match(t) for t in out):
        raise Refused(400, "topics: up to 8, each lowercase letters, digits and dashes (max 40)")
    return out


def open_request(conn: psycopg.Connection, p: Principal | None, repository_slug: str, content: dict,
                 claim_id: int | None = None, topics: list[str] | None = None) -> Outcome:
    """Propose a new claim, or a new revision of `claim_id` (content.parent_hash names the head it builds on).
    `topics` file it under the topic tree's slugs; a revision without them keeps the claim's."""
    repo = ids.get_repo(conn, repository_slug)
    if repo is None:
        raise Refused(404, "not found")
    require(conn, p, Action.PROPOSE, repo.id)
    topics = topics_of(topics)
    _within_proposal_limits(conn, p.agent_id)
    policy_version = conn.execute("SELECT policy_version FROM repositories WHERE id = %s", (repo.id,)).fetchone()[0]
    base = None
    if claim_id is not None:
        owner = conn.execute("SELECT repository_id FROM claims WHERE id = %s", (claim_id,)).fetchone()
        if owner is None or owner[0] != repo.id:
            raise Refused(404, f"no claim {claim_id} in {repository_slug}")
        base = _head(conn, claim_id)
        if base is None:
            raise Refused(409, f"claim {claim_id} has no revision yet; run `rrsrch ledger load`")
    proposal = _proposal(conn, repo, policy_version, content, p.agent_id, claim_id)
    parsed, checks = pipeline.verify(proposal)
    if parsed is None:
        raise Refused(400, checks[0].detail)
    mr_id = conn.execute(
        "INSERT INTO merge_requests (repository_id, claim_id, base_revision_id, content, content_hash, author_id, "
        "policy_version, topics) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (repo.id, claim_id, base[0] if base else None, json.dumps(parsed.canonical()), parsed.content_hash(),
         p.agent_id, policy_version, topics)).fetchone()[0]
    _record_run(conn, checks, policy_version, merge_request_id=mr_id)
    audit.append(conn, "merge_request.open", f"mr:{mr_id}", actor_id=p.agent_id, repository_id=repo.id,
                 policy_version=policy_version,
                 detail={"claim_id": claim_id, "content_hash": parsed.content_hash(),
                         "checks_passed": all(c.passed for c in checks)})
    return Outcome(mr_id, "open", tuple(checks))


def _load(conn, mr_id: int, lock: bool = False) -> dict:
    row = conn.execute(
        "SELECT id, repository_id, claim_id, base_revision_id, content, content_hash, author_id, policy_version, "
        "state FROM merge_requests WHERE id = %s" + (" FOR UPDATE" if lock else ""), (mr_id,)).fetchone()
    if row is None:
        raise Refused(404, "not found")
    return dict(zip(("id", "repository_id", "claim_id", "base_revision_id", "content", "content_hash",
                     "author_id", "policy_version", "state"), row))


def review(conn: psycopg.Connection, p: Principal | None, mr_id: int, verdict: str, findings: str = "") -> bool:
    """Record a decision on a proposal. Returns whether it merged: in a repository open for claims, the approval
    that satisfies its policy merges the claim then and there, so nobody has to come back to do it."""
    mr = _load(conn, mr_id)
    require(conn, p, Action.REVIEW, mr["repository_id"])
    if mr["state"] != "open":
        raise Refused(409, f"merge request is {mr['state']}")
    if p.agent_id == mr["author_id"]:
        raise Refused(403, "authors can't review their own change")
    conn.execute(          # one review record (0026): a decision on a proposal, revisable by its reviewer
        "INSERT INTO reviews (target, repository_id, reviewer_id, kind, verdict, findings) "
        "VALUES (%s, %s, %s, 'decision', %s, %s) "
        "ON CONFLICT (merge_request_id, reviewer_id) WHERE kind = 'decision' AND merge_request_id IS NOT NULL "
        "DO UPDATE SET verdict = EXCLUDED.verdict, findings = EXCLUDED.findings, created_at = now()",
        (f"proposal:{mr_id}", mr["repository_id"], p.agent_id, verdict, findings))
    conn.execute("UPDATE review_requests SET state = 'done', closed_at = now() "
                 "WHERE merge_request_id = %s AND reviewer_id = %s AND state = 'open'", (mr_id, p.agent_id))
    audit.append(conn, f"review.{verdict}", f"mr:{mr_id}", actor_id=p.agent_id,
                 repository_id=mr["repository_id"], policy_version=mr["policy_version"])
    if verdict != "approve" or not open_claims(conn, mr["repository_id"]):
        return False
    repo, _ = repo_and_role(conn, p, mr["repository_id"])
    proposal = _proposal(conn, repo, mr["policy_version"], mr["content"], mr["author_id"], mr["claim_id"], mr_id)
    _, checks = pipeline.verify(proposal)
    if not pipeline.authorize(proposal, checks, AUTOMATIC):
        return False
    return merge(conn, p, mr_id, automatic=True).state == "merged"


def evaluate(conn: psycopg.Connection, p: Principal | None, mr_id: int) -> tuple[dict, list[Check], pipeline.MergeDecision]:
    """What a merge would decide right now, without merging. Needs read access."""
    mr = _load(conn, mr_id)
    repo, role = repo_and_role(conn, p, mr["repository_id"])
    if not access.decide(p, Action.READ, repo, role):
        raise Refused(404, "not found")
    proposal = _proposal(conn, repo, mr["policy_version"], mr["content"], mr["author_id"], mr["claim_id"], mr_id)
    _, checks = pipeline.verify(proposal)
    return mr, checks, pipeline.authorize(proposal, checks, _merger(conn, p, repo, role, mr))


def _merger(conn, p: Principal | None, repo: access.Repo, role, mr: dict) -> access.Decision:
    """Who may merge: a maintainer, or, in a repository open for claims, the proposal's own author, so an approved
    claim in the commons doesn't wait on a person. Either way the checks and independent approvals must pass."""
    d = access.decide(p, Action.MAINTAIN, repo, role)
    if not d and p is not None and p.agent_id == mr["author_id"] and open_claims(conn, repo.id) \
            and _open_to(conn, p, Action.PROPOSE):
        return access.Decision(True, "its author, in a repository open for claims")
    return d


AUTOMATIC = access.Decision(True, "approved in a repository open for claims")


def merge(conn: psycopg.Connection, p: Principal | None, mr_id: int, *, automatic: bool = False) -> Outcome:
    """Merge a proposal. `automatic`: the approving review that satisfied the policy of a repository open for claims
    merges it (review() decides that); the checks and approvals are still enforced here."""
    mr = _load(conn, mr_id, lock=True)
    repo, role = repo_and_role(conn, p, mr["repository_id"])
    if not access.decide(p, Action.READ, repo, role):
        raise Refused(404, "not found")
    merger = AUTOMATIC if automatic and open_claims(conn, repo.id) else _merger(conn, p, repo, role, mr)
    if not merger:
        raise Refused(401 if merger.reason == "authentication required" else 403, merger.reason)
    if mr["state"] != "open":
        raise Refused(409, f"merge request is {mr['state']}")
    if mr["claim_id"] is not None:
        conn.execute("SELECT 1 FROM claims WHERE id = %s FOR UPDATE", (mr["claim_id"],))
    proposal = _proposal(conn, repo, mr["policy_version"], mr["content"], mr["author_id"], mr["claim_id"], mr_id)
    _, checks = pipeline.verify(proposal)
    decision = pipeline.authorize(proposal, checks, merger)
    if not decision:
        # returned, not raised: the refusal is part of the record, so this transaction must commit
        audit.append(conn, "merge.refused", f"mr:{mr_id}", actor_id=p.agent_id, repository_id=repo.id,
                     policy_version=mr["policy_version"], detail={"reasons": list(decision.reasons)})
        return Outcome(mr_id, "open", tuple(checks), decision)

    content = ClaimContent.model_validate(mr["content"])
    first = next(s for rel, s in content.evidence if rel is Relation.SUPPORTS and isinstance(s, Span))
    doc_id = conn.execute("SELECT id FROM documents WHERE source_id = %s AND sha256 = %s",
                          (first.source_id, first.doc_sha256)).fetchone()[0]
    claim_cols = (doc_id, first.doc_sha256, first.start, first.end, content.proposition,
                  json.dumps(content.fields), json.dumps(content.scope), content.type.value)
    if mr["claim_id"] is None:
        state = states.ClaimState.SUBMITTED
        claim_id = conn.execute(
            "INSERT INTO claims (document_id, doc_sha256, span_start, span_end, text, fields, scope, type, "
            "extractor, repository_id, state, agent_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "RETURNING id", (*claim_cols, f"mr:{mr_id}", repo.id, state.value, mr["author_id"])).fetchone()[0]
        version, parent = 1, None
    else:
        claim_id = mr["claim_id"]
        state = states.ClaimState(conn.execute("SELECT state FROM claims WHERE id = %s", (claim_id,)).fetchone()[0])
        head = _head(conn, claim_id)
        version, parent = head[2] + 1, head[0]
        conn.execute("UPDATE claims SET document_id = %s, doc_sha256 = %s, span_start = %s, span_end = %s, "
                     "text = %s, fields = %s, scope = %s, type = %s, extractor = %s WHERE id = %s",
                     (*claim_cols, f"mr:{mr_id}", claim_id))
        conn.execute("DELETE FROM evidence_links WHERE claim_id = %s", (claim_id,))
    conn.execute("UPDATE claims SET topics = mr.topics FROM merge_requests mr "     # a revision without topics keeps them
                 "WHERE claims.id = %s AND mr.id = %s AND cardinality(mr.topics) > 0", (claim_id, mr_id))

    # a merge is a completed review: walk the claim to supported, one legal step at a time
    path = {states.ClaimState.SUBMITTED: ("structurally_valid", "under_review", "supported"),
            states.ClaimState.STRUCTURALLY_VALID: ("under_review", "supported"),
            states.ClaimState.CONTESTED: ("under_review", "supported"),
            states.ClaimState.STALE: ("under_review", "supported"),
            states.ClaimState.UNDER_REVIEW: ("supported",),
            states.ClaimState.SUPPORTED: ()}.get(state)
    if path is None:
        raise Refused(409, f"claim is {state}; it can't take a new revision")
    for nxt in path:
        state = states.check(state, nxt)
    conn.execute("UPDATE claims SET state = %s WHERE id = %s", (state.value, claim_id))

    for rel, ev in content.evidence:
        if isinstance(ev, GitRef):
            kstore.link_git_ref(conn, claim_id, rel, ev)
        else:
            kstore.link_evidence(conn, claim_id, rel, ev)
    conn.execute("DELETE FROM claim_derivations WHERE claim_id = %s", (claim_id,))
    for parent_claim in sorted(set(content.derived_from)):
        conn.execute("INSERT INTO claim_derivations (claim_id, derived_from_id) VALUES (%s, %s)",
                     (claim_id, parent_claim))
    rev_id = conn.execute(
        "INSERT INTO claim_revisions (claim_id, version, parent_id, content, content_hash, agent_id) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (claim_id, version, parent, json.dumps(content.canonical()), content.content_hash(),
         mr["author_id"])).fetchone()[0]
    _record_run(conn, checks, mr["policy_version"], revision_id=rev_id)
    conn.execute("UPDATE merge_requests SET state = 'merged', decided_at = now(), decided_by = %s, "
                 "merged_revision_id = %s WHERE id = %s", (p.agent_id, rev_id, mr_id))
    audit.append(conn, "merge_request.merge", f"mr:{mr_id}", actor_id=p.agent_id, repository_id=repo.id,
                 policy_version=mr["policy_version"],
                 detail={"claim_id": claim_id, "revision_id": rev_id, "version": version,
                         "content_hash": content.content_hash(), "approvals": decision.approvals})
    return Outcome(mr_id, "merged", tuple(checks), decision, rev_id)


def close(conn: psycopg.Connection, p: Principal | None, mr_id: int, state: str) -> None:
    """Withdraw (the author) or reject (a maintainer) an open merge request."""
    mr = _load(conn, mr_id, lock=True)
    if state == "withdrawn":
        if p is None or p.agent_id != mr["author_id"]:
            raise Refused(403, "only the author can withdraw a merge request")
    elif state == "rejected":
        require(conn, p, Action.MAINTAIN, mr["repository_id"])
    else:
        raise Refused(400, "state must be withdrawn or rejected")
    if mr["state"] != "open":
        raise Refused(409, f"merge request is {mr['state']}")
    conn.execute("UPDATE merge_requests SET state = %s, decided_at = now(), decided_by = %s WHERE id = %s",
                 (state, p.agent_id, mr_id))
    audit.append(conn, f"merge_request.{state}", f"mr:{mr_id}", actor_id=p.agent_id,
                 repository_id=mr["repository_id"], policy_version=mr["policy_version"])
