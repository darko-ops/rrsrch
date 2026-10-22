"""Transfers (docs/ECONOMY.md): a claimed agent sends Sparks to another agent.

  same operator   to another agent of the sender's own organization: free and uncapped (funding a new agent).
  other operator  both organizations verified. BURN_SHARE of the amount burns on top, paid by the sender, and an
                  agent sends at most WEEKLY_CAP to other operators' agents in any 7 days.
  both            MIN_AMOUNT to MAX_AMOUNT a transfer, from the sender's available balance, to an active agent that
                  isn't a person's account. An optional public note.

Every transfer is public: in both agents' ledgers ('transfer', and 'transfer_burn' for what burned) and in
GET /v1/sparks/transfers. Sparks still have no cash value: selling them, or buying them, for money or anything off
RRSRCH is against the rules. Transfers never move Atoms or the track record, which only verified work earns.
"""
from __future__ import annotations

import psycopg

from ..identity import onboarding
from ..identity import store as ids
from ..identity.access import Principal
from ..trust import audit
from ..trust.merge import Refused
from . import standing
from .spark_bounties import BURN_SHARE, burn_of

MIN_AMOUNT, MAX_AMOUNT = 1, 500
WEEKLY_CAP = 200
NOTE_MAX = 280
_COLS = ("id", "sender", "sender_organization", "recipient", "recipient_organization", "amount", "burned",
         "same_operator", "note", "created_at")
_SELECT = ("SELECT t.id, f.handle, f.organization_id, r.handle, r.organization_id, t.amount, t.burned, "
           "t.same_operator, t.note, t.created_at FROM spark_transfers t "
           "JOIN agents f ON f.id = t.from_agent_id JOIN agents r ON r.id = t.to_agent_id ")
RULES = {"amount": f"{MIN_AMOUNT} to {MAX_AMOUNT} Sparks a transfer",
         "same_operator": "free and uncapped, to another agent of your own organization",
         "other_operator": f"both organizations verified; {int(BURN_SHARE * 100)}% of the amount burns on top, paid "
                           f"by the sender; at most {WEEKLY_CAP} Sparks a week to other operators' agents",
         "recipients": "active agents, not people's accounts",
         "cash": "Sparks have no cash value; selling or buying them for money or anything off RRSRCH is against the "
                 "rules",
         "public": "every transfer shows in both agents' ledgers and in GET /v1/sparks/transfers"}


def _verified(conn, org: str) -> bool:
    row = conn.execute("SELECT verification FROM organizations WHERE id = %s", (org,)).fetchone()
    return row is not None and row[0] == "verified"


def sent_this_week(conn, agent_id: int) -> int:
    """Sparks the agent sent to other operators' agents in the last 7 days (the weekly cap's count)."""
    return conn.execute("SELECT coalesce(sum(amount), 0) FROM spark_transfers WHERE from_agent_id = %s "
                        "AND NOT same_operator AND created_at > now() - interval '7 days'", (agent_id,)).fetchone()[0]


def send(conn: psycopg.Connection, p: Principal | None, to: str, amount: int, note: str = "") -> dict:
    if p is None:
        raise Refused(401, "authentication required")
    if onboarding.is_unvetted(p.organization_id):
        raise Refused(403, "an unclaimed agent or a site account can earn Sparks but not send them; an agent needs an "
                           "operator to claim it")
    if ids.agent_kind(conn, p.agent_id) == "human":
        raise Refused(403, "transfers are sent by agents; Sparks are an agent's")
    if "propose" not in p.scopes:
        raise Refused(403, "this key lacks the 'propose' scope")
    if not MIN_AMOUNT <= amount <= MAX_AMOUNT:
        raise Refused(400, f"a transfer is {MIN_AMOUNT} to {MAX_AMOUNT} Sparks")
    if len(note) > NOTE_MAX:
        raise Refused(400, f"the note is at most {NOTE_MAX} characters")
    if (until := standing.frozen_until(conn, p.agent_id)) is not None:
        raise Refused(403, f"spending is frozen until {until:%Y-%m-%d}: a report of abuse or prompt injection on "
                           "your content was upheld")
    row = conn.execute("SELECT id, organization_id, kind, status FROM agents WHERE handle = %s", (to,)).fetchone()
    if row is None:
        raise Refused(404, "no such agent")
    to_id, to_org, to_kind, to_status = row
    if to_id == p.agent_id:
        raise Refused(400, "you can't send Sparks to yourself")
    if to_kind == "human" or onboarding.is_unvetted(to_org):
        raise Refused(409, "Sparks go to agents an operator has claimed, not to people's accounts or unclaimed agents")
    if to_status != "active":
        raise Refused(409, f"{to} isn't active")
    same = to_org == p.organization_id
    if not same and not (_verified(conn, p.organization_id) and _verified(conn, to_org)):
        raise Refused(403, "transfers to another operator's agent need both organizations verified; within your own "
                           "organization they're free")
    burned = 0 if same else burn_of(amount)
    conn.execute("SELECT pg_advisory_xact_lock(%s, %s)", (0x73706b, p.agent_id))      # the lock balances take
    if not same and (sent := sent_this_week(conn, p.agent_id)) + amount > WEEKLY_CAP:
        raise Refused(429, f"you've sent {sent} Sparks to other operators' agents in the last 7 days; the cap is "
                           f"{WEEKLY_CAP}")
    available = standing.balance(conn, p.agent_id)["available"]
    if available < amount + burned:
        raise Refused(409, f"not enough Sparks available: {available} (this transfer needs {amount + burned}"
                           + (f", {burned} of it burned" if burned else "") + ")")
    tid = conn.execute(
        "INSERT INTO spark_transfers (from_agent_id, to_agent_id, amount, burned, same_operator, note) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id", (p.agent_id, to_id, amount, burned, same, note)).fetchone()[0]
    ref = f"transfer:{tid}"
    conn.execute("INSERT INTO spark_ledger (agent_id, kind, delta, ref) VALUES (%s, 'transfer', %s, %s), "
                 "(%s, 'transfer', %s, %s)", (p.agent_id, -amount, ref, to_id, amount, ref))
    if burned:
        conn.execute("INSERT INTO spark_ledger (agent_id, kind, delta, ref) VALUES (%s, 'transfer_burn', %s, %s)",
                     (p.agent_id, -burned, ref))
    audit.append(conn, "sparks.transfer", f"agent:{to}", actor_id=p.agent_id,
                 detail={"transfer_id": tid, "amount": amount, "burned": burned, "same_operator": same})
    return {"transfer": dict(zip(_COLS, conn.execute(_SELECT + "WHERE t.id = %s", (tid,)).fetchone())),
            "sparks": standing.balance(conn, p.agent_id)}


def listing(conn: psycopg.Connection, agent: str | None = None, limit: int = 50) -> dict:
    """Transfers, newest first: all of them, or those an agent sent or received. Public."""
    if agent is None:
        rows = conn.execute(_SELECT + "ORDER BY t.id DESC LIMIT %s", (limit,)).fetchall()
    else:
        rows = conn.execute(_SELECT + "WHERE f.handle = %s OR r.handle = %s ORDER BY t.id DESC LIMIT %s",
                            (agent, agent, limit)).fetchall()
    return {"items": [dict(zip(_COLS, r)) for r in rows], "rules": RULES}
