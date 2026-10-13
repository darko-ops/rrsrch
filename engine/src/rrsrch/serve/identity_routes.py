"""Identity endpoints (SPEC-v2 §18.1): who am I, agents, keys, repository members and access.

Callers authenticate with `Authorization: Bearer rrsrch_<prefix>_<secret>`.
Every check goes through rrsrch.identity.access; these handlers only fetch
what the decision needs and act on the answer. A private repository the
caller can't read is reported as not found, so its existence doesn't leak.
"""
from __future__ import annotations

from collections.abc import Iterator

import psycopg
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException

from ..identity import access, store
from ..identity.access import Action, Principal, Role
from ..knowledge.models import HANDLE, AgentKind

router = APIRouter(prefix="/v1")


def conn(request: Request) -> Iterator[psycopg.Connection]:
    with request.app.state.connect() as c:
        yield c


def principal(request: Request, c: psycopg.Connection = Depends(conn)) -> Principal | None:
    header = request.headers.get("authorization")
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(401, "authorization must be 'Bearer <key>'")
    p = store.authenticate(c, token.strip())
    if p is None:
        raise HTTPException(401, "invalid, expired or revoked key")
    return p


def _require(decision: access.Decision, *, status: int = 403) -> None:
    if not decision:
        raise HTTPException(401 if decision.reason == "authentication required" else status, decision.reason)


def _repo(c: psycopg.Connection, p: Principal | None, owner: str, name: str) -> tuple[access.Repo, Role | None]:
    repo = store.get_repo(c, f"{owner}/{name}")
    if repo is None:
        raise HTTPException(404)
    role = store.role_in(c, p.agent_id if p else None, repo.id)
    if not access.decide(p, Action.READ, repo, role):
        raise HTTPException(404)          # don't confirm a private repository exists
    return repo, role


def _target_agent(c: psycopg.Connection, handle: str) -> dict:
    agent = store.get_agent(c, handle)
    if agent is None:
        raise HTTPException(404)
    return agent


def _public(agent: dict) -> dict:
    return {k: agent[k] for k in ("handle", "organization_id", "kind", "capabilities", "model", "status",
                                  "created_at")}


class NewAgent(BaseModel):
    handle: str = Field(pattern=HANDLE)
    kind: AgentKind
    capabilities: list[str] = Field(default_factory=list, max_length=32)
    model: str | None = Field(default=None, max_length=200)
    org_role: str = Field(default="member", pattern=r"^(member|admin)$")


class NewKey(BaseModel):
    scopes: list[str] = Field(min_length=1)
    days: int = Field(default=30, ge=1, le=store.MAX_KEY_DAYS)
    label: str = Field(default="", max_length=100)


class MemberRole(BaseModel):
    role: Role


@router.get("/whoami")
def whoami(p: Principal | None = Depends(principal)) -> dict:
    _require(access.Decision(p is not None, "authentication required"))
    return {"ok": True, "handle": p.handle, "organization_id": p.organization_id, "org_role": p.org_role,
            "status": p.status, "scopes": sorted(p.scopes), "key_id": p.key_id}


@router.post("/agents", status_code=201)
def register_agent(body: NewAgent, p: Principal | None = Depends(principal),
                   c: psycopg.Connection = Depends(conn)) -> dict:
    _require(access.can_manage_agents(p, p.organization_id if p else ""))
    try:
        agent = store.register_agent(c, p.organization_id, body.handle, body.kind.value,
                                     capabilities=tuple(body.capabilities), model=body.model,
                                     org_role=body.org_role)
    except store.Conflict as e:
        raise HTTPException(409, str(e)) from e
    return {"ok": True, "agent": _public(agent) | {"org_role": agent["org_role"]}}


@router.get("/agents/{handle}")
def get_agent(handle: str, c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True, "agent": _public(_target_agent(c, handle))}


@router.post("/agents/{handle}/revoke")
def revoke_agent(handle: str, p: Principal | None = Depends(principal),
                 c: psycopg.Connection = Depends(conn)) -> dict:
    agent = _target_agent(c, handle)
    _require(access.can_manage_agents(p, agent["organization_id"]))
    return {"ok": True, "handle": handle, "status": "revoked", "keys_revoked": store.revoke_agent(c, agent["id"])}


@router.post("/agents/{handle}/keys", status_code=201)
def issue_key(handle: str, body: NewKey, p: Principal | None = Depends(principal),
              c: psycopg.Connection = Depends(conn)) -> dict:
    """An org admin can issue any scopes; an agent can issue itself a key no broader than the one it's using."""
    agent = _target_agent(c, handle)
    scopes = frozenset(body.scopes)
    if not access.can_manage_agents(p, agent["organization_id"]):
        _require(access.Decision(p is not None, "authentication required"))
        if p.agent_id != agent["id"] or p.status != "active":
            raise HTTPException(403, f"only an admin of {agent['organization_id']} or {handle} itself can issue its keys")
        if not scopes <= p.scopes:
            raise HTTPException(403, f"a key can't grant scopes the current key lacks: {sorted(scopes - p.scopes)}")
    try:
        token, key_id, expires = store.issue_key(c, agent["id"], scopes, days=body.days, label=body.label)
    except ValueError as e:
        raise HTTPException(409 if isinstance(e, store.Conflict) else 400, str(e)) from e
    return {"ok": True, "key": token, "key_id": key_id, "scopes": sorted(scopes), "expires_at": expires,
            "note": "store this key now; it is not shown again"}


@router.post("/keys/{key_id}/revoke")
def revoke_key(key_id: int, p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    owner = store.key_owner(c, key_id)
    if owner is None:
        raise HTTPException(404)
    if not (p and p.agent_id == owner[0]):
        _require(access.can_manage_agents(p, owner[1]))
    return {"ok": True, "key_id": key_id, "revoked": store.revoke_key(c, key_id)}


@router.get("/repos/{owner}/{name}/access")
def repo_access(owner: str, name: str, p: Principal | None = Depends(principal),
                c: psycopg.Connection = Depends(conn)) -> dict:
    repo, role = _repo(c, p, owner, name)
    eff = access.effective_role(p, repo, role) if p else None
    return {"ok": True, "repository": repo.slug, "visibility": repo.visibility,
            "role": eff.value if eff else None,
            "actions": {a.value: access.decide(p, a, repo, role).allowed for a in Action}}


@router.put("/repos/{owner}/{name}/members/{handle}")
def set_member(owner: str, name: str, handle: str, body: MemberRole, p: Principal | None = Depends(principal),
               c: psycopg.Connection = Depends(conn)) -> dict:
    repo, role = _repo(c, p, owner, name)
    _require(access.decide(p, Action.ADMINISTER, repo, role))
    agent = _target_agent(c, handle)
    try:
        store.set_member(c, repo.id, agent["id"], body.role, granted_by=p.agent_id)
    except store.Conflict as e:
        raise HTTPException(409, str(e)) from e
    return {"ok": True, "repository": repo.slug, "handle": handle, "role": body.role.value}


@router.delete("/repos/{owner}/{name}/members/{handle}")
def remove_member(owner: str, name: str, handle: str, p: Principal | None = Depends(principal),
                  c: psycopg.Connection = Depends(conn)) -> dict:
    repo, role = _repo(c, p, owner, name)
    _require(access.decide(p, Action.ADMINISTER, repo, role))
    agent = _target_agent(c, handle)
    return {"ok": True, "repository": repo.slug, "handle": handle, "removed": store.remove_member(c, repo.id, agent["id"])}
