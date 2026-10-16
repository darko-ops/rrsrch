"""Agents, keys and memberships in Postgres.

These functions change state but don't decide who may change it: callers ask
rrsrch.identity.access first. The exceptions here are about the data itself
(a handle already taken, a revoked agent getting a key).
"""
from __future__ import annotations

from datetime import datetime

import psycopg

from . import keys
from .access import SCOPES, Principal, Repo, Role

MAX_KEY_DAYS = 365          # a key issued with a fixed lifetime
IDLE_DAYS = 90              # otherwise a key expires this long after it was last used (docs/AGENTS.md, "Keys")
_AGENT_COLS = ("a.id, a.handle, a.organization_id, a.kind, a.capabilities, a.model, a.org_role, a.status, a.created_at, "
               "a.registered_via, a.description, a.claimed_at")


class Conflict(ValueError):
    """The request is well-formed but clashes with what's stored."""


def _agent(row) -> dict:
    keys_ = ("id", "handle", "organization_id", "kind", "capabilities", "model", "org_role", "status", "created_at",
             "registered_via", "description", "claimed_at")
    return dict(zip(keys_, row))


def create_organization(conn: psycopg.Connection, org_id: str, name: str) -> None:
    if conn.execute("SELECT 1 FROM organizations WHERE id = %s", (org_id,)).fetchone():
        raise Conflict(f"organization {org_id} already exists")
    conn.execute("INSERT INTO organizations (id, name) VALUES (%s, %s)", (org_id, name))


def register_agent(conn: psycopg.Connection, organization_id: str, handle: str, kind: str, *,
                   capabilities: tuple[str, ...] = (), model: str | None = None,
                   org_role: str = "member") -> dict:
    if conn.execute("SELECT 1 FROM agents WHERE handle = %s", (handle,)).fetchone():
        raise Conflict(f"handle {handle} is taken")
    if not conn.execute("SELECT 1 FROM organizations WHERE id = %s", (organization_id,)).fetchone():
        raise Conflict(f"no organization {organization_id}")
    row = conn.execute(
        "INSERT INTO agents (handle, organization_id, kind, capabilities, model, org_role) "
        f"VALUES (%s, %s, %s, %s, %s, %s) RETURNING {_AGENT_COLS.replace('a.', '')}",
        (handle, organization_id, kind, list(capabilities), model, org_role)).fetchone()
    return _agent(row)


def get_agent(conn: psycopg.Connection, handle: str) -> dict | None:
    row = conn.execute(f"SELECT {_AGENT_COLS} FROM agents a WHERE a.handle = %s", (handle,)).fetchone()
    return _agent(row) if row else None


def revoke_agent(conn: psycopg.Connection, agent_id: int) -> int:
    """Revoke an agent and every key it holds. Returns how many live keys were revoked."""
    conn.execute("UPDATE agents SET status = 'revoked', revoked_at = coalesce(revoked_at, now()) WHERE id = %s",
                 (agent_id,))
    return conn.execute("UPDATE api_keys SET revoked_at = now() WHERE agent_id = %s AND revoked_at IS NULL",
                        (agent_id,)).rowcount


def issue_key(conn: psycopg.Connection, agent_id: int, scopes: set[str] | frozenset[str], *,
              days: int | None = None, idle_days: int = IDLE_DAYS, max_expires_at: datetime | None = None,
              label: str = "") -> tuple[str, int, datetime]:
    """A new key for an active agent: (token, key id, expiry). The token is not stored and can't be recovered.

    By default the key stays valid while it's used: it expires `idle_days` after its last use (never past
    `max_expires_at`, if given). With `days`, it has that fixed lifetime instead."""
    bad = set(scopes) - SCOPES
    if not scopes or bad:
        raise ValueError(f"scopes must be a non-empty subset of {sorted(SCOPES)}" + (f"; unknown {sorted(bad)}" if bad else ""))
    if days is not None and not 1 <= days <= MAX_KEY_DAYS:
        raise ValueError(f"a fixed lifetime is 1 to {MAX_KEY_DAYS} days")
    if days is None and not 1 <= idle_days <= 365:
        raise ValueError("idle_days is 1 to 365")
    status = conn.execute("SELECT status FROM agents WHERE id = %s", (agent_id,)).fetchone()
    if status is None or status[0] != "active":
        raise Conflict(f"agent is {status[0] if status else 'missing'}; keys are only issued to active agents")
    token, prefix, secret_hash = keys.generate()
    idle = None if days is not None else idle_days
    key_id, expires = conn.execute(
        "INSERT INTO api_keys (agent_id, prefix, secret_hash, scopes, label, idle_days, max_expires_at, expires_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, LEAST(now() + make_interval(days => %s), %s)) RETURNING id, expires_at",
        (agent_id, prefix, secret_hash, sorted(scopes), label, idle, max_expires_at, days or idle,
         max_expires_at)).fetchone()
    return token, key_id, expires


def key_owner(conn: psycopg.Connection, key_id: int) -> tuple[int, str] | None:
    """(agent id, organization) holding a key."""
    return conn.execute("SELECT a.id, a.organization_id FROM api_keys k JOIN agents a ON a.id = k.agent_id "
                        "WHERE k.id = %s", (key_id,)).fetchone()


def list_keys(conn: psycopg.Connection, agent_id: int) -> list[dict]:
    """A key's metadata, never its secret: enough to see what's live and revoke what shouldn't be."""
    cols = ("id", "prefix", "scopes", "label", "created_at", "expires_at", "revoked_at", "last_used_at", "idle_days",
            "max_expires_at")
    return [dict(zip(cols, r)) for r in conn.execute(
        f"SELECT {', '.join(cols)} FROM api_keys WHERE agent_id = %s ORDER BY id DESC", (agent_id,))]


def list_agents(conn: psycopg.Connection, organization_id: str | None, after: int, limit: int) -> list[dict]:
    """Public profiles, oldest first. Handles and profiles are public already (GET /v1/agents/{handle})."""
    cols = ("id", "handle", "organization_id", "kind", "capabilities", "model", "status", "created_at")
    return [dict(zip(cols, r)) for r in conn.execute(
        f"SELECT {', '.join(cols)} FROM agents WHERE (%s::text IS NULL OR organization_id = %s) AND id > %s "
        "ORDER BY id LIMIT %s", (organization_id, organization_id, after, limit))]


def revoke_key(conn: psycopg.Connection, key_id: int) -> bool:
    return conn.execute("UPDATE api_keys SET revoked_at = now() WHERE id = %s AND revoked_at IS NULL",
                        (key_id,)).rowcount == 1


def authenticate(conn: psycopg.Connection, token: str) -> Principal | None:
    """The principal a token belongs to, if it is well-formed, current and unrevoked."""
    parsed = keys.parse(token)
    if parsed is None:
        return None
    prefix, secret = parsed
    row = conn.execute(
        "SELECT k.id, k.secret_hash, k.scopes, a.id, a.handle, a.organization_id, a.org_role, a.status "
        "FROM api_keys k JOIN agents a ON a.id = k.agent_id "
        "WHERE k.prefix = %s AND k.revoked_at IS NULL AND k.expires_at > now()", (prefix,)).fetchone()
    if row is None or not keys.matches(secret, row[1]):
        return None
    # a key in use stays alive: push its expiry to idle_days from now (never past its cap, never backwards)
    conn.execute("UPDATE api_keys SET last_used_at = now(), expires_at = CASE WHEN idle_days IS NULL THEN expires_at "
                 "ELSE LEAST(GREATEST(expires_at, now() + make_interval(days => idle_days)), "
                 "COALESCE(max_expires_at, 'infinity')) END WHERE id = %s", (row[0],))
    return Principal(agent_id=row[3], handle=row[4], organization_id=row[5], org_role=row[6], status=row[7],
                     scopes=frozenset(row[2]), key_id=row[0])


def get_repo(conn: psycopg.Connection, slug: str) -> Repo | None:
    row = conn.execute("SELECT id, slug, organization_id, visibility FROM repositories WHERE slug = %s",
                       (slug,)).fetchone()
    return Repo(*row) if row else None


def role_in(conn: psycopg.Connection, agent_id: int | None, repository_id: int) -> Role | None:
    if agent_id is None:
        return None
    row = conn.execute("SELECT role FROM memberships WHERE repository_id = %s AND agent_id = %s",
                       (repository_id, agent_id)).fetchone()
    return Role(row[0]) if row else None


def set_member(conn: psycopg.Connection, repository_id: int, agent_id: int, role: Role | str,
               granted_by: int | None) -> None:
    role = Role(role)
    status = conn.execute("SELECT status FROM agents WHERE id = %s", (agent_id,)).fetchone()
    if status is None or status[0] != "active":
        raise Conflict("roles are only granted to active agents")
    conn.execute(
        "INSERT INTO memberships (repository_id, agent_id, role, granted_by) VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (repository_id, agent_id) DO UPDATE SET role = EXCLUDED.role, "
        "granted_by = EXCLUDED.granted_by, created_at = now()",
        (repository_id, agent_id, role.value, granted_by))


def remove_member(conn: psycopg.Connection, repository_id: int, agent_id: int) -> bool:
    return conn.execute("DELETE FROM memberships WHERE repository_id = %s AND agent_id = %s",
                        (repository_id, agent_id)).rowcount == 1


def list_members(conn: psycopg.Connection, repository_id: int) -> list[dict]:
    cols = ("handle", "kind", "organization_id", "role", "granted_by", "granted_at")
    return [dict(zip(cols, r)) for r in conn.execute(
        "SELECT a.handle, a.kind, a.organization_id, m.role, g.handle, m.created_at FROM memberships m "
        "JOIN agents a ON a.id = m.agent_id LEFT JOIN agents g ON g.id = m.granted_by "
        "WHERE m.repository_id = %s ORDER BY array_position(ARRAY['owner','maintainer','reviewer','contributor',"
        "'observer'], m.role), a.handle", (repository_id,))]
