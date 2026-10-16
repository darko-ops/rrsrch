"""Adding a paper to the shared sources while the engine runs.

A claim can only cite a passage of a stored document, so an agent that found a new paper asks the engine to add
it. The agent names the paper; the engine fetches it from Europe PMC itself and stores exactly what Europe PMC
returned, the abstract always and the full text when the paper is open access. Nothing an agent sends becomes
document text, so nobody can cite words they wrote. A source already stored is returned as it is: its text never
changes under claims that point into it.
"""
from __future__ import annotations

import re

import psycopg

from ..corpus import snapshot
from ..identity.access import Principal
from ..ledger import db
from ..sources.ctgov import find_nct_ids
from ..sources.europepmc import EuropePMC
from ..trust import audit
from ..trust.merge import Refused
from . import query

SOURCE_ID = re.compile(r"^(MED|PMC|PPR):[A-Za-z0-9]{1,20}$")
DOI = re.compile(r"^10\.\d{4,9}/\S{1,200}$")
SOURCES_PER_HOUR = 30


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


def add_source(conn: psycopg.Connection, p: Principal | None, *, source_id: str | None = None,
               doi: str | None = None, epmc: EuropePMC | None = None) -> tuple[dict, bool]:
    """Store a paper by its Europe PMC id (MED:<pmid>, PMC:<pmcid>, PPR:<id>) or DOI. Returns the source, as
    GET /v1/sources/{id} shows it, and whether it was added now."""
    p = _can_add(p)
    if bool(source_id) == bool(doi):
        raise Refused(400, "give a source_id (MED:<pmid>, PMC:<pmcid> or PPR:<id>) or a doi")
    if source_id and not SOURCE_ID.match(source_id):
        raise Refused(400, "source_id must look like MED:<pmid>, PMC:<pmcid> or PPR:<id>")
    if doi and not DOI.match(doi):
        raise Refused(400, "doi must look like 10.<registrant>/<suffix>")
    if source_id and (have := query.get_source(conn, source_id)):
        return have, False
    n = conn.execute("SELECT count(*) FROM audit_events WHERE actor_id = %s AND action = 'source.add' "
                     "AND at > now() - interval '1 hour'", (p.agent_id,)).fetchone()[0]
    if n >= SOURCES_PER_HOUR:
        raise Refused(429, "too many sources added in the last hour; try again later")
    epmc = epmc or EuropePMC()
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
        for part in ("abstract", "fulltext"):          # link registered trials we already hold
            for nct in find_nct_ids(parts.get(part) or ""):
                conn.execute("INSERT INTO trial_links (nct_id, source_id, method) SELECT %s, %s, %s "
                             "WHERE EXISTS (SELECT 1 FROM trials WHERE nct_id = %s) ON CONFLICT DO NOTHING",
                             (nct, sid, f"nct_in_{part}", nct))
        audit.append(conn, "source.add", f"source:{sid}", actor_id=p.agent_id,
                     detail={"source_id": sid, "full_text": bool(parts.get("fulltext")),
                             "snapshot_sha256": snapshot.sha256(raw)})
    return query.get_source(conn, sid), True
