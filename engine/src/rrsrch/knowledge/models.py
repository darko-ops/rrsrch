"""Pydantic models for the knowledge schema, mirroring db/migrations/0006_knowledge.sql.

These are the shapes the API and MCP tools will accept and return. Content
that gets hashed (ClaimContent) is kept separate from bookkeeping (ids,
timestamps, review state), so a state change never changes a hash.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import canonical
from .states import ClaimState

ORG_ID = r"^[a-z0-9][a-z0-9-]{0,38}$"
HANDLE = r"^[a-z0-9][a-z0-9-]{0,62}$"
REPO_SLUG = r"^[a-z0-9][a-z0-9-]{0,38}/[a-z0-9][a-z0-9._-]{0,99}$"
SHA256 = r"^[0-9a-f]{64}$"
GIT_SHA = r"^[0-9a-f]{40}$"
# public forges only: the engine clones these read-only to check a commit (docs/security/PLAN.md §5.5)
GIT_REPO = r"^https://(?:github\.com|gitlab\.com|codeberg\.org)/[a-z0-9][a-z0-9._-]{0,99}/[a-z0-9][a-z0-9._-]{0,99}$"
GIT_TAG = r"^[A-Za-z0-9][A-Za-z0-9._/@=+-]{0,199}$"
GIT_PATH = r"^[^/:\-\x00-\x1f][^\x00-\x1f]{0,399}$"     # not '/', ':' (pathspec magic) or '-' (an option) first


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


class GitRef(_Model):
    """A commit in a public repository, pinned by its full SHA; optionally the release tag it should be in, and
    lines of one file at that commit. Evidence for what the code says, not what a document says."""
    repo_url: str = Field(pattern=GIT_REPO)
    commit: str = Field(pattern=GIT_SHA)

    @field_validator("repo_url", mode="before")
    @classmethod
    def _one_spelling(cls, v):
        """Forges are case-insensitive and accept a trailing .git: store one spelling, so one repository has one key."""
        if isinstance(v, str):
            v = v.strip().rstrip("/").lower()
            v = v[:-4] if v.endswith(".git") else v
        return v
    tag: str | None = Field(default=None, pattern=GIT_TAG)
    path: str | None = Field(default=None, pattern=GIT_PATH)
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _lines(self) -> GitRef:
        if self.tag and (".." in self.tag or "@{" in self.tag or self.tag.endswith((".lock", "/"))
                         or self.tag in ("HEAD", "FETCH_HEAD", "ORIG_HEAD")):
            raise ValueError("not a release tag name")
        if self.repo_url.rsplit("/", 1)[-1] in (".", ".."):
            raise ValueError("not a repository name")
        if self.path and ".." in self.path.split("/"):
            raise ValueError("a path can't climb out of the repository ('..')")
        if (self.start_line is None) != (self.end_line is None):
            raise ValueError("start_line and end_line go together")
        if self.start_line is not None:
            if self.path is None:
                raise ValueError("lines need a path")
            if self.end_line < self.start_line:
                raise ValueError(f"end_line {self.end_line} is before start_line {self.start_line}")
        return self

    def label(self) -> str:
        where = f":{self.path}" + (f"#L{self.start_line}-L{self.end_line}" if self.start_line else "") if self.path else ""
        return f"{self.repo_url.removeprefix('https://')}@{self.commit[:12]}{where}" + (f" (in {self.tag}?)" if self.tag else "")


class Evidence(_Model):
    id: int | None = None
    kind: str = Field(default="document_span", pattern=r"^(document_span|git_ref)$")
    span: Span | None = None
    git: GitRef | None = None
    document_id: int | None = None
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
    proposition: str = Field(min_length=1, max_length=2000)
    scope: dict[str, Any] = Field(default_factory=dict)
    fields: dict[str, Any] = Field(default_factory=dict)
    # document spans, and (where the repository's policy allows) git refs; git refs never stand alone (see
    # trust/pipeline.py, "anchored")
    evidence: tuple[tuple[Relation, Span | GitRef], ...] = Field(min_length=1, max_length=50)
    derived_from: tuple[int, ...] = Field(default=(), max_length=20)   # claims (same repository) this builds on
    parent_hash: str | None = Field(default=None, pattern=SHA256)

    def canonical(self) -> dict[str, Any]:
        d = self.model_dump(mode="json")
        # evidence order is not content: sort so the same set hashes the same
        d["evidence"] = sorted(d["evidence"], key=canonical.dumps)
        # added after the first revisions were hashed: left out when empty so their hashes still hold
        if d["derived_from"]:
            d["derived_from"] = sorted(set(d["derived_from"]))
        else:
            del d["derived_from"]
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
