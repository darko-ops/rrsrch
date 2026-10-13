"""Pydantic models for the knowledge schema, mirroring db/migrations/0006_knowledge.sql.

These are the shapes the API and MCP tools will accept and return. Content
that gets hashed (ClaimContent) is kept separate from bookkeeping (ids,
timestamps, review state), so a state change never changes a hash.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import canonical
from .states import ClaimState

ORG_ID = r"^[a-z0-9][a-z0-9-]{0,38}$"
HANDLE = r"^[a-z0-9][a-z0-9-]{0,62}$"
REPO_SLUG = r"^[a-z0-9][a-z0-9-]{0,38}/[a-z0-9][a-z0-9._-]{0,99}$"
SHA256 = r"^[0-9a-f]{64}$"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ClaimType(StrEnum):
    """SPEC-v2 §7.2. Each type gets its own evidence and review standard."""
    FACTUAL = "factual"
    EMPIRICAL = "empirical"
    INTERPRETIVE = "interpretive"
    HYPOTHESIS = "hypothesis"
    PROCEDURAL = "procedural"
    PREDICTIVE = "predictive"


class Visibility(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"


class AgentKind(StrEnum):
    SERVICE = "service"
    MODEL = "model"
    HUMAN = "human"


class AgentStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class Relation(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    CONTEXT = "context"


class CheckKind(StrEnum):
    """SPEC-v2 §10.3. Passing one kind of check never implies passing another."""
    STRUCTURAL = "structural"
    INTEGRITY = "integrity"
    PROVENANCE = "provenance"
    SOURCE = "source"
    EMPIRICAL = "empirical"
    FACTUAL = "factual"


class Organization(_Model):
    id: str = Field(pattern=ORG_ID)
    name: str = Field(min_length=1)
    verification: str = Field(default="unverified", pattern=r"^(unverified|verified)$")


class Agent(_Model):
    id: int | None = None
    handle: str = Field(pattern=HANDLE)
    organization_id: str = Field(pattern=ORG_ID)
    kind: AgentKind
    capabilities: tuple[str, ...] = ()
    status: AgentStatus = AgentStatus.ACTIVE


class Repository(_Model):
    id: int | None = None
    slug: str = Field(pattern=REPO_SLUG)
    organization_id: str = Field(pattern=ORG_ID)
    topic: str = Field(min_length=1)
    description: str = ""
    visibility: Visibility
    contribution_policy: dict[str, Any] = Field(default_factory=dict)
    evidence_policy: dict[str, Any] = Field(default_factory=dict)
    policy_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def _owner_matches_slug(self) -> Repository:
        if self.slug.split("/", 1)[0] != self.organization_id:
            raise ValueError(f"slug {self.slug!r} is not under organization {self.organization_id!r}")
        return self


class Span(_Model):
    """An exact character range of a document, valid only against `doc_sha256`."""
    source_id: str = Field(min_length=1)
    doc_sha256: str = Field(pattern=SHA256)
    start: int = Field(ge=0)
    end: int

    @model_validator(mode="after")
    def _ordered(self) -> Span:
        if self.end <= self.start:
            raise ValueError(f"span end {self.end} must be after start {self.start}")
        return self


class Evidence(_Model):
    id: int | None = None
    kind: str = Field(default="document_span", pattern=r"^document_span$")
    span: Span
    document_id: int
    excerpt: str = Field(min_length=1)
    is_primary: bool
    license: str | None = None
    retrieved_at: datetime | None = None


class EvidenceLink(_Model):
    claim_id: int
    evidence_id: int
    relation: Relation


class ClaimContent(_Model):
    """What a claim says and rests on. This, and only this, is hashed into a revision."""
    repository: str = Field(pattern=REPO_SLUG)
    type: ClaimType
    proposition: str = Field(min_length=1)
    scope: dict[str, Any] = Field(default_factory=dict)
    fields: dict[str, Any] = Field(default_factory=dict)
    evidence: tuple[tuple[Relation, Span], ...] = Field(min_length=1)
    parent_hash: str | None = Field(default=None, pattern=SHA256)

    def canonical(self) -> dict[str, Any]:
        d = self.model_dump(mode="json")
        # evidence order is not content: sort so the same set hashes the same
        d["evidence"] = sorted(d["evidence"], key=canonical.dumps)
        return d

    def content_hash(self) -> str:
        return canonical.digest(self.canonical())


class ClaimRevision(_Model):
    id: int | None = None
    claim_id: int
    version: int = Field(ge=1)
    parent_id: int | None = None
    content: ClaimContent
    content_hash: str = Field(pattern=SHA256)
    agent_id: int

    @model_validator(mode="after")
    def _consistent(self) -> ClaimRevision:
        if (self.version == 1) != (self.parent_id is None):
            raise ValueError("version 1 has no parent; every later version has one")
        if (self.version == 1) != (self.content.parent_hash is None):
            raise ValueError("content.parent_hash must be set exactly when there is a parent")
        if self.content.content_hash() != self.content_hash:
            raise ValueError("content_hash does not match content")
        return self


class Claim(_Model):
    id: int | None = None
    repository_id: int
    type: ClaimType
    state: ClaimState
    proposition: str = Field(min_length=1)
    scope: dict[str, Any] = Field(default_factory=dict)
    agent_id: int


class Check(_Model):
    kind: CheckKind
    name: str = Field(min_length=1)
    passed: bool
    detail: str = ""


class VerificationRun(_Model):
    id: int | None = None
    claim_revision_id: int
    policy_version: str = Field(min_length=1)
    checks: tuple[Check, ...] = Field(min_length=1)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)
