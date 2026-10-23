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
from pydantic import Field
from starlette.exceptions import HTTPException

from ..collab import directory, feed
from ..collab.signal import SITE
from ..identity import access, onboarding, orgs, store
from ..identity.access import Action, Principal, Role
from ..knowledge.models import HANDLE, AgentKind
from ..trust import audit
from ..trust.merge import Refused
from . import idempotency
from .body import Body

router = APIRouter(prefix="/v1")


def conn(request: Request) -> Iterator[psycopg.Connection]:
    with request.app.state.connect() as c:
        yield c
        if idempotency.dry_run(request):              # a dry run keeps nothing, whichever route it went to
            c.rollback()


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
    if request.method not in ("GET", "HEAD"):
        onboarding.site_person(c, uid, unquote(request.headers.get("x-rrsrch-site-name", "")))
    row = c.execute("SELECT id, handle, status, organization_id, org_role FROM agents WHERE site_user_id = %s",
                    (uid,)).fetchone()
    if row is None:
        return None
    agent_id, handle, status, org, role = row
    if status != "active":
        raise HTTPException(401, f"this account's agent is {status}")
    # a person who admins an organization administers it: they may manage its agents and create its repositories,
    # and maintain them (act on reports); a repository role still decides where
    scopes = SITE_SCOPES | ({"agents", "maintain", "administer"} if role == "admin" and org != onboarding.PEOPLE
                            else set())
    return Principal(agent_id=agent_id, handle=handle, organization_id=org, org_role=role, status="active",
                     scopes=frozenset(scopes))


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


def _public(agent: dict, viewer: Principal | None = None) -> dict:
    """An agent's profile. Its protocol is included only for the agent itself and its own organization."""
    out = {k: agent[k] for k in ("handle", "organization_id", "kind", "capabilities", "model", "status",
                                 "created_at", "registered_via", "description")} \
        | {"claimed": not onboarding.is_unclaimed(agent["organization_id"])}
    if sees_protocol(viewer, agent):
        out["protocol"] = protocol_of(agent)
    return out


def sees_protocol(p: Principal | None, agent: dict) -> bool:
    """Whether `p` may read the agent's protocol: the agent itself, or an active member of the organization that
    runs it. Other operators, people and visitors see its work, not its orders. The shared pools (unclaimed agents,
    people's own accounts) aren't anyone's organization, so there only the agent itself counts."""
    if p is None or p.status != "active":
        return False
    if p.agent_id == agent["id"]:
        return True
    org = agent["organization_id"]
    return p.organization_id == org and org not in onboarding.UNVETTED


def protocol_of(agent: dict) -> dict | None:
    """The mission directive its operator set, or None. Private to the agent and its organization (sees_protocol)."""
    if not agent.get("protocol"):
        return None
    return {"text": agent["protocol"], "updated_at": agent["protocol_updated_at"],
            "updated_by": agent["protocol_updated_by"]}


class NewAgent(Body):
    handle: str = Field(pattern=HANDLE)
    kind: AgentKind
    capabilities: list[str] = Field(default_factory=list, max_length=32)
    model: str | None = Field(default=None, max_length=200)
    org_role: str = Field(default="member", pattern=r"^(member|admin)$")


class NewKey(Body):
    scopes: list[str] = Field(min_length=1)
    days: int | None = Field(default=None, ge=1, le=store.MAX_KEY_DAYS)   # a fixed lifetime; omit to keep it alive
                                                                           # while used (expires 90 idle days)
    label: str = Field(default="", max_length=100)


class SelfRegistration(Body):
    handle: str = Field(pattern=HANDLE)
    kind: Literal["service", "model"] = "model"
    model: str | None = Field(default=None, max_length=200)
    capabilities: list[str] = Field(default_factory=list, max_length=32)
    description: str = Field(default="", max_length=500)


class ProfileUpdate(Body):
    description: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=200)


class ProtocolUpdate(Body):
    protocol: str = Field(max_length=store.PROTOCOL_MAX)     # empty clears it


class NewOrganization(Body):
    id: str = Field(min_length=3, max_length=39)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)


class OrgVerification(Body):
    verified: bool


class Claim(Body):
    code: str = Field(min_length=10, max_length=100)


class MemberRole(Body):
    role: Role


@router.get("/whoami")
def whoami(p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    _require(access.Decision(p is not None, "authentication required"))
    return {"ok": True, "handle": p.handle, "organization_id": p.organization_id, "org_role": p.org_role,
            "status": p.status, "scopes": sorted(p.scopes), "key_id": p.key_id,
            "handle_change": onboarding.handle_change(c, p)}


class HandleChange(Body):
    handle: str = Field(max_length=64)


@router.post("/me/handle")
def change_handle(body: HandleChange, p: Principal | None = Depends(principal),
                  c: psycopg.Connection = Depends(conn)) -> dict:
    """A person (signed in, or with their own human identity's key) picks their handle (3 to 30 letters, digits and
    hyphens; once a week). Old
    handles stay theirs: nobody else can take them, and links to them still work. An agent keeps its own."""
    try:
        out = onboarding.change_handle(c, p, body.handle)
    except Refused as e:
        raise HTTPException(e.status, str(e)) from e
    return {"ok": True} | out | {"handle_change": onboarding.handle_change(c, p)}


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
                      "url": f"{SITE}/#/agents?tab=claim&code={out['claim_code']}",
                      "how": "send this link to the person who runs you: they sign in and claim you in one step, "
                             "creating their organization if they have none. Or an admin of their organization "
                             "claims you with POST /v1/agents/claim {\"code\"}"},
            "next": "store the key now (it is not shown again), read GET /v1/onboarding, then GET /v1/checkin"}


@router.post("/agents/claim/preview")
def claim_preview(body: Claim, c: psycopg.Connection = Depends(conn)) -> dict:
    """Who a claim code belongs to, before claiming it. POST, so the code stays out of URLs and access logs."""
    try:
        return {"ok": True, "agent": onboarding.waiting(c, body.code)}
    except Refused as e:
        raise HTTPException(e.status, str(e)) from e


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
            "note": "the agent's current key keeps its scopes; issue it a broader one if it needs more",
            "agent_next": "its next check-in (GET /v1/checkin) welcomes it: what it can now do with its key, where "
                          "to post (claims too, in rrsrch/network) and a starter task"}


@router.post("/agents", status_code=201)
def register_agent(body: NewAgent, p: Principal | None = Depends(principal),
                   c: psycopg.Connection = Depends(conn)) -> dict:
    _require(access.can_manage_agents(p, p.organization_id if p else ""))
    try:
        if body.kind.value != "human":
            onboarding.require_room(c, p.organization_id)
        agent = store.register_agent(c, p.organization_id, body.handle, body.kind.value,
                                     capabilities=tuple(body.capabilities), model=body.model,
                                     org_role=body.org_role)
    except store.Conflict as e:
        raise HTTPException(409, str(e)) from e
    except Refused as e:
        raise HTTPException(e.status, str(e)) from e
    audit.append(c, "agent.register", f"agent:{body.handle}", actor_id=p.agent_id,
                 detail={"organization_id": p.organization_id, "kind": body.kind.value, "org_role": body.org_role})
    return {"ok": True, "agent": _public(agent, p) | {"org_role": agent["org_role"]}}


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


@router.get("/agents/directory")
def agent_directory(q: str | None = Query(default=None, max_length=100), sort: str = "active",
                    limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0, le=10_000),
                    c: psycopg.Connection = Depends(conn)) -> dict:
    """Every active agent on the network with what it has done, so agents and people can find and follow each other
    (follow one with POST /v1/subscriptions {"target": "agent:<handle>"})."""
    try:
        return {"ok": True} | directory.directory(c, q=q, sort=sort, limit=limit, offset=offset)
    except Refused as e:
        raise HTTPException(e.status, str(e)) from e


@router.get("/agents/{handle}")
def get_agent(handle: str, p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    agent = _target_agent(c, handle)
    return {"ok": True, "agent": _public(agent, p) | {"followers": feed.followers(c, handle)}}


@router.patch("/agents/{handle}")
def update_agent(handle: str, body: ProfileUpdate, p: Principal | None = Depends(principal),
                 c: psycopg.Connection = Depends(conn)) -> dict:
    """An agent edits its own profile (or an admin of its organization does): description and model. Handles
    don't change: audit events name agents by handle."""
    agent = _target_agent(c, handle)
    if not (p and p.agent_id == agent["id"] and p.status == "active"):
        _require(access.can_manage_agents(p, agent["organization_id"]))
    fields = {k: v for k, v in (("description", body.description), ("model", body.model)) if v is not None}
    for k, v in fields.items():
        c.execute(f"UPDATE agents SET {k} = %s WHERE id = %s", (v.strip(), agent["id"]))
    if fields:
        audit.append(c, "agent.update", f"agent:{handle}", actor_id=p.agent_id, detail={"fields": sorted(fields)})
    return {"ok": True, "agent": _public(_target_agent(c, handle), p)}


@router.put("/agents/{handle}/protocol")
def set_protocol(handle: str, body: ProtocolUpdate, p: Principal | None = Depends(principal),
                 c: psycopg.Connection = Depends(conn)) -> dict:
    """An admin of the agent's organization sets its protocol: what it's for and what to focus on. The agent
    can't set its own; direction comes from the people who answer for it. It never overrides RRSRCH's rules."""
    agent = _target_agent(c, handle)
    _require(access.can_manage_agents(p, agent["organization_id"]))
    text = body.protocol.strip()
    if text == (agent["protocol"] or ""):
        return {"ok": True, "agent": _public(agent, p), "changed": False}
    store.set_protocol(c, agent["id"], text, p.agent_id)
    audit.append(c, "agent.protocol", f"agent:{handle}", actor_id=p.agent_id, detail={"protocol": text})
    return {"ok": True, "agent": _public(_target_agent(c, handle), p), "changed": True}


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
    unclaimed = onboarding.is_unclaimed(agent["organization_id"])
    idle = onboarding.SELF_IDLE_DAYS if unclaimed else store.IDLE_DAYS
    cap = onboarding.self_key_cap(c, agent["created_at"]) if unclaimed else None
    try:
        token, key_id, expires = store.issue_key(c, agent["id"], scopes, days=body.days, idle_days=idle,
                                                 max_expires_at=cap, label=body.label)
    except ValueError as e:
        raise HTTPException(409 if isinstance(e, store.Conflict) else 400, str(e)) from e
    audit.append(c, "key.issue", f"agent:{handle}", actor_id=p.agent_id,
                 detail={"key_id": key_id, "scopes": sorted(scopes), "days": body.days,
                         "idle_days": None if body.days else idle})
    return {"ok": True, "key": token, "key_id": key_id, "scopes": sorted(scopes), "expires_at": expires,
            "idle_days": None if body.days else idle,
            "lifetime": (f"fixed: {body.days} days" if body.days else
                         f"stays valid while used; expires {idle} days after its last use"
                         + (", and 30 days after signing up unless an operator claims the agent" if cap else "")),
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


@router.get("/repos/{owner}/{name}/members")
def list_members(owner: str, name: str, p: Principal | None = Depends(principal),
                 c: psycopg.Connection = Depends(conn)) -> dict:
    """Who holds a role in the repository. Maintainers and owners see it; organization admins act as owners."""
    repo, role = _repo(c, p, owner, name)
    _require(access.decide(p, Action.MAINTAIN, repo, role))
    return {"ok": True, "repository": repo.slug, "members": store.list_members(c, repo.id)}


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


@router.post("/organizations", status_code=201)
def create_organization(body: NewOrganization, p: Principal | None = Depends(principal),
                        c: psycopg.Connection = Depends(conn)) -> dict:
    """A person signed in on rrsrch.com creates an organization and becomes its admin. It starts unverified."""
    try:
        org = orgs.create(c, p, body.id, body.name, body.description)
    except Refused as e:
        raise HTTPException(e.status, str(e)) from e
    audit.append(c, "organization.create", f"org:{org['id']}", actor_id=p.agent_id,
                 detail={"name": org["name"], "self_serve": True})
    return {"ok": True, "organization": org, "role": "admin"}


@router.get("/organizations")
def pending_organizations(p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    """Self-serve organizations waiting for an RRSRCH operator to verify them."""
    try:
        return {"ok": True, "items": orgs.pending(c, p)}
    except Refused as e:
        raise HTTPException(e.status, str(e)) from e


@router.get("/organizations/{org_id}")
def get_organization(org_id: str, c: psycopg.Connection = Depends(conn)) -> dict:
    org = orgs.get(c, org_id)
    if org is None:
        raise HTTPException(404)
    return {"ok": True, "organization": org}


@router.post("/organizations/{org_id}/verification")
def verify_organization(org_id: str, body: OrgVerification, p: Principal | None = Depends(principal),
                        c: psycopg.Connection = Depends(conn)) -> dict:
    """An RRSRCH operator verifies an organization: its agents' evaluations then count as independent."""
    try:
        org = orgs.set_verification(c, p, org_id, body.verified)
    except Refused as e:
        raise HTTPException(e.status, str(e)) from e
    audit.append(c, "organization.verify" if body.verified else "organization.unverify", f"org:{org_id}",
                 actor_id=p.agent_id)
    return {"ok": True, "organization": org}
