"""The hub's API (hub.daed.io, the admin hub for daed's products): RRSRCH's figures, agents and reports for its staff.

The hub calls with RRSRCH_ADMIN_TOKEN as a bearer token and the email of the person acting in X-RRSRCH-Staff, which
must be in RRSRCH_ADMIN_STAFF (comma-separated). A missing or wrong token is answered 404, as if there were no such
API; with no token configured, there isn't. Staff act as people, not agents: what they do goes on the audit chain
with their email (detail.staff). The queries are in rrsrch.collab.admin.
"""
from __future__ import annotations

import hmac
import os
from typing import Literal

import psycopg
from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field
from starlette.exceptions import HTTPException

from ..collab import admin
from .body import Body
from .identity_routes import conn
from .trust_routes import _call


def staff(request: Request) -> str:
    """The staff member the hub says is asking, once its token checks out."""
    token = os.environ.get("RRSRCH_ADMIN_TOKEN", "")
    scheme, _, given = request.headers.get("authorization", "").partition(" ")
    if not token or scheme.lower() != "bearer" or not hmac.compare_digest(given.strip(), token):
        raise HTTPException(404)
    who = request.headers.get("x-rrsrch-staff", "").strip().lower()
    allowed = {e.strip().lower() for e in os.environ.get("RRSRCH_ADMIN_STAFF", "").split(",") if e.strip()}
    if who not in allowed:
        raise HTTPException(403, "not on rrsrch's staff list (RRSRCH_ADMIN_STAFF)")
    return who


router = APIRouter(prefix="/v1/admin", include_in_schema=False, dependencies=[Depends(staff)])


def _choice(value: int, allowed: tuple[int, ...], name: str) -> int:
    if value not in allowed:
        raise HTTPException(400, f"{name} must be one of {', '.join(map(str, allowed))}")
    return value


class StatusChange(Body):
    action: Literal["suspend", "reinstate"]
    note: str | None = Field(default=None, max_length=2000)


class ReportDecision(Body):
    action: Literal["hide", "dismiss"]


@router.get("/overview")
def overview(c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True} | admin.overview(c)


@router.get("/growth")
def growth(weeks: int = 12, c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True} | admin.growth(c, _choice(weeks, (12, 26, 52), "weeks"))


@router.get("/engagement")
def engagement(days: int = 7, c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True} | admin.engagement(c, _choice(days, (7, 30, 90), "days"))


@router.get("/experience")
def experience(hours: int = 24, c: psycopg.Connection = Depends(conn)) -> dict:
    hours = _choice(hours, (24, 168, 720), "hours")
    from .api import backup_status                         # api imports this module
    health = {"model": os.environ.get("RRSRCH_READER_MODEL"), "backup": backup_status()}
    return {"ok": True} | admin.experience(c, hours, health)


@router.get("/agents")
def agents(q: str | None = Query(default=None, max_length=100),
           filter: Literal["all", "claimed", "unclaimed", "people", "suspended", "revoked"] = "all",
           sort: Literal["newest", "last_seen", "actions"] = "newest",
           limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
           c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True} | admin.agents(c, q, filter, sort, limit, offset)


@router.get("/agents/{handle}")
def agent(handle: str, c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True} | _call(admin.agent, c, handle)


@router.post("/agents/{handle}")
def change_agent(handle: str, body: StatusChange, who: str = Depends(staff),
                 c: psycopg.Connection = Depends(conn)) -> dict:
    status = "suspended" if body.action == "suspend" else "active"
    return {"ok": True} | _call(admin.set_status, c, handle, status, who, body.note)


@router.get("/reports")
def reports(state: Literal["open", "actioned", "dismissed"] = "open", limit: int = Query(default=100, ge=1, le=500),
            c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True} | admin.reports(c, state, limit)


@router.post("/reports/{report_id}")
def resolve_report(report_id: int, body: ReportDecision, who: str = Depends(staff),
                   c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True, "report_id": report_id, "state": _call(admin.resolve, c, report_id, body.action, who)}


@router.get("/activity")
def activity(limit: int = Query(default=100, ge=1, le=500), c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True, "actions": admin.staff_actions(c, limit)}
