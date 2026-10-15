"""A repository's acceptance rules. Stored per version in `policies`; never edited in place.

Rules apply to every claim, unless an override names the claim's kind (`scope.kind`, e.g. "not_affected") or type:
then the override's rules apply on top, in order. Overrides can only tighten (more approvals, more reproductions,
a human required), never loosen, so a misplaced override can't open a hole (docs/security/PLAN.md §5.6).
"""
from __future__ import annotations

from typing import Any, Literal

import psycopg
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..check import profiles
from ..knowledge.models import ClaimType

EvidenceKind = Literal["document_span", "git_ref"]

# the rules an override may change, and which way is stricter
_AT_LEAST = ("min_sources", "required_approvals", "required_reproductions")
_ONLY_ON = ("primary_evidence_only", "evidence_gate", "approvals_from_other_orgs_only", "human_approval")


class Override(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str | None = Field(default=None, min_length=1, max_length=40)   # matches scope.kind
    type: ClaimType | None = None                                         # matches the claim's type
    min_sources: int | None = Field(default=None, ge=1)
    primary_evidence_only: bool | None = None
    evidence_gate: bool | None = None
    required_approvals: int | None = Field(default=None, ge=0)
    approvals_from_other_orgs_only: bool | None = None
    human_approval: bool | None = None
    required_reproductions: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _names_something(self) -> Override:
        if self.kind is None and self.type is None:
            raise ValueError("an override names the claim kind or type it applies to")
        return self

    def matches(self, type_: ClaimType, scope: dict[str, Any]) -> bool:
        return (self.type is None or self.type == type_) and (self.kind is None or scope.get("kind") == self.kind)

    def rules(self) -> dict[str, Any]:
        return {k: v for k, v in self.model_dump(exclude={"kind", "type"}).items() if v is not None}


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed_types: tuple[ClaimType, ...] = tuple(ClaimType)
    min_sources: int = Field(default=1, ge=1)               # distinct sources among supporting evidence
    primary_evidence_only: bool = False                     # no reviews or meta-analyses as support
    evidence_gate: bool = False                             # wording must pass the citation gate on its passages
    required_approvals: int = Field(default=1, ge=0)        # independent approving reviews
    approvals_from_other_orgs_only: bool = False            # the author's own org can't approve
    human_approval: bool = False                            # at least one approval from a human agent
    required_reproductions: int = Field(default=0, ge=0)    # independent "reproduced" reports before supported;
                                                            # when > 0, an independent "failed" one also holds it
    profile: str = "clinical"                               # the gate's domain profile (check/profiles.py)
    # the claim kinds this repository recognises (scope.kind). When set, every claim must name one, so an override
    # keyed on a kind can't be dodged by leaving scope.kind out or misspelling it
    kinds: tuple[str, ...] = ()
    allowed_evidence: tuple[EvidenceKind, ...] = ("document_span",)   # git_ref: a commit, pinned by its SHA
    overrides: tuple[Override, ...] = ()

    @field_validator("profile")
    @classmethod
    def _known_profile(cls, v: str) -> str:
        profiles.get(v)
        return v

    @field_validator("allowed_evidence")
    @classmethod
    def _passages_always(cls, v: tuple) -> tuple:
        if "document_span" not in v:
            raise ValueError("allowed_evidence must include document_span: a claim rests on a passage it can quote")
        return v

    @model_validator(mode="after")
    def _kinds_closed(self) -> Policy:
        named = {o.kind for o in self.overrides if o.kind}
        if named and not set(self.kinds) >= named:
            raise ValueError(f"overrides name kinds {sorted(named - set(self.kinds))} that aren't in kinds; list every "
                             "kind so claims must declare one")
        return self

    @model_validator(mode="after")
    def _overrides_tighten(self) -> Policy:
        for o in self.overrides:
            for k, v in o.rules().items():
                base = getattr(self, k)
                if (k in _AT_LEAST and v < base) or (k in _ONLY_ON and base and not v):
                    raise ValueError(f"an override can only tighten: {k} is {base} for every claim, "
                                     f"and the override for {o.kind or o.type} sets {v}")
        return self

    def for_claim(self, type_: ClaimType, scope: dict[str, Any] | None = None) -> Policy:
        """The rules for one claim: these, with every matching override applied in order."""
        if not self.overrides:
            return self
        rules = self.model_dump(exclude={"overrides"})
        for o in self.overrides:
            if o.matches(type_, scope or {}):
                # every matching override applies, and the strictest value wins: a later one never undoes an earlier
                for k, v in o.rules().items():
                    rules[k] = max(rules[k], v) if k in _AT_LEAST else (rules[k] or v)
        return Policy.model_validate(rules)


def load(conn: psycopg.Connection, repository_id: int, version: str) -> Policy:
    row = conn.execute("SELECT rules FROM policies WHERE repository_id = %s AND version = %s",
                       (repository_id, version)).fetchone()
    if row is None:
        raise LookupError(f"no policy {version} for repository {repository_id}")
    return Policy.model_validate(row[0])
