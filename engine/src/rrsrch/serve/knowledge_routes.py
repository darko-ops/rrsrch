"""Knowledge endpoints (SPEC-v2 §18.1): repositories, claims, revisions, evidence, provenance, search.

Reads go through rrsrch.knowledge.query, which only returns what the caller
may read; anything else is a 404. Writes that change knowledge (submitting a
claim, adding evidence) open a merge request, so they meet the same checks,
review and audit as any other change. Writes accept an Idempotency-Key.
"""
from __future__ import annotations

import base64
import binascii
from typing import Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder as jsonable
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException

from ..identity.access import NETWORK_ORG, Principal
from ..knowledge import ingest, query, repos
from ..knowledge.models import REPO_SLUG
from ..trust import merge
from . import idempotency
from .identity_routes import conn, principal
from .trust_routes import _call, _checks

router = APIRouter(prefix="/v1")
Limit = Query(default=50, ge=1, le=query.MAX_LIMIT)
After = Query(default=0, ge=0)


def _found(value):
    if value is None:
        raise HTTPException(404)
    return value


class NewRepo(BaseModel):
    slug: str = Field(pattern=REPO_SLUG)
    topic: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    visibility: Literal["public", "private"]
    policy: dict[str, Any] = Field(default_factory=dict)


class RepoChange(BaseModel):
    topic: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    visibility: Literal["public", "private"] | None = None
    policy: dict[str, Any] | None = None


class NewClaim(BaseModel):
    content: dict[str, Any]


class NewSource(BaseModel):
    source_id: str | None = Field(default=None, max_length=40)
    doi: str | None = Field(default=None, max_length=220)
    url: str | None = Field(default=None, max_length=2000)


def _policy_error(e: ValueError) -> HTTPException:
    errors = getattr(e, "errors", None)
    return HTTPException(400, f"policy: {errors()[0]['msg'] if errors else e}")


def _merge_response(out: merge.Outcome) -> tuple[int, dict]:
    return 201, {"ok": True, "merge_request_id": out.merge_request_id, "state": out.state,
                 "checks_passed": all(x.passed for x in out.checks), "checks": _checks(out.checks)}


@router.get("/repos")
def list_repos(after: int = After, limit: int = Limit, p: Principal | None = Depends(principal),
               c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True} | query.list_repos(c, p, after, limit)


@router.post("/repos", status_code=201)
def create_repo(body: NewRepo, request: Request, p: Principal | None = Depends(principal),
                c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    def go():
        try:
            _call(repos.create, c, p, body.slug, body.topic, body.description, body.visibility, body.policy)
        except ValueError as e:                      # policy rules that don't validate
            raise _policy_error(e) from e
        return 201, {"ok": True, "repository": query.get_repo(c, p, body.slug)}
    return idempotency.run(request, c, p, body, go)


@router.get("/repos/{owner}/{name}")
def get_repo(owner: str, name: str, p: Principal | None = Depends(principal),
             c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True, "repository": _found(query.get_repo(c, p, f"{owner}/{name}"))}


@router.patch("/repos/{owner}/{name}")
def update_repo(owner: str, name: str, body: RepoChange, p: Principal | None = Depends(principal),
                c: psycopg.Connection = Depends(conn)) -> dict:
    try:
        _call(repos.update, c, p, f"{owner}/{name}", topic=body.topic, description=body.description,
              visibility=body.visibility, rules=body.policy)
    except ValueError as e:
        raise _policy_error(e) from e
    return {"ok": True, "repository": query.get_repo(c, p, f"{owner}/{name}")}


@router.get("/repos/{owner}/{name}/atlas")
def repo_atlas(owner: str, name: str, limit: int = Query(default=300, ge=1, le=1000),
               p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    """The repository's knowledge as one graph: claims, the sources and trials they rest on, who wrote them,
    and how claims relate (agree, contradict, derive). Per-claim detail is in /v1/claims/{id}/provenance."""
    repo = _found(query.get_repo(c, p, f"{owner}/{name}"))
    return {"ok": True, "repository": repo["slug"]} | query.atlas(c, repo["id"], limit)


@router.get("/repos/{owner}/{name}/history")
def repo_history(owner: str, name: str, after: int = After, limit: int = Limit,
                 p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    repo = _found(query.get_repo(c, p, f"{owner}/{name}"))
    return {"ok": True, "repository": repo["slug"]} | query.repo_history(c, repo["id"], after, limit)


@router.post("/repos/{owner}/{name}/claims", status_code=201)
def submit_claim(owner: str, name: str, body: NewClaim, request: Request, p: Principal | None = Depends(principal),
                 c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    """Propose a new claim. It enters the repository when its merge request is merged."""
    slug = f"{owner}/{name}"
    content = {"repository": slug} | body.content
    return idempotency.run(request, c, p, body,
                           lambda: _merge_response(_call(merge.open_request, c, p, slug, content, None)))


@router.get("/claims/{claim_id}")
def get_claim(claim_id: int, p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True, "claim": _found(query.get_claim(c, p, claim_id))}


@router.get("/claims/{claim_id}/revisions")
def claim_revisions(claim_id: int, p: Principal | None = Depends(principal),
                    c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True, "claim_id": claim_id, "revisions": _found(query.revisions(c, p, claim_id))}


@router.get("/claims/{claim_id}/provenance")
def claim_provenance(claim_id: int, p: Principal | None = Depends(principal),
                     c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True} | _found(query.provenance(c, p, claim_id))


@router.get("/sources/{source_id}")
def get_source(source_id: str, c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True, "source": _found(query.get_source(c, source_id))}


@router.post("/sources")
def add_source(body: NewSource, p: Principal | None = Depends(principal),
               c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    """Bring a source so claims can cite it: a paper by Europe PMC id (MED:<pmid>, PMC:<pmcid>) or DOI, or any
    public https document by `url` (a web page, an SEC filing, an award notice; HTML or plain text for now). The
    engine fetches it itself and records where it came from (docs/SOURCES.md). Needs a key with the propose scope.
    A source already stored comes back unchanged (200); a new one is 201."""
    src, added = _call(ingest.add_source, c, p, source_id=body.source_id, doi=body.doi, url=body.url)
    return JSONResponse({"ok": True, "added": added, "source": jsonable(src)}, status_code=201 if added else 200)


class NewUpload(BaseModel):
    content_base64: str = Field(min_length=4, max_length=70_000_000)        # 50 MB (a PDF), base64-encoded
    content_type: str = Field(max_length=100)
    origin: str = Field(min_length=10, max_length=1000)
    title: str = Field(default="", max_length=500)


@router.post("/sources/upload")
def upload_source(body: NewUpload, p: Principal | None = Depends(principal),
                  c: psycopg.Connection = Depends(conn)) -> JSONResponse:
    """Send a document yourself, for a source with no public address (a paywalled article, a private report): HTML
    or plain text, base64-encoded, up to 10 MB, with `origin` saying who published it, when, and how you got it.
    It is stored as agent-supplied (provenance `uploaded`); repositories accept such sources only if their policy
    says so. Prefer POST /v1/sources with a URL whenever the document is public. 201 new, 200 already stored."""
    try:
        content = base64.b64decode(body.content_base64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise HTTPException(400, "content_base64 is not valid base64") from e
    src, added = _call(ingest.add_upload, c, p, content, body.content_type, body.origin, body.title)
    return JSONResponse({"ok": True, "added": added, "source": jsonable(src)}, status_code=201 if added else 200)


@router.get("/answer-gaps")
def answer_gaps(after: int = After, limit: int = Query(default=20, ge=1, le=100),
                p: Principal | None = Depends(principal), c: psycopg.Connection = Depends(conn)) -> dict:
    """Questions people searched where the ledger had too little to answer (fewer than 3 matching claims), oldest
    first, each question once. Only the text is returned, never who asked. RRSRCH's own agents use it to decide
    what to read next; other callers get 403."""
    if p is None or p.status != "active" or "read" not in p.scopes or p.organization_id != NETWORK_ORG:
        raise HTTPException(403, f"only {NETWORK_ORG}'s own agents read answer gaps")
    rows = c.execute(
        "SELECT max(id), min(question), count(*) FROM reports WHERE bench_id IS NULL AND id > %s "
        "AND cardinality(claims_shown) < 3 GROUP BY lower(question) ORDER BY 1 LIMIT %s", (after, limit)).fetchall()
    items = [{"id": r[0], "question": r[1], "asked": r[2]} for r in rows]
    return {"ok": True, "items": items, "next": items[-1]["id"] if len(items) == limit else None}


@router.get("/sources/{source_id}/locate")
def locate(source_id: str, quote: str = Query(min_length=12, max_length=2000),
           c: psycopg.Connection = Depends(conn)) -> dict:
    """The exact span to cite for a quote: document hash and character offsets."""
    _found(query.get_source(c, source_id))
    return {"ok": True, "source_id": source_id, "spans": query.locate(c, source_id, quote)}


@router.get("/search")
def search(q: str = Query(min_length=1, max_length=500), repository: str | None = None,
           state: str | None = None, type: str | None = None, limit: int = Query(default=20, ge=1, le=100),
           offset: int = Query(default=0, ge=0, le=10_000), p: Principal | None = Depends(principal),
           c: psycopg.Connection = Depends(conn)) -> dict:
    return {"ok": True, "q": q} | query.search(c, p, q, repository=repository, state=state, type_=type,
                                               limit=limit, offset=offset)
