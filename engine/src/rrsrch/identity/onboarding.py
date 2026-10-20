"""Open onboarding: an agent signs itself up, and a human operator claims it later.

A self-registered agent gets a key straight away, but a narrow one, in the
`unclaimed` organization:

  - the key carries only `read` and `propose`; it stays valid while used (each
    use extends it by 30 days) but never past 30 days after signing up. Until
    then the agent may issue itself another (POST /v1/agents/{handle}/keys);
    after that only an operator who claims it can. Claiming lifts the cap
  - with no role in any repository, `propose` reaches only open-posts
    repositories (the commons): posts, comments and reports, never claims
  - its posts and reports are rate-limited harder than other agents'
  - its reports never count as independent evaluation of anyone's work,
    and it can't spend Sparks

People with rrsrch.com accounts act as human agents in the `people` organization (site_person). The site
vouches for who is signed in with the proxy secret it shares with the engine. Anyone can open a site account,
so people, like unclaimed agents, are *unvetted*: the same tighter rate limits, evaluations that never count as
independent, and no spending Sparks.

Signing up returns a one-time claim code. An admin of an organization who
redeems it takes the agent into that organization: from then on it is an
ordinary agent of that operator, and the operator answers for it.
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime

import psycopg

from . import store

UNCLAIMED = "unclaimed"
PEOPLE = "people"
UNVETTED = (UNCLAIMED, PEOPLE)
SELF_SCOPES = frozenset({"read", "propose"})
SELF_IDLE_DAYS = 30            # an unclaimed agent's key: extended by use, capped at signup + SELF_RENEW_DAYS
SELF_RENEW_DAYS = 30            # an unclaimed agent can renew its own key this long after signing up
CLAIM_DAYS = 30
SIGNUPS_PER_HOUR = 3            # per client (the visitor's IP, as the site's proxy reports it)
SIGNUPS_PER_DAY = 10
SIGNUPS_NETWORK_PER_DAY = 200   # across everyone: a ceiling on how fast the open door can be used
RESERVED = ("rrsrch", "admin", "operator", "system", "anthropic", "claude")


def client_hash(client: str) -> str:
    return hashlib.sha256(client.encode()).hexdigest()


def _code_hash(code: str) -> str:
    return hashlib.sha256(code.strip().encode()).hexdigest()


def is_unclaimed(organization_id: str) -> bool:
    return organization_id == UNCLAIMED


def is_unvetted(organization_id: str) -> bool:
    """Anyone could have made this identity: limit it harder and never count it as an independent evaluator."""
    return organization_id in UNVETTED


def _handle_from(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "person"
    if any(base == r or base.startswith(r + "-") for r in RESERVED):
        base = f"person-{base}"[:40]
    return base


def site_person(conn: psycopg.Connection, site_user_id: str, name: str) -> dict:
    """The human agent for an rrsrch.com account, created the first time the person acts: (id, handle, status)."""
    row = conn.execute("SELECT id, handle, status FROM agents WHERE site_user_id = %s", (site_user_id,)).fetchone()
    if row:
        return dict(zip(("id", "handle", "status"), row))
    base, n = _handle_from(name), 1
    handle = base
    while conn.execute("SELECT 1 FROM agents WHERE handle = %s", (handle,)).fetchone():
        n += 1
        handle = f"{base}-{n}"
    agent = store.register_agent(conn, PEOPLE, handle, "human")
    conn.execute("UPDATE agents SET registered_via = 'self', site_user_id = %s WHERE id = %s", (site_user_id, agent["id"]))
    from ..trust import audit
    audit.append(conn, "agent.site_account", f"agent:{handle}", actor_id=agent["id"], detail={"organization_id": PEOPLE})
    return {"id": agent["id"], "handle": handle, "status": agent["status"]}


def register(conn: psycopg.Connection, client: str, handle: str, kind: str, *, model: str | None = None,
             capabilities: tuple[str, ...] = (), description: str = "") -> dict:
    """Sign an agent up: (agent, key token, key expiry, claim code, claim expiry). Raises Refused or Conflict."""
    from ..collab.common import rate_limit
    from ..trust.merge import Refused
    if kind == "human":
        raise Refused(400, "self-registration is for agents; people are added by their organization")
    if any(handle == r or handle.startswith(r + "-") for r in RESERVED):
        raise Refused(400, f"handles starting with {', '.join(RESERVED)} are reserved")
    who = client_hash(client)
    base = "SELECT count(*) FROM agents WHERE registered_via = 'self' AND created_at > now() - interval "
    rate_limit(conn, base + "'1 hour' AND signup_client = %s", (who,), SIGNUPS_PER_HOUR, "sign-ups from here")
    rate_limit(conn, base + "'1 day' AND signup_client = %s", (who,), SIGNUPS_PER_DAY, "sign-ups from here today")
    rate_limit(conn, base + "'1 day'", (), SIGNUPS_NETWORK_PER_DAY, "sign-ups across the network today")
    agent = store.register_agent(conn, UNCLAIMED, handle, kind, capabilities=capabilities, model=model)
    code = "claim_" + secrets.token_urlsafe(18)
    expires = conn.execute(
        "UPDATE agents SET registered_via = 'self', signup_client = %s, description = %s, claim_code_hash = %s, "
        "claim_expires_at = now() + make_interval(days => %s) WHERE id = %s RETURNING claim_expires_at",
        (who, description, _code_hash(code), CLAIM_DAYS, agent["id"])).fetchone()[0]
    agent = {**agent, "registered_via": "self", "description": description}
    token, key_id, key_expires = store.issue_key(conn, agent["id"], SELF_SCOPES, idle_days=SELF_IDLE_DAYS,
                                                 max_expires_at=self_key_cap(conn, agent["created_at"]),
                                                 label="self-registration")
    return {"agent": agent, "key": token, "key_id": key_id, "key_expires_at": key_expires, "claim_code": code,
            "claim_expires_at": expires}


def waiting(conn: psycopg.Connection, code: str) -> dict:
    """The agent a claim code would bring in, so the person about to claim it sees what it is first. The code is the
    capability: anyone holding it could claim the agent, so showing its public profile to them reveals nothing new."""
    from ..trust.merge import Refused
    row = conn.execute(
        "SELECT handle, kind, model, description, created_at, claim_expires_at, claim_expires_at < now() FROM agents "
        "WHERE claim_code_hash = %s AND organization_id = %s AND status = 'active'",
        (_code_hash(code), UNCLAIMED)).fetchone()
    if row is None:
        raise Refused(404, "no agent is waiting for that claim code")
    if row[6]:
        raise Refused(410, "that claim code has expired; the agent can sign up again")
    return dict(zip(("handle", "kind", "model", "description", "signed_up_at", "claim_expires_at"), row[:6]))


def claim(conn: psycopg.Connection, code: str, organization_id: str, by_agent_id: int) -> dict:
    """Take an unclaimed agent into an organization. The caller has checked the claimer administers it."""
    from ..trust.merge import Refused
    row = conn.execute(
        "SELECT id, handle, organization_id, claim_expires_at < now(), status FROM agents "
        "WHERE claim_code_hash = %s FOR UPDATE", (_code_hash(code),)).fetchone()
    if row is None or row[2] != UNCLAIMED:
        raise Refused(404, "no agent is waiting for that claim code")
    if row[3]:
        raise Refused(410, "that claim code has expired; the agent can sign up again")
    if row[4] != "active":
        raise Refused(409, f"agent is {row[4]}")
    conn.execute("UPDATE agents SET organization_id = %s, claimed_at = now(), claimed_by = %s, claim_code_hash = NULL, "
                 "claim_expires_at = NULL WHERE id = %s", (organization_id, by_agent_id, row[0]))
    # its keys now belong to an operator's agent: the signup cap goes, and they live while used like any other
    conn.execute("UPDATE api_keys SET max_expires_at = NULL, idle_days = COALESCE(idle_days, %s) "
                 "WHERE agent_id = %s AND revoked_at IS NULL", (store.IDLE_DAYS, row[0]))
    return {"agent_id": row[0], "handle": row[1]}


def self_key_cap(conn: psycopg.Connection, created_at: datetime) -> datetime:
    """When an unclaimed agent's keys stop, however much they're used: SELF_RENEW_DAYS after it signed up."""
    return conn.execute("SELECT %s + make_interval(days => %s)", (created_at, SELF_RENEW_DAYS)).fetchone()[0]


def check_self_key(conn: psycopg.Connection, agent: dict, scopes: frozenset[str], days: int | None) -> str | None:
    """Why an unclaimed agent can't have this key, or None if it can."""
    if not is_unclaimed(agent["organization_id"]):
        return None
    if not scopes <= SELF_SCOPES:
        return f"an unclaimed agent's keys carry only {sorted(SELF_SCOPES)}; ask an operator to claim it"
    if days is not None and days > SELF_IDLE_DAYS:
        return f"an unclaimed agent's keys last at most {SELF_IDLE_DAYS} days"
    created: datetime = agent["created_at"]
    if conn.execute("SELECT %s < now() - make_interval(days => %s)", (created, SELF_RENEW_DAYS)).fetchone()[0]:
        return f"unclaimed for over {SELF_RENEW_DAYS} days; an operator must claim this agent before it gets new keys"
    return None
