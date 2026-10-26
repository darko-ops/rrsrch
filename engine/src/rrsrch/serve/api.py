"""The engine's HTTP API, on FastAPI: POST /v1/answer, GET /v1/health, and the
identity (identity_routes), review/merge (trust_routes) and knowledge
(knowledge_routes) endpoints, and the hosted MCP server at /mcp (mcp_tools.HostedMCP).

Binds to localhost by default; put a tunnel or reverse proxy in front when the
site needs it. Errors keep the shape the site's proxy reads, {"ok": false,
"error": "..."}, whatever produced them: a bad body, an unknown path or a
failure inside the writer.

Handlers are plain `def`s, so FastAPI runs them in its threadpool: the one-shot
answer waits on the model for minutes, and must not block other requests while
it does. It gives its database connection back before it waits, and only a few
may wait at once (rrsrch.serve.jobs).

The interactive docs (/docs, /redoc) and /openapi.json are served only when
RRSRCH_PUBLIC_DOCS=1.
"""
from __future__ import annotations

import contextlib
import json
import logging
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable

import httpx
import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel
from starlette.exceptions import HTTPException
from starlette.routing import Route

from ..identity import onboarding, store
from ..identity.access import Principal
from ..ledger import db
from ..reader.llm import LLM
from ..sources import web
from . import answer as answer_mod
from . import jobs as jobs_mod
from . import bounty_routes, collab_routes, identity_routes, idempotency, knowledge_routes, mcp_tools, trust_routes
from .identity_routes import client_of

MAX_QUESTION = 800
MAX_BODY = 256 * 1024
# POST /v1/sources/upload: a 50 MB PDF, base64-encoded in JSON, and the few short fields beside it
UPLOAD_BODY = 4 * math.ceil(web.PDF_MAX_BYTES / 3) + 64 * 1024
LARGE_BODIES = ("/v1/sources/upload",)  # routes that take more than MAX_BODY: only callers who sign in get that far
WRITES = ("POST", "PUT", "PATCH", "DELETE")
_EVIDENCE = re.compile(r"^evidence|passage|unknown source|span", re.I)
log = logging.getLogger(__name__)
# Tailscale Funnel connects from loopback and appends the caller's address to X-Forwarded-For; uvicorn takes the
# client from the last address added by a trusted hop, so a forged header changes nothing. Stated here, not left
# to uvicorn's defaults, because the per-IP limits for direct callers depend on it (rrsrch.serve.identity_routes).
SERVER = {"proxy_headers": True, "forwarded_allow_ips": "127.0.0.1"}


def public_docs() -> bool:
    """RRSRCH_PUBLIC_DOCS=1 serves /docs, /redoc and /openapi.json; otherwise they're off."""
    return os.environ.get("RRSRCH_PUBLIC_DOCS", "").strip() == "1"


class AnswerRequest(BaseModel):
    question: str | None = None


def _error(code: int, message: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=code, headers=headers)


def refusal_category(status: int, reason: str) -> str:
    if status == 429:
        return "rate_limit"
    if status in (401, 403):
        return "permission"
    if _EVIDENCE.search(reason):
        return "evidence"
    return "conflict" if status == 409 else "invalid"


def _log_refusal(connect: Callable, agent_id: int, method: str, path: str, status: int, reason: str) -> None:
    """Record a refused write in its own transaction: the request's own was rolled back."""
    try:
        with connect() as c:
            c.execute("INSERT INTO refusals (agent_id, method, path, status, category, reason) "
                      "VALUES (%s, %s, %s, %s, %s, %s)",
                      (agent_id, method, path[:300], status, refusal_category(status, reason), reason[:500]))
    except Exception:            # the record is for standing; never let it break the response
        pass


BACKUP_STATUS = Path(os.environ.get("RRSRCH_BACKUP_STATUS", "~/rrsrch-pg/backups/status.json")).expanduser()


def backup_status() -> dict | None:
    """The last ledger backup, as deploy/spark/backup.sh recorded it: times and state, never error text (this is
    public). None where no backup runs, such as a development machine."""
    try:
        s = json.loads(BACKUP_STATUS.read_text())
    except (OSError, ValueError):
        return None
    out = {k: s.get(k) for k in ("last_state", "last_step", "last_ok_at", "last_verified_at", "last_offsite_at",
                                 "offsite", "accounts_state", "last_accounts_at")}
    if s.get("last_verified_at"):
        age = datetime.now(timezone.utc) - datetime.fromisoformat(s["last_verified_at"])
        out["verified_age_hours"] = round(age.total_seconds() / 3600, 2)
    return out


def create_app(connect: Callable = db.connect, make_llm: Callable[[], LLM] = LLM.from_env,
               answer: Callable = answer_mod.answer, jobs: jobs_mod.AnswerJobs | None = None) -> FastAPI:
    # The hosted MCP server (rrsrch.com/mcp): its tools call this API on loopback with each caller's own key
    mcp = mcp_tools.HostedMCP(lambda: app.state.mcp_api)

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with mcp.running():
            yield

    docs = public_docs()
    app = FastAPI(title="rrsrch engine", version="0.1.0", lifespan=lifespan, docs_url="/docs" if docs else None,
                  redoc_url="/redoc" if docs else None, openapi_url="/openapi.json" if docs else None)
    app.state.connect = connect
    app.state.jobs = jobs or jobs_mod.AnswerJobs(connect, make_llm, answer)
    app.state.mcp_api = httpx.Client(base_url=os.environ.get("RRSRCH_MCP_API_URL", "http://127.0.0.1:8787"),
                                     timeout=120)                       # run() points it at the port it serves
    app.router.routes.append(Route("/mcp", endpoint=mcp, methods=["GET", "POST", "DELETE"]))
    app.add_middleware(CORSMiddleware, allow_origins=[os.environ.get("RRSRCH_CORS_ORIGIN", "*")],
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                       allow_headers=["Content-Type", "Authorization", "Idempotency-Key"])
    app.include_router(identity_routes.router)
    app.include_router(trust_routes.router)
    app.include_router(knowledge_routes.router)
    app.include_router(collab_routes.router)
    app.include_router(bounty_routes.router)

    @app.middleware("http")
    async def bounded_body(request: Request, call_next):
        length = request.headers.get("content-length")
        if length is None:
            # a body without a declared length (chunked) can't be bounded before it's read
            if request.method in ("POST", "PUT", "PATCH") and request.headers.get("transfer-encoding"):
                return _error(411, "send a Content-Length")
        elif not length.strip().isdigit():
            return _error(400, "invalid Content-Length")
        elif int(length) > (cap := UPLOAD_BODY if request.url.path == "/v1/sources/upload" else MAX_BODY):
            return _error(413, f"request body over {cap // 1024} KB")
        return await call_next(request)

    def _signed_in(request: Request) -> bool:
        header = request.headers.get("authorization")
        if not header:                                  # the site, vouching for a signed-in person
            return identity_routes._proxied(request) and bool(request.headers.get("x-rrsrch-site-user", "").strip())
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return False
        with app.state.connect() as c:
            return store.authenticate(c, token.strip()) is not None

    @app.middleware("http")
    async def sign_in_before_large_bodies(request: Request, call_next):
        """A route that takes a large body checks who is calling before the body is read."""
        if request.url.path in LARGE_BODIES and request.method in WRITES:
            try:
                ok = await run_in_threadpool(_signed_in, request)
            except Exception:  # noqa: BLE001
                log.exception("checking the key before an upload failed")
                return _error(503, "the engine can't check keys right now; try again shortly")
            if not ok:
                return _error(401, "authentication required: send 'Authorization: Bearer <key>'")
        return await call_next(request)

    @app.middleware("http")
    async def record_refusals(request: Request, call_next):
        """A write an agent attempted and the engine refused goes on the agent's record (rrsrch.collab.standing).
        Not found is left out: it's what a private repository looks like from outside."""
        response = await call_next(request)
        p = getattr(request.state, "principal", None)
        if idempotency.dry_run(request):              # checking a write first never counts against the agent
            response.headers["X-RRSRCH-Dry-Run"] = "true"
        elif p is not None and request.method in WRITES and 400 <= response.status_code < 500 \
                and response.status_code != 404:
            await run_in_threadpool(_log_refusal, app.state.connect, p.agent_id, request.method, request.url.path,
                                    response.status_code, getattr(request.state, "error", ""))
        return response

    @app.exception_handler(HTTPException)
    def http_error(req: Request, exc: HTTPException) -> JSONResponse:
        message = "not found" if exc.status_code == 404 else str(exc.detail).lower()
        req.state.error = message
        return _error(exc.status_code, message)

    @app.exception_handler(RequestValidationError)
    def bad_body(req: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        unknown = [".".join(str(x) for x in e["loc"] if x != "body")
                   for e in errors if e.get("type") == "extra_forbidden"]
        if any(e.get("type") == "json_invalid" for e in errors):
            message = "body must be JSON"
        elif unknown:                                # refused, not dropped: say which, so the caller can fix it
            message = (f"unknown field{'s' if len(unknown) > 1 else ''}: {', '.join(unknown)}. Nothing was saved"
                       + ("; the fields each endpoint takes are in /openapi.json" if docs else ""))
        else:
            field = ".".join(str(x) for x in errors[0]["loc"] if x != "body")
            message = ("question must be a string" if field == "question" else
                       f"{field}: {errors[0]['msg']}" if field else errors[0]["msg"])
        req.state.error = message
        return _error(400, message)

    @app.get("/v1/health")
    @app.get("/health", include_in_schema=False)
    @app.get("/", include_in_schema=False)
    def health() -> JSONResponse:
        try:
            with connect() as conn:
                n = conn.execute("SELECT count(*) FROM claims c JOIN repositories r ON r.id = c.repository_id "
                                 "WHERE r.deleted_at IS NULL").fetchone()[0]          # retired collections don't count
                busy = conn.execute("SELECT count(*) FROM answer_jobs WHERE status IN ('queued', 'running')").fetchone()[0]
        except Exception:  # noqa: BLE001  the detail can name hosts: logged, not shown
            log.exception("health check failed")
            return _error(503, "the ledger is unavailable")
        # answers_in_progress: the model is shared, so background readers hold off while visitors wait
        return JSONResponse({"ok": True, "claims": n, "model": os.environ.get("RRSRCH_READER_MODEL"),
                             "answers_in_progress": busy, "backup": backup_status()})

    def _submit(question: str, request: Request, p: Principal | None):
        client, agent = client_of(request, p)
        if p is not None and onboarding.is_unvetted(p.organization_id):
            agent = False                               # anyone could have made it: a visitor's share, by key
        try:
            return app.state.jobs.submit(question, client=client, agent=agent), None
        except jobs_mod.RateLimited as e:
            return None, _error(429, str(e), {"Retry-After": "120"})
        except jobs_mod.QueueFull as e:
            return None, _error(429, str(e), {"Retry-After": "60"})

    def _caller(request: Request) -> Principal | None:
        """The caller, on a connection given back at once (the one-shot answer then waits without one)."""
        with app.state.connect() as c:
            return identity_routes.principal(request, c)

    @app.post("/v1/answer")
    @app.post("/answer", include_in_schema=False)
    def answer_route(request: Request, req: AnswerRequest | None = None) -> JSONResponse:
        """One request, one answer: the same queue and limits as /v1/answers, but it waits for the result, up to
        jobs.WAIT seconds. When it can't wait that long, or too many requests are already waiting, it answers 202
        with the job to poll at /v1/answers/{job_id}. Behind a proxy with a short timeout, use /v1/answers."""
        question = " ".join((req.question or "").split()) if req else ""
        if not question:
            return _error(400, "question required")
        if len(question) > MAX_QUESTION:
            return _error(400, "question too long")
        p = _caller(request)
        submitted, refused = _submit(question, request, p)
        if refused:
            return refused
        job, created = submitted
        if job["status"] in ("queued", "running"):
            job = app.state.jobs.wait(job["id"], client_of(request, p)[0]) or job
        if job["status"] == "done":
            return JSONResponse(jsonable_encoder(job["result"]))
        if job["status"] == "failed":
            return _error(500, _job_view(job)["error"])
        body = jsonable_encoder(_job_view(job)) | {"reused": not created, "poll": f"/v1/answers/{job['id']}"}
        return JSONResponse(body, status_code=202)

    def _job_view(job: dict) -> dict:
        out = {"ok": True, "job_id": str(job["id"]), "question": job["question"], "status": job["status"],
               "stage": job["stage"], "created_at": job["created_at"], "finished_at": job["finished_at"]}
        if job["status"] == "done":
            out["answer"] = job["result"]
        if job["status"] == "failed":                   # older jobs recorded what went wrong: never shown
            out["error"] = job["error"] if job["error"] in (jobs_mod.FAILED, jobs_mod.RESTARTED) else jobs_mod.FAILED
        return out

    @app.post("/v1/answers", status_code=202)
    def start_answer(request: Request, req: AnswerRequest | None = None,
                     p: Principal | None = Depends(identity_routes.principal)) -> JSONResponse:
        """Start answering; returns at once with a job to poll. Repeats of a question share one job."""
        question = " ".join((req.question or "").split()) if req else ""
        if not question:
            return _error(400, "question required")
        if len(question) > MAX_QUESTION:
            return _error(400, "question too long")
        submitted, refused = _submit(question, request, p)
        if refused:
            return refused
        job, created = submitted
        body = jsonable_encoder(_job_view(job)) | {"reused": not created}
        return JSONResponse(body, status_code=202 if job["status"] in ("queued", "running") else 200)

    @app.get("/v1/answers/{job_id}")
    def answer_status(job_id: str) -> JSONResponse:
        job = app.state.jobs.get(job_id)
        if job is None:
            return _error(404, "not found")
        return JSONResponse(jsonable_encoder(_job_view(job)))

    return app


def run(host: str = "127.0.0.1", port: int = 8787) -> None:
    print(f"rrsrch engine on http://{host}:{port}  (POST /v1/answer, GET /v1/health"
          + (", docs at /docs)" if public_docs() else "; set RRSRCH_PUBLIC_DOCS=1 for /docs)"))
    app = create_app()
    loopback = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    app.state.mcp_api = httpx.Client(base_url=os.environ.get("RRSRCH_MCP_API_URL", f"http://{loopback}:{port}"),
                                     timeout=120)
    try:
        waiting = app.state.jobs.recover()
        if waiting:
            print(f"restarted {waiting} waiting answer job(s)")
    except Exception as e:  # noqa: BLE001  the API should come up even if the ledger is briefly away
        print(f"could not recover answer jobs: {e}")
    uvicorn.run(app, host=host, port=port, **SERVER)
