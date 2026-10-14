"""A repository's acceptance rules. Stored per version in `policies`; never edited in place."""
from __future__ import annotations

import psycopg
from pydantic import BaseModel, ConfigDict, Field

from ..knowledge.models import ClaimType


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


def load(conn: psycopg.Connection, repository_id: int, version: str) -> Policy:
    row = conn.execute("SELECT rules FROM policies WHERE repository_id = %s AND version = %s",
                       (repository_id, version)).fetchone()
    if row is None:
        raise LookupError(f"no policy {version} for repository {repository_id}")
    return Policy.model_validate(row[0])
