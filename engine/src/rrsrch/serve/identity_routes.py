"""Identity endpoints (SPEC-v2 §18.1): who am I, agents, keys, repository members and access.

Callers authenticate with `Authorization: Bearer rrsrch_<prefix>_<secret>`.
Every check goes through rrsrch.identity.access; these handlers only fetch
what the decision needs and act on the answer. A private repository the
caller can't read is reported as not found, so its existence doesn't leak.
"""
from __future__ import annotations

import hmac
import os
from collections.abc import Iterator
from importlib import resources
from typing import Literal
from urllib.parse import unquote

import psycopg
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException

from ..identity import access, onboarding, store
from ..identity.access import Action, Principal, Role
from ..knowledge.models import HANDLE, AgentKind
from ..trust import audit
from ..trust.merge import Refused

router = APIRouter(prefix="/v1")


def conn(request: Request) -> Iterator[psycopg.Connection]:
    with request.app.state.connect() as c:
        yield c


SITE_SCOPES = frozenset({"read", "propose", "review"})


def _proxied(request: Request) -> bool:
    """Whether the request carries the secret the site's proxy shares with the engine."""
    secret = os.environ.get("RRSRCH_PROXY_SECRET", "")
    return bool(secret) and hmac.compare_digest(request.headers.get("x-rrsrch-proxy-secret", ""), secret)


def site_principal(request: Request, c: psycopg.Connection) -> Principal | None:
    """A person signed in on rrsrch.com, as the site vouches for them. Their human agent is created the first time
    they write; a read before then is anonymous."""
    uid = request.headers.get("x-rrsrch-site-user", "").strip()
    if not uid or not _proxied(request):
        return None
    if request.method in ("GET", "HEAD"):
        row = c.execute("SELECT id, handle, status FROM agents WHERE site_user_id = %s", (uid,)).fetchone()
        person = dict(zip(("id", "handle", "status"), row)) if row else None
    else:
        person = onboarding.site_person(c, uid, unquote(request.headers.get("x-rrsrch-site-name", "")))
    if person is None:
        return None
    if person["status"] != "active":
        raise HTTPException(401, f"this account's agent is {person['status']}")
    return Principal(agent_id=person["id"], handle=person["handle"], organization_id=onboarding.PEOPLE,
                     org_role="member", status="active", scopes=SITE_SCOPES)


def principal(request: Request, c: psycopg.Connection = Depends(conn)) -> Principal | None:
    header = request.headers.get("authorization")
    if not header:
        p = site_principal(request, c)
        if p is not None:
            request.state.principal = p
        return p
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(401, "authorization must be 'Bearer <key>'")
    p = store.authenticate(c, token.strip())
    if p is None:
        raise HTTPException(401, "invalid, expired or revoked key")
    request.state.principal = p          # for the refusal record (serve.api)
    return p


def client_of(request: Request, p: Principal | None) -> tuple[str, bool]:
    """Who is asking, for limits: an agent by key, otherwise a visitor by IP. The site's proxy passes the
    visitor's IP (every request it makes comes from Vercel), proven by a secret it shares with the engine; a
    header without the secret is ignored, so nobody can claim another visitor's IP."""
    if p is not None:
        return f"agent:{p.agent_id}", True
    if _proxied(request) and request.headers.get("x-rrsrch-client-ip"):
        return f"ip:{request.headers['x-rrsrch-client-ip'].strip()}", False
    return f"ip:{request.client.host if request.client else 'unknown'}", False


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
                                  "created_at", "registered_via", "description")} \
        | {"claimed": not onboarding.is_unclaimed(agent["organization_id"])}


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


class SelfRegistration(BaseModel):
    handle: str = Field(pattern=HANDLE)
    kind: Literal["service", "model"] = "model"
    model: str | None = Field(default=None, max_length=200)
    capabilities: list[str] = Field(default_factory=list, max_length=32)
    description: str = Field(default="", max_length=500)


class Claim(BaseModel):
    code: str = Field(min_length=10, max_length=100)


class MemberRole(BaseModel):
    role: Role


@router.get("/whoami")
def whoami(p: Principal | None = Depends(principal)) -> dict:
    _require(access.Decision(p is not None, "authentication required"))
    return {"ok": True, "handle": p.handle, "organization_id": p.organization_id, "org_role": p.org_role,
            "status": p.status, "scopes": sorted(p.scopes), "key_id": p.key_id}


@router.get("/onboarding", response_class=PlainTextResponse)
def onboarding_guide() -> PlainTextResponse:
    """How an agent joins RRSRCH, as Markdown an agent can read and follow."""
    text = resources.files("rrsrch.serve").joinpath("onboarding.md").read_text()
    return PlainTextResponse(text, media_type="text/markdown; charset=utf-8")


@router.post("/agents/register", status_code=201)
def self_register(body: SelfRegistration, request: Request, c: psycopg.Connection = Depends(conn)) -> dict:
    """An agent signs itself up. It gets a narrow 7-day key now and a claim code for its human operator."""
    client, _ = client_of(request, None)
    try:
        out = onboarding.register(c, client, body.handle, body.kind, model=body.model,
                                  capabilities=tuple(body.capabilities), description=body.description)
    except Refused as e:
        raise HTTPException(e.status, str(e)) from e
    except store.Conflict as e:
        raise HTTPException(409, str(e)) from e
    audit.append(c, "agent.self_register", f"agent:{body.handle}", actor_id=out["agent"]["id"],
                 detail={"kind": body.kind, "model": body.model, "key_id": out["key_id"]})
    return {"ok": True, "agent": _public(out["agent"]), "key": out["key"], "key_expires_at": out["key_expires_at"],
            "scopes": sorted(onboarding.SELF_SCOPES),
            "claim": {"code": out["claim_code"], "expires_at": out["claim_expires_at"],
                      "how": "give this code to the person who runs you; an admin of their organization claims you "
                             "with POST /v1/agents/claim (or on rrsrch.com, Agents)"},
            "next": "store the key now (it is not shown again), read GET /v1/onboarding, then GET /v1/checkin"}


@router.post("/agents/claim")
def claim_agent(body: Claim, p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    """An organization admin takes a self-registered agent into the organization with its claim code."""
    _require(access.can_manage_agents(p, p.organization_id if p else ""))
    try:
        got = onboarding.claim(c, body.code, p.organization_id, p.agent_id)
    except Refused as e:
        raise HTTPException(e.status, str(e)) from e
    audit.append(c, "agent.claim", f"agent:{got['handle']}", actor_id=p.agent_id,
                 detail={"organization_id": p.organization_id})
    return {"ok": True, "handle": got["handle"], "organization_id": p.organization_id,
            "note": "the agent's current key keeps its scopes; issue it a broader one if it needs more"}


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
    audit.append(c, "agent.register", f"agent:{body.handle}", actor_id=p.agent_id,
                 detail={"organization_id": p.organization_id, "kind": body.kind.value, "org_role": body.org_role})
    return {"ok": True, "agent": _public(agent) | {"org_role": agent["org_role"]}}


@router.get("/agents")
def list_agents(organization: str | None = None, after: int = Query(default=0, ge=0),
                limit: int = Query(default=50, ge=1, le=200), c: psycopg.Connection = Depends(conn)) -> dict:
    rows = store.list_agents(c, organization, after, limit)
    return {"ok": True, "items": rows, "next": rows[-1]["id"] if len(rows) == limit else None}


@router.get("/agents/{handle}/keys")
def list_keys(handle: str, p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    """An agent's own keys, or any agent's in your organization if you manage its agents. Never the secrets."""
    agent = _target_agent(c, handle)
    if not (p and p.agent_id == agent["id"] and p.status == "active"):
        _require(access.can_manage_agents(p, agent["organization_id"]))
    return {"ok": True, "handle": handle, "keys": store.list_keys(c, agent["id"])}


@router.get("/agents/{handle}")
def get_agent(handle: str, c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True, "agent": _public(_target_agent(c, handle))}


@router.post("/agents/{handle}/revoke")
def revoke_agent(handle: str, p: Principal | None = Depends(principal),
                 c: psycopg.Connection = Depends(conn)) -> dict:
    agent = _target_agent(c, handle)
    _require(access.can_manage_agents(p, agent["organization_id"]))
    n = store.revoke_agent(c, agent["id"])
    audit.append(c, "agent.revoke", f"agent:{handle}", actor_id=p.agent_id, detail={"keys_revoked": n})
    return {"ok": True, "handle": handle, "status": "revoked", "keys_revoked": n}


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
    if (why := onboarding.check_self_key(c, agent, scopes, body.days)) is not None:
        raise HTTPException(403, why)
    try:
        token, key_id, expires = store.issue_key(c, agent["id"], scopes, days=body.days, label=body.label)
    except ValueError as e:
        raise HTTPException(409 if isinstance(e, store.Conflict) else 400, str(e)) from e
    audit.append(c, "key.issue", f"agent:{handle}", actor_id=p.agent_id,
                 detail={"key_id": key_id, "scopes": sorted(scopes), "days": body.days})
    return {"ok": True, "key": token, "key_id": key_id, "scopes": sorted(scopes), "expires_at": expires,
            "note": "store this key now; it is not shown again"}


@router.post("/keys/{key_id}/revoke")
def revoke_key(key_id: int, p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    owner = store.key_owner(c, key_id)
    if owner is None:
        raise HTTPException(404)
    if not (p and p.agent_id == owner[0]):
        _require(access.can_manage_agents(p, owner[1]))
    revoked = store.revoke_key(c, key_id)
    audit.append(c, "key.revoke", f"key:{key_id}", actor_id=p.agent_id, detail={"revoked": revoked})
    return {"ok": True, "key_id": key_id, "revoked": revoked}


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
    audit.append(c, "member.set", f"agent:{handle}", actor_id=p.agent_id, repository_id=repo.id,
                 detail={"role": body.role.value})
    return {"ok": True, "repository": repo.slug, "handle": handle, "role": body.role.value}


@router.delete("/repos/{owner}/{name}/members/{handle}")
def remove_member(owner: str, name: str, handle: str, p: Principal | None = Depends(principal),
                  c: psycopg.Connection = Depends(conn)) -> dict:
    repo, role = _repo(c, p, owner, name)
    _require(access.decide(p, Action.ADMINISTER, repo, role))
    agent = _target_agent(c, handle)
    removed = store.remove_member(c, repo.id, agent["id"])
    audit.append(c, "member.remove", f"agent:{handle}", actor_id=p.agent_id, repository_id=repo.id,
                 detail={"removed": removed})
    return {"ok": True, "repository": repo.slug, "handle": handle, "removed": removed}
