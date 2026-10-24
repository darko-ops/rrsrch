"""Independence: whose decision counts as independent of whose work. One rule for approvals that merge or support
claims, challenges, reproductions, Spark bounties and Sparks credits (docs/ECONOMY.md, docs/SPARKS.md).

An agent or person counts as independent of an organization's work when it is
  - in another organization, where OWNER_ORGS (RRSRCH's own and its owner's) are one operator, never independent of
    each other
  - in a verified organization: a new self-serve organization counts once an RRSRCH operator verifies it
  - not unvetted (identity/onboarding.py): unclaimed sign-ups and people's own rrsrch.com accounts never count

Where a decision is taken now, the decider must also be active (trust/pipeline.py checks that); a record already
made keeps counting.
"""
from __future__ import annotations

import psycopg

from . import onboarding

OWNER_ORGS = ("rrsrch", "ominis-labs")      # RRSRCH's own and its owner's: never independent of each other


def operator(org: str) -> tuple[str, ...]:
    """The organizations run by the same operator as `org`, itself included."""
    return OWNER_ORGS if org in OWNER_ORGS else (org,)


def same_operator(a: str, b: str) -> bool:
    return b in operator(a)


def excluded(org: str) -> list[str]:
    """Organizations whose agents never count as independent of `org`'s work."""
    return [*operator(org), *onboarding.UNVETTED]


def vetted(org: str, verification: str | None) -> bool:
    """Whether an agent of `org` can count as independent of anyone: a verified organization, not an unvetted pool."""
    return org not in onboarding.UNVETTED and verification == "verified"


def counts(of_org: str, org: str, verification: str | None) -> bool:
    """Whether an agent of `org` (whose organization is `verification`) is independent of `of_org`'s work."""
    return vetted(org, verification) and not same_operator(of_org, org)


def of(conn: psycopg.Connection, agent_id: int, of_org: str) -> bool:
    """Whether this agent, active now, is independent of `of_org`'s work."""
    row = conn.execute("SELECT a.organization_id, o.verification, a.status FROM agents a "
                       "JOIN organizations o ON o.id = a.organization_id WHERE a.id = %s", (agent_id,)).fetchone()
    return bool(row) and row[2] == "active" and counts(of_org, row[0], row[1])


def params(conn: psycopg.Connection, org: str) -> dict:
    """Query parameters for sql() and sql_toward(), relative to `org` (the organization whose work, or whose
    credit, is being decided)."""
    verification = conn.execute("SELECT verification FROM organizations WHERE id = %s", (org,)).fetchone()
    return {"ind_excluded": excluded(org), "ind_operator": list(operator(org)), "ind_owners": list(OWNER_ORGS),
            "ind_vetted": vetted(org, verification[0] if verification else None)}


def sql(col: str) -> str:
    """SQL: the agent in `col` is independent of the work of params()' organization."""
    return (f"coalesce((SELECT o.id <> ALL(%(ind_excluded)s) AND o.verification = 'verified' FROM agents x "
            f"JOIN organizations o ON o.id = x.organization_id WHERE x.id = {col}), false)")


def sql_apart(a: str, b: str) -> str:
    """SQL: the agents in columns `a` and `b` belong to different operators (needs params()' ind_owners)."""
    grp = ("(SELECT CASE WHEN x.organization_id = ANY(%(ind_owners)s) THEN '' ELSE x.organization_id END "
           "FROM agents x WHERE x.id = {})")
    return f"coalesce({grp.format(a)} <> {grp.format(b)}, false)"


def sql_toward(col: str) -> str:
    """SQL: params()' organization is independent of the work of the agent in `col` (the other direction)."""
    return (f"(%(ind_vetted)s AND coalesce((SELECT x.organization_id <> ALL(%(ind_operator)s) FROM agents x "
            f"WHERE x.id = {col}), false))")
