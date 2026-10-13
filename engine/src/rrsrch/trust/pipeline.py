"""The validation pipeline and the merge decision (SPEC-v2 §10.2–10.4). Pure functions.

`verify` runs the checks a proposed claim must pass on its own (steps 2–6):
schema, policy, provenance, integrity, source, and the evidence gate. Each
check names its kind, so passing one is never read as passing another.

`authorize` makes the merge decision (steps 7–9) from the checks, the reviews
and who is merging. It counts only independent approvals: never the author's
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

from ..check import gate
from ..identity.access import Decision
from ..knowledge.models import Check, CheckKind, ClaimContent, Relation
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


@dataclass(frozen=True)
class MergeDecision:
    allowed: bool
    reasons: tuple[str, ...]
    approvals: int

    def __bool__(self) -> bool:
        return self.allowed


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
    checks.append(_check(S, "repository", c.repository == p.repository,
                         f"content is for {c.repository}, proposed to {p.repository}"))
    checks.append(_check(S, "claim_type", c.type in p.policy.allowed_types,
                         f"{c.type} claims aren't accepted here (allowed: "
                         f"{', '.join(t.value for t in p.policy.allowed_types)})"))
    support = [s for rel, s in c.evidence if rel is Relation.SUPPORTS]
    distinct = {s.source_id for s in support}
    checks.append(_check(S, "min_sources", len(distinct) >= p.policy.min_sources,
                         f"{len(distinct)} distinct supporting source(s), policy needs {p.policy.min_sources}"
                         + (" (duplicate spans of one source count once)" if len(support) > len(distinct) else "")))

    checks.append(_check(P, "author_active", p.author_status == "active", f"author is {p.author_status}"))
    unknown = sorted({s.source_id for _, s in c.evidence} - p.known_sources)
    checks.append(_check(P, "sources_known", not unknown, f"unknown source(s): {', '.join(unknown)}"))

    checks.append(_check(I, "parent_is_head", c.parent_hash == p.head_hash,
                         "new claims have no parent" if p.head_hash is None else
                         f"written against {c.parent_hash}, but the claim's head is {p.head_hash}"))
    stale = []
    for _, s in c.evidence:
        d = p.docs.get((s.source_id, s.doc_sha256))
        if d is None:
            stale.append(f"{s.source_id}@{s.doc_sha256[:12]} is not a current document")
        elif s.end > len(d.text):
            stale.append(f"{s.source_id} span {s.start}-{s.end} runs past the document ({len(d.text)} chars)")
    checks.append(_check(I, "spans_current", not stale, "; ".join(stale)))

    if p.policy.primary_evidence_only:
        derivative = sorted({s.source_id for s in support
                             if (d := p.docs.get((s.source_id, s.doc_sha256))) and not d.is_primary})
        checks.append(_check(SRC, "primary_evidence", not derivative,
                             f"derivative source(s) as support: {', '.join(derivative)}"))

    if p.policy.evidence_gate:
        cited = [gate.CitedClaim(f"e{i}", d.text[s.start:s.end], gate.source_context(d.title, d.abstract))
                 for i, s in enumerate(support) if (d := p.docs.get((s.source_id, s.doc_sha256)))]
        v = gate.check(c.proposition, cited, report_scope={})
        checks.append(_check(F, f"evidence_gate:{v.rule}" if not v.passed else "evidence_gate", v.passed,
                             v.detail))
    return c, checks


def authorize(p: Proposal, checks: list[Check], merger: Decision) -> MergeDecision:
    reasons = []
    if not merger:
        reasons.append(f"merger: {merger.reason}")
    reasons += [f"check {c.kind}/{c.name} failed: {c.detail}" for c in checks if not c.passed]

    approvals, humans = 0, 0
    for r in p.reviews:
        if r.reviewer_id == p.author_id:
            continue                                    # never counts, never blocks
        if r.status != "active":
            continue
        if p.policy.approvals_from_other_orgs_only and r.organization_id == p.author_org:
            continue
        if r.verdict == "approve":
            approvals += 1
            humans += r.kind == "human"
        else:
            reasons.append(f"reviewer {r.reviewer_id} says {r.verdict}")
    if approvals < p.policy.required_approvals:
        reasons.append(f"{approvals} independent approval(s), policy needs {p.policy.required_approvals}")
    if p.policy.human_approval and not humans:
        reasons.append("policy needs an approval from a human reviewer")
    return MergeDecision(not reasons, tuple(reasons), approvals)
