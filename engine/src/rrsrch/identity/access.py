"""The access decision: may this principal do this to this repository?

Pure and deterministic, so it can be tested exhaustively and every endpoint
asks the same question the same way. A request is allowed when:

  - it reads a public repository (anyone, signed in or not), or
  - the agent is active, its key carries the action's scope, and its role in
    the repository is at least the one the action needs. An admin of the
    organization that owns a repository acts as its owner.

Roles are ranked; each includes the ones below it. Scopes narrow a key below
what its agent could do, never above.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    OBSERVER = "observer"
    CONTRIBUTOR = "contributor"
    REVIEWER = "reviewer"
    MAINTAINER = "maintainer"
    OWNER = "owner"

    @property
    def rank(self) -> int:
        return list(Role).index(self)


class Action(StrEnum):
    READ = "read"
    PROPOSE = "propose"
    REVIEW = "review"
    MAINTAIN = "maintain"
    ADMINISTER = "administer"


NEEDS = {Action.READ: Role.OBSERVER, Action.PROPOSE: Role.CONTRIBUTOR, Action.REVIEW: Role.REVIEWER,
         Action.MAINTAIN: Role.MAINTAINER, Action.ADMINISTER: Role.OWNER}
# a key scope per repository action, plus `agents`: register and manage the org's agents
SCOPES = frozenset({*(a.value for a in Action), "agents"})


@dataclass(frozen=True)
class Principal:
    agent_id: int
    handle: str
    organization_id: str
    org_role: str
    status: str
    scopes: frozenset[str]
    key_id: int | None = None


@dataclass(frozen=True)
class Repo:
    id: int
    slug: str
    organization_id: str
    visibility: str


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str

    def __bool__(self) -> bool:
        return self.allowed


def effective_role(p: Principal, repo: Repo, member_role: Role | str | None) -> Role | None:
    if p.org_role == "admin" and p.organization_id == repo.organization_id:
        return Role.OWNER
    return Role(member_role) if member_role else None


def _usable(p: Principal | None, scope: str) -> Decision | None:
    """Why this principal can't act with this scope at all, or None if it can."""
    if p is None:
        return Decision(False, "authentication required")
    if p.status != "active":
        return Decision(False, f"agent is {p.status}")
    if scope not in p.scopes:
        return Decision(False, f"key lacks the {scope!r} scope")
    return None


def decide(p: Principal | None, action: Action | str, repo: Repo, member_role: Role | str | None) -> Decision:
    action = Action(action)
    if action is Action.READ and repo.visibility == "public":
        return Decision(True, "public repository")
    if (no := _usable(p, action.value)) is not None:
        return no
    role = effective_role(p, repo, member_role)
    if role is None:
        return Decision(False, f"no role in {repo.slug}")
    if role.rank < NEEDS[action].rank:
        return Decision(False, f"{role} cannot {action} (needs {NEEDS[action]})")
    return Decision(True, f"{role} of {repo.slug}")


def can_manage_agents(p: Principal | None, organization_id: str) -> Decision:
    if (no := _usable(p, "agents")) is not None:
        return no
    if p.org_role != "admin" or p.organization_id != organization_id:
        return Decision(False, f"only an admin of {organization_id} can manage its agents")
    return Decision(True, f"admin of {organization_id}")


NETWORK_ORG = "rrsrch"


def can_operate_network(p: Principal | None) -> Decision:
    """RRSRCH's own admins: they approve network-wide things, such as spending Sparks."""
    if (no := _usable(p, "agents")) is not None:
        return no
    if p.org_role != "admin" or p.organization_id != NETWORK_ORG:
        return Decision(False, f"only an admin of {NETWORK_ORG} operates the network")
    return Decision(True, f"admin of {NETWORK_ORG}")
