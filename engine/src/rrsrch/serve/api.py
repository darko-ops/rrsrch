"""The engine's HTTP API, on FastAPI: POST /v1/answer, GET /v1/health, and the
identity (identity_routes), review/merge (trust_routes) and knowledge
(knowledge_routes) endpoints.

Binds to localhost by default; put a tunnel or reverse proxy in front when the
site needs it. Errors keep the shape the site's proxy reads, {"ok": false,
"error": "..."}, whatever produced them: a bad body, an unknown path or a
failure inside the writer.

Handlers are plain `def`s, so FastAPI runs them in its threadpool: an answer
holds a database connection and waits on the model for minutes, and must not
block other requests while it does.
"""
from __future__ import annotations

import os
from collections.abc import Callable

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from ..ledger import db
from ..reader.llm import LLM
from . import answer as answer_mod
from . import collab_routes, identity_routes, knowledge_routes, trust_routes

MAX_QUESTION = 800
MAX_BODY = 256 * 1024


class AnswerRequest(BaseModel):
    question: str | None = None


def _error(code: int, message: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=code)


def create_app(connect: Callable = db.connect, make_llm: Callable[[], LLM] = LLM.from_env,
               answer: Callable = answer_mod.answer) -> FastAPI:
    app = FastAPI(title="rrsrch engine", version="0.1.0")
    app.state.connect = connect
    app.add_middleware(CORSMiddleware, allow_origins=[os.environ.get("RRSRCH_CORS_ORIGIN", "*")],
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                       allow_headers=["Content-Type", "Authorization", "Idempotency-Key"])
    app.include_router(identity_routes.router)
    app.include_router(trust_routes.router)
    app.include_router(knowledge_routes.router)
    app.include_router(collab_routes.router)

    @app.middleware("http")
    async def bounded_body(request: Request, call_next):
        length = request.headers.get("content-length")
        if length is None:
            # a body without a declared length (chunked) can't be bounded before it's read
            if request.method in ("POST", "PUT", "PATCH") and request.headers.get("transfer-encoding"):
                return _error(411, "send a Content-Length")
        elif not length.strip().isdigit():
            return _error(400, "invalid Content-Length")
        elif int(length) > MAX_BODY:
            return _error(413, f"request body over {MAX_BODY // 1024} KB")
        return await call_next(request)

    @app.exception_handler(HTTPException)
    def http_error(_req: Request, exc: HTTPException) -> JSONResponse:
        return _error(exc.status_code, "not found" if exc.status_code == 404 else str(exc.detail).lower())

    @app.exception_handler(RequestValidationError)
    def bad_body(_req: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        if any(e.get("type") == "json_invalid" for e in errors):
            return _error(400, "body must be JSON")
        field = ".".join(str(x) for x in errors[0]["loc"] if x != "body")
        if field == "question":
            return _error(400, "question must be a string")
        return _error(400, f"{field}: {errors[0]['msg']}" if field else errors[0]["msg"])

    @app.get("/v1/health")
    @app.get("/health", include_in_schema=False)
    @app.get("/", include_in_schema=False)
    def health() -> JSONResponse:
        try:
            with connect() as conn:
                n = conn.execute("SELECT count(*) FROM claims").fetchone()[0]
        except Exception as e:  # noqa: BLE001
            return _error(503, str(e)[:200])
        return JSONResponse({"ok": True, "claims": n, "model": os.environ.get("RRSRCH_READER_MODEL")})

    @app.post("/v1/answer")
    @app.post("/answer", include_in_schema=False)
    def answer_route(req: AnswerRequest | None = None) -> JSONResponse:
        question = " ".join((req.question or "").split()) if req else ""
        if not question:
            return _error(400, "question required")
        if len(question) > MAX_QUESTION:
            return _error(400, "question too long")
        try:
            llm = make_llm()
            with connect() as conn:
                db.migrate(conn)
                return JSONResponse(answer(conn, llm, question))
        except Exception as e:  # noqa: BLE001
            return _error(500, str(e)[:400])

    return app


def run(host: str = "127.0.0.1", port: int = 8787) -> None:
    print(f"rrsrch engine on http://{host}:{port}  (POST /v1/answer, GET /v1/health, docs at /docs)")
    uvicorn.run(create_app(), host=host, port=port)
