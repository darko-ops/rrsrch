"""Agents bring sources (docs/SOURCES.md).

A claim can only cite a passage of a stored document, so an agent that needs a source asks the engine to add it.
The agent names it, by a Europe PMC id or DOI (a paper) or by a public https URL (a web page, an SEC filing, an
award notice); the engine fetches it itself and stores exactly what it got, converted to text the same way every
time. Nothing an agent sends becomes document text, so nobody can cite words they wrote. A source already stored is
returned as it is: its text never changes under claims that point into it.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import re
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

import psycopg

from ..corpus import html as htmlmod
from ..corpus import pdf as pdfmod
from ..corpus import snapshot
from ..identity.access import Principal
from ..ledger import db
from ..sources.ctgov import find_nct_ids
from ..sources import web
from ..sources.europepmc import EuropePMC
from ..trust import audit
from ..trust.merge import Refused
from . import query

SOURCE_ID = re.compile(r"^(MED|PMC|PPR):[A-Za-z0-9]{1,20}$")
DOI = re.compile(r"^10\.\d{4,9}/\S{1,200}$")
SOURCES_PER_HOUR = 30
ATTEMPTS_PER_HOUR = 60          # fetches and conversions an agent may start, refused and failed ones included
AT_ONCE = 2                     # an agent's fetches and conversions running at the same time
# EDGAR documents: https://www.sec.gov/Archives/edgar/data/<cik>/<accession, 18 digits>/<file>
SEC_DOC = re.compile(r"^https://www\.sec\.gov/Archives/edgar/data/(?P<cik>\d{1,10})/(?P<acc>\d{18})/(?P<file>[^/?#]+)$")
# the SEC asks automated clients to identify themselves (https://www.sec.gov/os/accessing-edgar-data)
SEC_USER_AGENT = os.environ.get("RRSRCH_SEC_USER_AGENT", "RRSRCH research network https://rrsrch.com")
USER_AGENT = "RRSRCH source fetcher (+https://rrsrch.com/agents.md)"


def _can_add(p: Principal | None) -> Principal:
    if p is None:
        raise Refused(401, "authentication required")
    if p.status != "active":
        raise Refused(403, f"agent is {p.status}")
    if "propose" not in p.scopes:
        raise Refused(403, "key lacks the 'propose' scope")
    return p


def _record(epmc: EuropePMC, source_id: str | None, doi: str | None) -> dict | None:
    if source_id:
        return epmc.record(source_id)
    hits = epmc.search(f'DOI:"{doi}"', page_size=1, result_type="core")
    return hits[0] if hits else None


class _Attempts:
    """Every fetch or conversion an agent starts, whatever came of it, and how many are running now. Kept in the
    engine process (one serves the API), so a restart forgets them; sources added stay counted in the ledger."""

    def __init__(self):
        self.lock = threading.Lock()
        self.started: dict[int, deque] = defaultdict(deque)
        self.running: dict[int, int] = defaultdict(int)

    @contextlib.contextmanager
    def attempt(self, agent_id: int):
        now = time.monotonic()
        with self.lock:
            started = self.started[agent_id]
            while started and started[0] < now - 3600:
                started.popleft()
            if len(started) >= ATTEMPTS_PER_HOUR:
                raise Refused(429, "too many sources tried in the last hour; try again later")
            if self.running[agent_id] >= AT_ONCE:
                raise Refused(429, f"{AT_ONCE} of your sources are already being fetched; wait for them to finish")
            started.append(now)
            self.running[agent_id] += 1
        try:
            yield
        finally:
            with self.lock:
                self.running[agent_id] -= 1
                if not self.running[agent_id]:
                    del self.running[agent_id]

    def reset(self) -> None:
        with self.lock:
            self.started.clear()
            self.running.clear()


ATTEMPTS = _Attempts()


def _rate_limited(conn, p: Principal) -> None:
    n = conn.execute("SELECT count(*) FROM audit_events WHERE actor_id = %s AND action = 'source.add' "
                     "AND at > now() - interval '1 hour'", (p.agent_id,)).fetchone()[0]
    if n >= SOURCES_PER_HOUR:
        raise Refused(429, "too many sources added in the last hour; try again later")


def _url_id(url: str) -> tuple[str, str]:
    """(source id, kind) for a canonical URL: SEC:<accession>:<file> for an EDGAR document, else URL:<hash>."""
    m = SEC_DOC.match(url)
    if m:
        acc = m["acc"]
        return f"SEC:{acc[:10]}-{acc[10:12]}-{acc[12:]}:{m['file']}", "sec"
    return "URL:" + hashlib.sha256(url.encode()).hexdigest()[:24], "url"


def add_url(conn: psycopg.Connection, p: Principal | None, url: str, *, client=None, resolve=None) -> tuple[dict, bool]:
    """Fetch a public https document and store it (provenance `registry` for SEC filings, `fetched` otherwise)."""
    p = _can_add(p)
    try:
        canon = web.canonical(url)
    except web.FetchRefused as e:
        raise Refused(400, str(e)) from e
    sid, kind = _url_id(canon)
    have = conn.execute("SELECT id FROM sources WHERE id = %s OR url = %s", (sid, canon)).fetchone()
    if have:
        return query.get_source(conn, have[0]), False
    _rate_limited(conn, p)
    kw = {"client": client} if client is not None else {}
    if resolve is not None:
        kw["resolve"] = resolve
    with ATTEMPTS.attempt(p.agent_id):                  # counted whether or not it works
        try:
            got = web.fetch(canon, user_agent=SEC_USER_AGENT if kind == "sec" else USER_AGENT, types=web.DOC_TYPES,
                            **kw)
        except web.FetchRefused as e:
            raise Refused(422, str(e)) from e
        final = web.canonical(got.url)
        if final != canon:                              # redirected: store it under where it really lives
            sid, kind = _url_id(final)
            have = conn.execute("SELECT id FROM sources WHERE id = %s OR url = %s", (sid, final)).fetchone()
            if have:
                return query.get_source(conn, have[0]), False
        title, body, converter = _convert(got.body, got.content_type, got.charset)
    if len(body) < 40:
        raise Refused(422, "the page has no readable text to cite")
    title = title[:500] or final
    digest = snapshot.sha256(got.body)
    with conn.transaction():
        conn.execute(
            "INSERT INTO sources (id, title, has_full_text, snapshot_sha256, kind, provenance, url, content_type, "
            "added_by, fetched_at) VALUES (%s, %s, true, %s, %s, %s, %s, %s, %s, %s)",
            (sid, title, digest, kind, "registry" if kind == "sec" else "fetched", final, got.content_type,
             p.agent_id, datetime.now(timezone.utc)))
        db._put_document(conn, sid, "title", title)
        db._put_document(conn, sid, "fulltext", body)
        audit.append(conn, "source.add", f"source:{sid}", actor_id=p.agent_id,
                     detail={"source_id": sid, "kind": kind, "url": final, "content_type": got.content_type,
                             "content_sha256": digest, "converter": converter})
    return query.get_source(conn, sid), True


UPLOAD_TYPES = ("text/html", "application/xhtml+xml", "text/plain", "application/pdf")


def _convert(content: bytes, ctype: str, charset: str | None) -> tuple[str, str, str]:
    """(title, text, converter) of a document's bytes: HTML, plain text or PDF, the same every time."""
    if ctype in web.PDF_TYPES:
        try:
            title, body = pdfmod.to_text(content)
        except pdfmod.PDFRefused as e:
            raise Refused(422, str(e)) from e
        return title, body, pdfmod.VERSION
    text = htmlmod.decode(content, charset)
    if ctype == "text/plain":
        return "", htmlmod.plain(text), htmlmod.VERSION
    try:
        title, body = htmlmod.to_text_isolated(text)
    except htmlmod.HTMLRefused as e:
        raise Refused(422, str(e)) from e
    return title, body, htmlmod.VERSION


def add_upload(conn: psycopg.Connection, p: Principal | None, content: bytes, content_type: str, origin: str,
               title: str = "") -> tuple[dict, bool]:
    """Store a document an agent sent itself, for a source with no public address (docs/SOURCES.md, step 2). It is
    agent-supplied: provenance `uploaded`, kept apart from what the engine fetched, and a repository's claims rest on
    it only if the repository accepts uploads. `origin` is the agent's account of where it came from. The same bytes
    uploaded again are the same source."""
    p = _can_add(p)
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype not in UPLOAD_TYPES:
        raise Refused(422, f"{ctype or 'unknown content'} can't be stored: HTML, plain text and PDF can")
    cap = web.PDF_MAX_BYTES if ctype in web.PDF_TYPES else web.MAX_BYTES
    if not content or len(content) > cap:
        raise Refused(422, f"an upload of {ctype} must be 1 byte to {cap // (1024 * 1024)} MB")
    origin = " ".join((origin or "").split())
    if not 10 <= len(origin) <= 1000:
        raise Refused(400, "say where the document came from (origin, 10 to 1000 characters): who published it, when, and how you got it")
    digest = snapshot.sha256(content)
    sid = f"UP:{digest[:24]}"
    if conn.execute("SELECT 1 FROM sources WHERE id = %s", (sid,)).fetchone():
        return query.get_source(conn, sid), False
    _rate_limited(conn, p)
    with ATTEMPTS.attempt(p.agent_id):
        found_title, body, converter = _convert(content, ctype, "utf-8")
    if len(body) < 40:
        raise Refused(422, "the document has no readable text to cite")
    title = " ".join((title or found_title or origin).split())[:500]
    with conn.transaction():
        conn.execute(
            "INSERT INTO sources (id, title, has_full_text, snapshot_sha256, kind, provenance, content_type, added_by, "
            "fetched_at, origin) VALUES (%s, %s, true, %s, 'upload', 'uploaded', %s, %s, now(), %s)",
            (sid, title, digest, ctype, p.agent_id, origin))
        db._put_document(conn, sid, "title", title)
        db._put_document(conn, sid, "fulltext", body)
        audit.append(conn, "source.add", f"source:{sid}", actor_id=p.agent_id,
                     detail={"source_id": sid, "kind": "upload", "origin": origin, "content_type": ctype,
                             "content_sha256": digest, "converter": converter})
    return query.get_source(conn, sid), True


def add_source(conn: psycopg.Connection, p: Principal | None, *, source_id: str | None = None,
               doi: str | None = None, url: str | None = None, epmc: EuropePMC | None = None,
               client=None, resolve=None) -> tuple[dict, bool]:
    """Store a source: a paper by its Europe PMC id (MED:<pmid>, PMC:<pmcid>, PPR:<id>) or DOI, or a public https
    document by URL. Returns the source, as GET /v1/sources/{id} shows it, and whether it was added now."""
    p = _can_add(p)
    if sum(bool(x) for x in (source_id, doi, url)) != 1:
        raise Refused(400, "give one of: a source_id (MED:<pmid>, PMC:<pmcid> or PPR:<id>), a doi, or an https url")
    if url:
        return add_url(conn, p, url, client=client, resolve=resolve)
    if source_id and not SOURCE_ID.match(source_id):
        raise Refused(400, "source_id must look like MED:<pmid>, PMC:<pmcid> or PPR:<id>")
    if doi and not DOI.match(doi):
        raise Refused(400, "doi must look like 10.<registrant>/<suffix>")
    if source_id and (have := query.get_source(conn, source_id)):
        return have, False
    _rate_limited(conn, p)
    epmc = epmc or EuropePMC()
    with ATTEMPTS.attempt(p.agent_id):
        try:
            r = _record(epmc, source_id, doi)
        except Exception as e:  # noqa: BLE001  (Europe PMC down or refusing: say so, store nothing)
            raise Refused(502, f"Europe PMC could not be reached: {str(e)[:120]}") from e
    if not r or not r.get("source") or not r.get("id"):
        raise Refused(404, "Europe PMC has no such record")
    sid = f"{r['source']}:{r['id']}"
    if not SOURCE_ID.match(sid):
        raise Refused(400, f"unsupported Europe PMC record {sid}")
    if have := query.get_source(conn, sid):
        return have, False
    fulltext = None
    if r.get("isOpenAccess") == "Y" and r.get("pmcid"):
        try:
            fulltext = epmc.full_text_xml(r["pmcid"])
        except Exception:  # noqa: BLE001  (the abstract is still worth storing)
            fulltext = None
    if not r.get("abstractText") and not fulltext:
        raise Refused(422, f"{sid} has no abstract or open full text to cite")
    raw = snapshot.stable_record_bytes(r)
    with conn.transaction():
        parts = db.put_source(conn, sid, r, fulltext, raw)
        conn.execute("UPDATE sources SET added_by = %s, fetched_at = now() WHERE id = %s", (p.agent_id, sid))
        for part in ("abstract", "fulltext"):          # link registered trials we already hold
            for nct in find_nct_ids(parts.get(part) or ""):
                conn.execute("INSERT INTO trial_links (nct_id, source_id, method) SELECT %s, %s, %s "
                             "WHERE EXISTS (SELECT 1 FROM trials WHERE nct_id = %s) ON CONFLICT DO NOTHING",
                             (nct, sid, f"nct_in_{part}", nct))
        audit.append(conn, "source.add", f"source:{sid}", actor_id=p.agent_id,
                     detail={"source_id": sid, "full_text": bool(parts.get("fulltext")),
                             "snapshot_sha256": snapshot.sha256(raw)})
    return query.get_source(conn, sid), True
