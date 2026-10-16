"""The tools an agent gets in each condition, metered, with JSON schemas for model tool-calling.

Corpus tools (every condition): find sources, read a document, locate a quote,
and submit the answer. Reading comes straight from the evaluation database,
not the public API: full text carries per-paper licenses and stays inside the
harness. Repository tools go through the real API with the agent's own key,
so policy, review and permissions apply exactly as they would in production.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import psycopg

from ..knowledge import query
from .budget import Meter

READ_CHARS = 6000          # a read returns at most this much text; ask again with `offset` for more
VERDICTS = ("benefit", "no_difference", "harm", "safe", "mixed", "contested", "uncertain")

SPAN = {"type": "object", "properties": {
    "source_id": {"type": "string"}, "doc_sha256": {"type": "string"},
    "start": {"type": "integer"}, "end": {"type": "integer"}},
    "required": ["source_id", "doc_sha256", "start", "end"]}


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


SCHEMAS: dict[str, tuple[str, dict]] = {
    "find_sources": ("Search the study corpus by title and abstract. Returns source ids, titles and years.",
                     _obj({"query": {"type": "string"}, "limit": {"type": "integer"}}, ["query"])),
    "read_source": ("Read a stored document of a source: part is 'abstract' or 'fulltext'. Long text comes in "
                    f"pages of {READ_CHARS} characters; pass offset to continue.",
                    _obj({"source_id": {"type": "string"}, "part": {"type": "string", "enum": ["abstract", "fulltext"]},
                          "offset": {"type": "integer"}}, ["source_id", "part"])),
    "locate_passage": ("Find a verbatim quote (12+ characters) in a source; returns the exact span to cite.",
                       _obj({"source_id": {"type": "string"}, "quote": {"type": "string"}}, ["source_id", "quote"])),
    "submit_answer": ("Submit your final answer. verdict is one of " + ", ".join(VERDICTS) + ". Cite the spans "
                      "and/or repository claim ids your answer rests on. Ends the task.",
                      _obj({"verdict": {"type": "string", "enum": list(VERDICTS)}, "summary": {"type": "string"},
                            "spans": {"type": "array", "items": SPAN},
                            "claim_ids": {"type": "array", "items": {"type": "integer"}}},
                           ["verdict", "summary"])),
    "search_knowledge": ("Search claims other agents contributed to the shared repository. Check a claim's "
                         "state and challenges before relying on it.",
                         _obj({"query": {"type": "string"}}, ["query"])),
    "get_claim": ("A shared claim with its evidence, state, challenges and contradictions.",
                  _obj({"claim_id": {"type": "integer"}}, ["claim_id"])),
    "propose_claim": ("Contribute a finding to the shared repository so others can reuse it. Word it so the "
                      "cited spans support it exactly; it is checked against them.",
                      _obj({"proposition": {"type": "string"}, "spans": {"type": "array", "items": SPAN}},
                           ["proposition", "spans"])),
    "list_open_merge_requests": ("Contributions by other agents waiting for review.", _obj({}, [])),
    "review_merge_request": ("Review another agent's contribution. Approve only if its spans support it as worded.",
                             _obj({"merge_request_id": {"type": "integer"},
                                   "verdict": {"type": "string", "enum": ["approve", "request_changes", "reject"]},
                                   "findings": {"type": "string"}}, ["merge_request_id", "verdict"])),
    "submit_challenge": ("Object to a shared claim you believe is wrong, ideally citing spans that show it.",
                         _obj({"claim_id": {"type": "integer"},
                               "kind": {"type": "string", "enum": ["contradiction", "missing_assumption",
                                                                   "evidence_problem", "scope", "other"]},
                               "statement": {"type": "string"}, "spans": {"type": "array", "items": SPAN}},
                              ["claim_id", "kind", "statement"])),
}
CONDITION_TOOLS = {
    "A": ("find_sources", "read_source", "locate_passage", "submit_answer"),
    "B": ("find_sources", "read_source", "locate_passage", "submit_answer", "search_knowledge", "get_claim",
          "propose_claim"),
    "C": ("find_sources", "read_source", "locate_passage", "submit_answer", "search_knowledge", "get_claim",
          "propose_claim", "list_open_merge_requests", "review_merge_request", "submit_challenge"),
}


@dataclass
class Answer:
    verdict: str
    summary: str
    spans: list[dict] = field(default_factory=list)
    claim_ids: list[int] = field(default_factory=list)


class Toolbox:
    """One agent's tools for one task, in one condition."""

    def __init__(self, condition: str, api: httpx.Client, connect: Callable[[], psycopg.Connection], meter: Meter,
                 repository: str | None):
        self.condition, self.api, self.connect, self.meter, self.repository = condition, api, connect, meter, repository
        self.names = CONDITION_TOOLS[condition]
        self.answer: Answer | None = None
        self.merge_requests: list[int] = []

    def schemas(self) -> list[dict]:
        """OpenAI-style function tools for this condition."""
        return [{"type": "function", "function": {"name": n, "description": SCHEMAS[n][0], "parameters": SCHEMAS[n][1]}}
                for n in self.names]

    def call(self, name: str, args: dict[str, Any]) -> Any:
        """Run a tool. Unknown or withheld tools are refused like any other bad call, and still cost a call."""
        self.meter.charge_call()
        if name not in self.names:
            # refused by the harness, not the platform: kept apart from the unauthorized-action metric
            self.meter.record(f"withheld:{name}", "", 0)
            return {"error": f"no tool {name} in this condition"}
        try:
            return getattr(self, f"_{name}")(**args)
        except (TypeError, ValueError, AttributeError, KeyError) as e:
            self.meter.record(name, "", 400)
            return {"error": f"bad arguments: {e}"}
        except Exception as e:  # noqa: BLE001  one bad call ends nothing but itself
            self.meter.record(name, "", 0)
            return {"error": f"tool failed: {type(e).__name__}: {e}"[:300]}

    # -- HTTP, recorded for the unauthorized-action metric
    def _http(self, tool: str, key: str, method: str, path: str, **kw) -> dict:
        if "params" in kw:
            kw["params"] = {k: v for k, v in kw["params"].items() if v is not None}
        try:
            r = self.api.request(method, path, **kw)
        except httpx.HTTPError as e:
            self.meter.record(tool, key, 0)
            return {"error": f"API unreachable: {e}"}
        self.meter.record(tool, key, r.status_code)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code >= 400:
            return {"error": body.get("error", r.reason_phrase), "reasons": body.get("reasons", [])}
        body.pop("ok", None)
        return body

    # -- corpus
    def _find_sources(self, query: str, limit: int = 10) -> dict:
        with self.connect() as c:
            rows = c.execute(
                "SELECT s.id, s.title, s.pub_year FROM sources s "
                "LEFT JOIN documents a ON a.source_id = s.id AND a.part = 'abstract', "
                "websearch_to_tsquery('english', %s) q "
                "WHERE to_tsvector('english', s.title || ' ' || coalesce(a.text, '')) @@ q "
                "ORDER BY ts_rank(to_tsvector('english', s.title || ' ' || coalesce(a.text, '')), q) DESC, s.id "
                "LIMIT %s", (query, max(1, min(limit, 25)))).fetchall()
        self.meter.record("find_sources", f"find:{query.lower()}", 200)
        return {"sources": [{"source_id": i, "title": t, "year": y} for i, t, y in rows]}

    def _read_source(self, source_id: str, part: str, offset: int = 0) -> dict:
        with self.connect() as c:
            row = c.execute("SELECT text, sha256 FROM documents WHERE source_id = %s AND part = %s",
                            (source_id, part)).fetchone()
        if row is None:
            self.meter.record("read_source", f"read:{source_id}/{part}", 404)
            return {"error": f"no {part} for {source_id}"}
        self.meter.record("read_source", f"read:{source_id}/{part}", 200)
        text, sha = row
        page = text[offset:offset + READ_CHARS]
        nxt = offset + READ_CHARS if offset + READ_CHARS < len(text) else None
        return {"source_id": source_id, "part": part, "doc_sha256": sha, "offset": offset, "text": page,
                "next_offset": nxt}

    def _locate_passage(self, source_id: str, quote: str) -> dict:
        with self.connect() as c:
            spans = query.locate(c, source_id, quote)
        self.meter.record("locate_passage", f"locate:{source_id}", 200)
        return {"spans": spans}

    def _submit_answer(self, verdict: str, summary: str, spans: list[dict] | None = None,
                       claim_ids: list[int] | None = None) -> dict:
        if verdict not in VERDICTS:
            self.meter.record("submit_answer", "", 400)
            return {"error": f"verdict must be one of {', '.join(VERDICTS)}"}
        self.answer = Answer(verdict, summary, list(spans or []), [int(x) for x in claim_ids or []])
        self.meter.record("submit_answer", "", 200)
        return {"accepted": True}

    # -- shared repository (B, C)
    def _search_knowledge(self, query: str) -> dict:
        return self._http("search_knowledge", f"search:{query.lower()}", "GET", "/v1/search",
                          params={"q": query, "repository": self.repository, "limit": 10})

    def _get_claim(self, claim_id: int) -> dict:
        return self._http("get_claim", f"claim:{claim_id}", "GET", f"/v1/claims/{claim_id}")

    def _propose_claim(self, proposition: str, spans: list[dict]) -> dict:
        content = {"type": "empirical", "proposition": proposition,
                   "evidence": [["supports", {k: s.get(k) for k in ("source_id", "doc_sha256", "start", "end")}]
                                for s in spans]}
        out = self._http("propose_claim", "", "POST", f"/v1/repos/{self.repository}/claims", json={"content": content})
        if "merge_request_id" in out:
            self.merge_requests.append(out["merge_request_id"])
        return out

    def _list_open_merge_requests(self) -> dict:
        with self.connect() as c:
            rows = c.execute(
                "SELECT m.id, m.content->>'proposition', a.handle FROM merge_requests m JOIN agents a ON a.id = m.author_id "
                "JOIN repositories r ON r.id = m.repository_id WHERE r.slug = %s AND m.state = 'open' ORDER BY m.id",
                (self.repository,)).fetchall()
        self.meter.record("list_open_merge_requests", "", 200)
        return {"merge_requests": [{"id": i, "proposition": p, "author": a} for i, p, a in rows]}

    def _review_merge_request(self, merge_request_id: int, verdict: str, findings: str = "") -> dict:
        return self._http("review_merge_request", f"mr:{merge_request_id}", "POST", "/v1/reviews",
                          json={"target": f"proposal:{merge_request_id}", "verdict": verdict, "findings": findings})

    def _submit_challenge(self, claim_id: int, kind: str, statement: str, spans: list[dict] | None = None) -> dict:
        ev = [{k: s.get(k) for k in ("source_id", "doc_sha256", "start", "end")} for s in spans or []]
        return self._http("submit_challenge", f"claim:{claim_id}", "POST", "/v1/reviews",
                          json={"target": f"claim:{claim_id}", "verdict": "object", "objection": kind,
                                "findings": statement, "evidence": ev, "blocking": True})
