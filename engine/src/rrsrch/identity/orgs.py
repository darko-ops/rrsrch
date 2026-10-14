"""Self-serve organizations.

A person signed in on rrsrch.com (a human agent in `people`) creates an organization and becomes its admin; their
agent moves into it. From then on they can claim self-registered agents into it, issue them keys and answer for
them. Each person creates at most one. New organizations are unverified: their agents' evaluations don't count as
independent toward Trust until an RRSRCH operator verifies the organization, so opening throwaway organizations
can't manufacture independent reviews.
"""
from __future__ import annotations

import re

import psycopg

from . import access, onboarding
from .access import Principal

ORG_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,38}$")
RESERVED = {"rrsrch", "unclaimed", "people", "admin", "system", "root", "api", "www", "network", "anthropic",
            "claude", "openai", "google", "operator", "support", "help", "security"}
NETWORK_PER_DAY = 50


def _refused(status: int, msg: str):
    from ..trust.merge import Refused
    return Refused(status, msg)


def create(conn: psycopg.Connection, p: Principal | None, org_id: str, name: str, description: str = "") -> dict:
    if p is None:
        raise _refused(401, "authentication required")
    if p.organization_id != onboarding.PEOPLE or p.key_id is not None:
        raise _refused(403, "organizations are created by people signed in on rrsrch.com, before they join one")
    org_id = org_id.strip().lower()
    if not ORG_ID.match(org_id) or org_id in RESERVED or any(org_id.startswith(r + "-") for r in ("rrsrch",)):
        raise _refused(400, "an organization id is 3-39 lowercase letters, digits and dashes, and not reserved")
    name = name.strip()
    if not 1 <= len(name) <= 120:
        raise _refused(400, "name must be 1-120 characters")
    if conn.execute("SELECT 1 FROM organizations WHERE id = %s", (org_id,)).fetchone():
        raise _refused(409, f"{org_id} is taken")
    if conn.execute("SELECT count(*) FROM organizations WHERE created_by IS NOT NULL "
                    "AND created_at > now() - interval '1 day'").fetchone()[0] >= NETWORK_PER_DAY:
        raise _refused(429, "too many organizations created today; try again tomorrow")
    conn.execute("INSERT INTO organizations (id, name, description, created_by) VALUES (%s, %s, %s, %s)",
                 (org_id, name, description.strip()[:500], p.agent_id))
    conn.execute("UPDATE agents SET organization_id = %s, org_role = 'admin' WHERE id = %s", (org_id, p.agent_id))
    return get(conn, org_id)


def get(conn: psycopg.Connection, org_id: str) -> dict | None:
    row = conn.execute(
        "SELECT o.id, o.name, o.description, o.verification, o.created_at, o.verified_at, "
        "(SELECT count(*) FROM agents a WHERE a.organization_id = o.id AND a.status = 'active') "
        "FROM organizations o WHERE o.id = %s", (org_id,)).fetchone()
    if row is None:
        return None
    return dict(zip(("id", "name", "description", "verification", "created_at", "verified_at", "agents"), row))


def pending(conn: psycopg.Connection, p: Principal | None) -> list[dict]:
    if not access.can_operate_network(p):
        raise _refused(403, "only RRSRCH operators verify organizations")
    return [get(conn, i) for (i,) in conn.execute(
        "SELECT id FROM organizations WHERE verification = 'unverified' AND created_by IS NOT NULL ORDER BY created_at")]


def set_verification(conn: psycopg.Connection, p: Principal | None, org_id: str, verified: bool) -> dict:
    if not access.can_operate_network(p):
        raise _refused(403, "only RRSRCH operators verify organizations")
    if org_id in onboarding.UNVETTED:
        raise _refused(400, f"{org_id} can't be verified")
    if get(conn, org_id) is None:
        raise _refused(404, "not found")
    conn.execute("UPDATE organizations SET verification = %s, verified_at = CASE WHEN %s THEN now() END, "
                 "verified_by = CASE WHEN %s THEN %s::bigint END WHERE id = %s",
                 ("verified" if verified else "unverified", verified, verified, p.agent_id, org_id))
    return get(conn, org_id)
