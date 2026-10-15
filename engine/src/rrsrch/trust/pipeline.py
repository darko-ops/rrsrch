"""The validation pipeline and the merge decision (SPEC-v2 §10.2–10.4). Pure functions.

`verify` runs the checks a proposed claim must pass on its own (steps 2–7):
schema, policy, provenance, integrity, source, and the evidence gate. Source
independence counts papers reporting the same registered trial once, and a
claim may not derive from itself, directly or through other claims. Each
check names its kind, so passing one is never read as passing another.

`authorize` makes the merge decision (steps 7–9) from the checks, the reviews,
open blocking challenges and who is merging. It counts only independent approvals: never the author's
own, never from a suspended or revoked reviewer, and, if the policy says so,
never from the author's organization. Any standing objection from an
independent reviewer blocks the merge.

Nothing here reads the database or calls a model: given the same facts, the
same decision, every time. rrsrch.trust.merge gathers the facts.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from pydantic import ValidationError

from ..check import gate, profiles
from ..identity.access import Decision
from ..knowledge.models import Check, CheckKind, ClaimContent, GitRef, Relation, Span
from .policy import Policy


@dataclass(frozen=True)
class Doc:
    """A stored document, as it is now."""
    source_id: str
    sha256: str
    text: str
    is_primary: bool
    title: str = ""
    abstract: str = ""


@dataclass(frozen=True)
class Review:
    reviewer_id: int
    organization_id: str
    kind: str
    status: str
    verdict: str                      # approve | request_changes | reject


@dataclass(frozen=True)
class Proposal:
    content: Mapping                  # as submitted; validated here
    repository: str                   # slug of the repository it's proposed to
    policy: Policy
    author_id: int
    author_org: str
    author_status: str
    known_sources: frozenset[str]
    docs: Mapping[tuple[str, str], Doc]       # (source_id, sha256) -> current document
    head_hash: str | None = None              # the claim's current revision; None for a new claim
    reviews: tuple[Review, ...] = field(default_factory=tuple)
    claim_id: int | None = None               # the claim being revised; None for a new claim
    trials: Mapping[str, frozenset[str]] = field(default_factory=dict)   # source_id -> registered trials it reports
    known_claims: frozenset[int] = frozenset()          # derived_from ids that exist in this repository
    ancestors: frozenset[int] = frozenset()             # every claim reachable through derived_from, transitively
    blocking_challenges: tuple[int, ...] = ()           # open blocking challenges on the claim being revised


@dataclass(frozen=True)
class MergeDecision:
    allowed: bool
    reasons: tuple[str, ...]
    approvals: int

    def __bool__(self) -> bool:
        return self.allowed


def independent_sources(sources: set[str], trials: Mapping[str, frozenset[str]]) -> int:
    """How many independent sources: two papers reporting the same registered trial are one study."""
    parent = {s: s for s in sources}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    by_trial: dict[str, str] = {}
    for s in sources:
        for t in trials.get(s, ()):
            if t in by_trial:
                parent[find(s)] = find(by_trial[t])
            else:
                by_trial[t] = s
    return len({find(s) for s in sources})


def _check(kind: CheckKind, name: str, ok: bool, detail: str = "") -> Check:
    return Check(kind=kind, name=name, passed=ok, detail="" if ok else detail)


def verify(p: Proposal) -> tuple[ClaimContent | None, list[Check]]:
    S, P, I, SRC, F = (CheckKind.STRUCTURAL, CheckKind.PROVENANCE, CheckKind.INTEGRITY, CheckKind.SOURCE,
                       CheckKind.FACTUAL)
    try:
        c = ClaimContent.model_validate(p.content)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(x) for x in first["loc"])
        return None, [_check(S, "schema", False, f"{where}: {first['msg']}" if where else first["msg"])]

    checks = [_check(S, "schema", True)]
    policy = p.policy.for_claim(c.type, c.scope)
    refs = [(rel, e) for rel, e in c.evidence if isinstance(e, GitRef)]
    spans = [(rel, e) for rel, e in c.evidence if isinstance(e, Span)]
    checks.append(_check(S, "repository", c.repository == p.repository,
                         f"content is for {c.repository}, proposed to {p.repository}"))
    checks.append(_check(S, "claim_type", c.type in policy.allowed_types,
                         f"{c.type} claims aren't accepted here (allowed: "
                         f"{', '.join(t.value for t in policy.allowed_types)})"))
    if p.policy.kinds:
        kind = (c.scope or {}).get("kind")
        checks.append(_check(S, "claim_kind", kind in p.policy.kinds,
                             f"scope.kind must be one of {', '.join(p.policy.kinds)}"
                             + (f" (got {kind!r})" if kind is not None else " (none given)")))
    if refs:
        checks.append(_check(S, "evidence_kinds", "git_ref" in policy.allowed_evidence,
                             "git refs aren't accepted as evidence here"))
    # only passages count as sources: a claim rests on something it can quote, and a commit can add to that,
    # never replace it (min_sources is at least 1)
    support = [s for rel, s in spans if rel is Relation.SUPPORTS]
    sources = {s.source_id for s in support}
    independent = independent_sources(sources, p.trials)
    checks.append(_check(S, "min_sources", independent >= policy.min_sources,
                         f"{independent} independent supporting source(s), policy needs {policy.min_sources}"
                         + (" (spans of one source count once)" if len(support) > len(sources) else "")
                         + (" (sources reporting the same trial count once)" if len(sources) > independent else "")))

    checks.append(_check(P, "author_active", p.author_status == "active", f"author is {p.author_status}"))
    unknown = sorted({s.source_id for _, s in spans} - p.known_sources)
    checks.append(_check(P, "sources_known", not unknown, f"unknown source(s): {', '.join(unknown)}"))
    if c.derived_from:
        missing = sorted(set(c.derived_from) - p.known_claims)
        checks.append(_check(P, "derived_from_known", not missing,
                             f"derived_from claim(s) not in {p.repository}: {missing}"))
        circular = p.claim_id is not None and (p.claim_id in c.derived_from or p.claim_id in p.ancestors)
        checks.append(_check(P, "no_circular_derivation", not circular,
                             f"claim {p.claim_id} would derive from itself through {sorted(c.derived_from)}"))

    checks.append(_check(I, "parent_is_head", c.parent_hash == p.head_hash,
                         "new claims have no parent" if p.head_hash is None else
                         f"written against {c.parent_hash}, but the claim's head is {p.head_hash}"))
    stale = []
    for _, s in spans:
        d = p.docs.get((s.source_id, s.doc_sha256))
        if d is None:
            stale.append(f"{s.source_id}@{s.doc_sha256[:12]} is not a current document")
        elif s.end > len(d.text):
            stale.append(f"{s.source_id} span {s.start}-{s.end} runs past the document ({len(d.text)} chars)")
    checks.append(_check(I, "spans_current", not stale, "; ".join(stale)))

    if policy.primary_evidence_only:
        derivative = sorted({s.source_id for s in support
                             if (d := p.docs.get((s.source_id, s.doc_sha256))) and not d.is_primary})
        checks.append(_check(SRC, "primary_evidence", not derivative,
                             f"derivative source(s) as support: {', '.join(derivative)}"))

    if policy.evidence_gate:
        profile = profiles.get(policy.profile)
        cited = [gate.CitedClaim(f"e{i}", d.text[s.start:s.end], gate.source_context(d.title, d.abstract, profile))
                 for i, s in enumerate(support) if (d := p.docs.get((s.source_id, s.doc_sha256)))]
        v = gate.check(c.proposition, cited, report_scope={}, profile=profile)
        checks.append(_check(F, f"evidence_gate:{v.rule}" if not v.passed else "evidence_gate", v.passed,
                             v.detail))
    return c, checks


def claim_policy(p: Proposal) -> Policy:
    """The repository's rules for this proposal's claim (its type and scope.kind); the base rules if the content
    doesn't parse, in which case the schema check has already failed it."""
    try:
        c = ClaimContent.model_validate(p.content)
    except ValidationError:
        return p.policy
    return p.policy.for_claim(c.type, c.scope)


def review_tally(reviews, author_id: int, author_org: str, policy: Policy) -> tuple[int, int, list[str]]:
    """(independent approvals, of them by humans, standing objections). Shared by merges and claim reviews.

    Never counts the author's own review; ignores suspended or revoked reviewers; if the policy says so,
    ignores reviewers from the author's organization. Any other non-approval is an objection that blocks."""
    approvals, humans, objections = 0, 0, []
    for r in reviews:
        if r.reviewer_id == author_id:
            continue                                    # never counts, never blocks
        if r.status != "active":
            continue
        if policy.approvals_from_other_orgs_only and r.organization_id == author_org:
            continue
        if r.verdict == "approve":
            approvals += 1
            humans += r.kind == "human"
        else:
            objections.append(f"reviewer {r.reviewer_id} says {r.verdict}")
    return approvals, humans, objections


def approval_reasons(approvals: int, humans: int, policy: Policy) -> list[str]:
    reasons = []
    if approvals < policy.required_approvals:
        reasons.append(f"{approvals} independent approval(s), policy needs {policy.required_approvals}")
    if policy.human_approval and not humans:
        reasons.append("policy needs an approval from a human reviewer")
    return reasons


def authorize(p: Proposal, checks: list[Check], merger: Decision) -> MergeDecision:
    reasons = []
    if not merger:
        reasons.append(f"merger: {merger.reason}")
    reasons += [f"check {c.kind}/{c.name} failed: {c.detail}" for c in checks if not c.passed]

    reasons += [f"blocking challenge {cid} is open" for cid in p.blocking_challenges]

    policy = claim_policy(p)
    approvals, humans, objections = review_tally(p.reviews, p.author_id, p.author_org, policy)
    reasons += objections
    reasons += approval_reasons(approvals, humans, policy)
    return MergeDecision(not reasons, tuple(reasons), approvals)
