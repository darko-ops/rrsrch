"""The reader: turn documents into claims, each pinned to its exact passage.

The model proposes; rules decide. For every claim the model returns:

  1. its quote must be found verbatim in the document (spans.locate), and
  2. the claim must pass the citation gate against its own quote: no number,
     direction, outcome or cell type the quote doesn't contain.

A claim that fails either check is kept in claim_rejections with the rule that
rejected it, never in claims. The rejection rate is reported, not hidden.

Only parts of a paper that report the study's own work are read: the abstract,
and the full text's methods, results and conclusions. Introductions and
discussions are skipped, because their sentences are mostly about other
studies and would be misattributed to this one.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field

import psycopg

from ..check import fields as fieldmod
from ..check import gate
from ..knowledge import store
from . import spans
from .llm import LLM

PROMPT_VERSION = "reader-v1"

SYSTEM = """You extract findings from one clinical study into an evidence ledger.

Return a JSON object: {"claims": [{"quote": "...", "claim": "..."}]}

Rules:
- Only what THIS study did and found: results, and design facts such as sample size, groups, dose and follow-up. Never background, and never results of other studies.
- "quote": one or two consecutive sentences copied exactly from the text, character for character.
- "claim": one finding, restated plainly as a single sentence. Use only the numbers, outcome measures, groups and direction that appear in the quote. Name the outcome measure and what was compared. If a result was not statistically significant, the claim must say so.
- Split compound results into separate claims, one finding each.
- If the text has no findings of this study, return {"claims": []}.

Example text: "At 12 months, WOMAC scores improved more in the MSC group than with hyaluronic acid (p = 0.01), while VAS pain did not differ (p = 0.41)."
Example output: {"claims": [
 {"quote": "At 12 months, WOMAC scores improved more in the MSC group than with hyaluronic acid (p = 0.01), while VAS pain did not differ (p = 0.41).", "claim": "At 12 months, WOMAC scores improved more with MSCs than with hyaluronic acid (p = 0.01)."},
 {"quote": "At 12 months, WOMAC scores improved more in the MSC group than with hyaluronic acid (p = 0.01), while VAS pain did not differ (p = 0.41).", "claim": "At 12 months, VAS pain did not differ between MSCs and hyaluronic acid (p = 0.41)."}
]}"""

USER = "Study: {title}\n\nText:\n{text}"

READ_SECTION = re.compile(r"method|material|patient|participant|design|result|outcome|finding|"
                          r"conclusion|efficacy|safety|follow", re.I)
SKIP_SECTION = re.compile(r"introduction|background|discussion|limitation|reference|acknowledg|"
                          r"funding|conflict|abbreviation|supplementary|author", re.I)
MAX_CHUNK = 3500


@dataclass
class Chunk:
    start: int
    end: int
    text: str

    @property
    def hash(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()[:16]


def chunks(part: str, text: str) -> list[Chunk]:
    """The readable stretches of a document, as offsets into its exact text."""
    if part == "abstract":
        return [Chunk(0, len(text), text)] if text else []
    if part != "fulltext":
        return []
    out: list[Chunk] = []
    reading, cur_start, cur_end, pos = False, None, None, 0
    for block in text.split("\n\n"):
        b_start, b_end = pos, pos + len(block)
        pos = b_end + 2
        is_title = len(block) < 90 and not block.rstrip().endswith((".", ":", ")")) and "\n" not in block
        if is_title:
            if SKIP_SECTION.search(block):
                reading = False
            elif READ_SECTION.search(block):
                reading = True
            continue
        if not reading:
            continue
        if cur_start is not None and b_end - cur_start > MAX_CHUNK:
            out.append(Chunk(cur_start, cur_end, text[cur_start:cur_end]))
            cur_start = None
        if cur_start is None:
            cur_start = b_start
        cur_end = b_end
    if cur_start is not None:
        out.append(Chunk(cur_start, cur_end, text[cur_start:cur_end]))
    return out


@dataclass
class ReadReport:
    chunks_read: int = 0
    chunks_skipped: int = 0
    claims: int = 0
    rejected: dict[str, int] = field(default_factory=dict)


def _reject(conn, doc_id, doc_sha, quote, claim, reason, detail, extractor, rep: ReadReport) -> None:
    conn.execute("INSERT INTO claim_rejections (document_id, doc_sha256, quote, claim_text, reason, "
                 "detail, extractor) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                 (doc_id, doc_sha, quote, claim, reason, detail, extractor))
    rep.rejected[reason] = rep.rejected.get(reason, 0) + 1


def wait_for_answers(conn: psycopg.Connection, pause=time.sleep, poll: float = 10.0, say=print) -> float:
    """Answers come first. The reader and the site's answers share one model; while any answer is waiting or
    being written, the reader holds off so a visitor isn't kept waiting behind corpus extraction.
    Returns the seconds it waited."""
    waited = 0.0
    while True:
        try:
            n = conn.execute("SELECT count(*) FROM answer_jobs WHERE status IN ('queued', 'running')").fetchone()[0]
        except psycopg.errors.UndefinedTable:              # an older ledger without answer jobs
            conn.rollback()
            return waited
        if not n:
            if waited:
                say(f"resuming after {int(waited)}s")
            return waited
        if not waited:
            say(f"pausing: {n} answer(s) waiting or being written")
        pause(poll)
        waited += poll


@dataclass
class Candidate:
    """A claim that passed the reader's rules against its own passage: found verbatim, and no wider than it."""
    claim: str
    quote: str
    start: int
    end: int
    fields: dict
    scope: dict
    self_check: dict


@dataclass
class Rejection:
    quote: str | None
    claim: str | None
    reason: str
    detail: str


def read_chunk(llm: LLM, title: str, text: str, ch: Chunk, context: dict) -> tuple[int, list[Candidate], list[Rejection]]:
    """Ask the model for one chunk's findings and keep only what passes the rules. Touches no database.
    Returns how many items the model gave, the candidates, and the rejections with their reasons."""
    try:
        reply = llm.json_chat(SYSTEM, USER.format(title=title, text=ch.text))
        items = reply.get("claims", [])
        if not isinstance(items, list):
            raise ValueError("'claims' is not a list")
    except (ValueError, KeyError) as e:
        return 0, [], [Rejection(None, None, "bad_reply", str(e)[:300])]
    found: list[Candidate] = []
    rejected: list[Rejection] = []
    for it in items:
        quote = str((it or {}).get("quote") or "")
        claim = " ".join(str((it or {}).get("claim") or "").split())
        if not claim:
            rejected.append(Rejection(quote, claim, "empty_claim", ""))
            continue
        span = spans.locate(quote, text, ch.start, ch.end)
        if span is None:
            rejected.append(Rejection(quote, claim, "quote_not_found", "quote is not in the text verbatim"))
            continue
        passage = text[span[0]:span[1]]
        cf = fieldmod.extract(claim)
        if not (cf.numbers or cf.findings or any(cf.entities.values())):
            rejected.append(Rejection(quote, claim, "nothing_checkable", "claim has no number, direction or named entity"))
            continue
        # the claim may not say more than its own passage: same gate the writer faces,
        # minus the report's population (a claim can be about anyone; scope is checked at use)
        v = gate.check(claim, [gate.CitedClaim("passage", passage, context)], report_scope={}, sentence_fields=cf)
        if not v.passed:
            rejected.append(Rejection(quote, claim, f"gate:{v.rule}", v.detail))
            continue
        found.append(Candidate(claim, passage, span[0], span[1], cf.to_json(),
                               {g: sorted(cf.scope.get(g) or context.get(g, ())) for g in ("species", "joint", "condition")},
                               v.to_json()))
    return len(items), found, rejected


def read_document(conn: psycopg.Connection, llm: LLM, doc: dict, context: dict, rep: ReadReport,
                  wait=wait_for_answers) -> None:
    extractor = f"{llm.model}|{PROMPT_VERSION}"
    for ch in chunks(doc["part"], doc["text"]):
        done = conn.execute("SELECT 1 FROM read_chunks WHERE document_id = %s AND chunk_sha = %s "
                            "AND extractor = %s", (doc["id"], ch.hash, extractor)).fetchone()
        if done:
            rep.chunks_skipped += 1
            continue
        wait(conn)
        n_items, found, rejected = read_chunk(llm, doc["title"], doc["text"], ch, context)
        with conn.transaction():
            for r in rejected:
                _reject(conn, doc["id"], doc["sha256"], r.quote, r.claim, r.reason, r.detail, extractor, rep)
            if rejected and rejected[0].reason == "bad_reply":
                continue
            for c in found:
                # passed the reader's rules against its own passage: structurally valid, not yet reviewed
                claim_id = conn.execute(
                    "INSERT INTO claims (document_id, doc_sha256, span_start, span_end, text, fields, "
                    "scope, extractor, self_check, repository_id, type, state, agent_id) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, "
                    "(SELECT id FROM repositories WHERE slug = %s), 'empirical', 'structurally_valid', "
                    "(SELECT id FROM agents WHERE handle = %s)) RETURNING id",
                    (doc["id"], doc["sha256"], c.start, c.end, c.claim, json.dumps(c.fields), json.dumps(c.scope),
                     extractor, json.dumps(c.self_check), store.PILOT_REPO, store.READER_AGENT)).fetchone()[0]
                store.record_claim(conn, claim_id)
            conn.execute("INSERT INTO read_chunks (document_id, chunk_sha, extractor, span_start, span_end, "
                         "n_claims, n_items) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                         (doc["id"], ch.hash, extractor, ch.start, ch.end, len(found), n_items))
        rep.chunks_read += 1
        rep.claims += len(found)


def read_corpus(conn: psycopg.Connection, llm: LLM, source_ids: list[str] | None = None,
                limit: int | None = None, progress=print, wait=wait_for_answers) -> ReadReport:
    rep = ReadReport()
    rows = conn.execute(
        "SELECT d.id, d.source_id, d.part, d.text, d.sha256, s.title, "
        "  (SELECT text FROM documents a WHERE a.source_id = d.source_id AND a.part = 'abstract') "
        "FROM documents d JOIN sources s ON s.id = d.source_id "
        "WHERE d.part IN ('abstract', 'fulltext') AND (%s::text[] IS NULL OR d.source_id = ANY(%s)) "
        "ORDER BY d.source_id, d.part", (source_ids, source_ids)).fetchall()
    sources = list(dict.fromkeys(r[1] for r in rows))[:limit]
    for i, sid in enumerate(sources, 1):
        for r in (r for r in rows if r[1] == sid):
            doc = {"id": r[0], "source_id": r[1], "part": r[2], "text": r[3], "sha256": r[4], "title": r[5]}
            context = gate.source_context(r[5], r[6] or "")
            read_document(conn, llm, doc, context, rep, wait=wait)
        progress(f"[{i}/{len(sources)}] {sid}: {rep.claims} claims so far, rejected {rep.rejected}")
    return rep
