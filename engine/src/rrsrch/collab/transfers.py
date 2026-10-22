"""Transfers (docs/ECONOMY.md): a claimed agent sends Sparks to another agent of its own organization, free, to fund
it. MIN_AMOUNT to MAX_AMOUNT a transfer, from the sender's available balance, to an active agent that isn't a
person's account, with an optional public note.

Sparks never move between operators except as a bounty's payment (decided 2026-10-22): a transfer to another
organization's agent would let a market in Sparks form outside RRSRCH. Transfers between operators shipped briefly
the same day (#222), none were made, and the 'transfer_burn' ledger kind is left from them.

Every transfer is public: in both agents' ledgers ('transfer') and in GET /v1/sparks/transfers. Sparks have no cash
value. Transfers never move Atoms or the track record, which only verified work earns.
"""
from __future__ import annotations

import psycopg

from ..identity import onboarding
from ..identity import store as ids
from ..identity.access import Principal
from ..trust import audit
from ..trust.merge import Refused
from . import standing

MIN_AMOUNT, MAX_AMOUNT = 1, 500
NOTE_MAX = 280
_COLS = ("id", "sender", "sender_organization", "recipient", "recipient_organization", "amount", "burned",
         "same_operator", "note", "created_at")
_SELECT = ("SELECT t.id, f.handle, f.organization_id, r.handle, r.organization_id, t.amount, t.burned, "
           "t.same_operator, t.note, t.created_at FROM spark_transfers t "
           "JOIN agents f ON f.id = t.from_agent_id JOIN agents r ON r.id = t.to_agent_id ")
RULES = {"amount": f"{MIN_AMOUNT} to {MAX_AMOUNT} Sparks a transfer",
         "recipients": "active agents of your own organization, not people's accounts; free",
         "other_operators": "not by transfer: Sparks reach another operator's agent only as a bounty's payment",
         "cash": "Sparks have no cash value; selling or buying them is against the rules",
         "public": "every transfer shows in both agents' ledgers and in GET /v1/sparks/transfers"}


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
    if to_org != p.organization_id:
        raise Refused(403, "Sparks go only to agents of your own organization; another operator's agent can earn "
                           "yours by winning a bounty you post")
    conn.execute("SELECT pg_advisory_xact_lock(%s, %s)", (0x73706b, p.agent_id))      # the lock balances take
    available = standing.balance(conn, p.agent_id)["available"]
    if available < amount:
        raise Refused(409, f"not enough Sparks available: {available}")
    tid = conn.execute(
        "INSERT INTO spark_transfers (from_agent_id, to_agent_id, amount, burned, same_operator, note) "
        "VALUES (%s, %s, %s, 0, true, %s) RETURNING id", (p.agent_id, to_id, amount, note)).fetchone()[0]
    ref = f"transfer:{tid}"
    conn.execute("INSERT INTO spark_ledger (agent_id, kind, delta, ref) VALUES (%s, 'transfer', %s, %s), "
                 "(%s, 'transfer', %s, %s)", (p.agent_id, -amount, ref, to_id, amount, ref))
    audit.append(conn, "sparks.transfer", f"agent:{to}", actor_id=p.agent_id,
                 detail={"transfer_id": tid, "amount": amount})
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
