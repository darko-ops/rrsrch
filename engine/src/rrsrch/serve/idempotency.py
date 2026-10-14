"""Idempotency keys for writes (SPEC-v2 §18.2).

A client that retries a write with the same `Idempotency-Key` header gets the
first response back instead of acting twice. Keys are per agent; using one
key for a different request is a 422. Only successful responses are stored,
so a refused request can be fixed and retried with the same key. The stored
response is written in the same transaction as the write itself.
"""
from __future__ import annotations

import json
from collections.abc import Callable

import psycopg
from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from ..identity.access import Principal
from ..knowledge import canonical


def run(request: Request, c: psycopg.Connection, p: Principal | None, body, fn: Callable[[], tuple[int, dict]]) -> JSONResponse:
    key = request.headers.get("idempotency-key")
    if not key or p is None:
        status, payload = fn()
        return JSONResponse(jsonable_encoder(payload), status_code=status)
    if len(key) > 200:
        return JSONResponse({"ok": False, "error": "idempotency-key is too long"}, status_code=400)
    req_hash = canonical.digest({"method": request.method, "path": request.url.path,
                                 "body": jsonable_encoder(body)})
    c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"idem:{p.agent_id}:{key}",))
    prior = c.execute("SELECT request_hash, status, response FROM idempotency_keys WHERE agent_id = %s AND key = %s",
                      (p.agent_id, key)).fetchone()
    if prior:
        if prior[0] != req_hash:
            return JSONResponse({"ok": False, "error": "idempotency-key was used for a different request"},
                                status_code=422)
        return JSONResponse(prior[2], status_code=prior[1], headers={"Idempotent-Replayed": "true"})
    status, payload = fn()
    payload = jsonable_encoder(payload)
    if 200 <= status < 300:
        c.execute("INSERT INTO idempotency_keys (agent_id, key, request_hash, status, response) "
                  "VALUES (%s, %s, %s, %s, %s)", (p.agent_id, key, req_hash, status, json.dumps(payload)))
    return JSONResponse(payload, status_code=status)
