"""Reading knowledge: repositories, claims, revisions, evidence, provenance, search.

Every query is limited to what the caller may read. `visible` is the SQL
form of rrsrch.identity.access.decide(p, READ, ...) and must agree with it
(tests check that it does); a claim in a repository the caller can't read is
reported as missing, not forbidden.

Lists page by id: pass the last id seen as `after`; `next` is None on the
last page.
"""
from __future__ import annotations

import psycopg

from ..identity.access import Principal

MAX_LIMIT = 200


def visible(p: Principal | None, alias: str = "r") -> tuple[str, dict]:
    """A WHERE fragment true for repositories `p` may read."""
    if p is None or p.status != "active" or "read" not in p.scopes:
        return f"{alias}.visibility = 'public'", {}
    return (f"({alias}.visibility = 'public' "
            f"OR EXISTS (SELECT 1 FROM memberships m WHERE m.repository_id = {alias}.id AND m.agent_id = %(vis_agent)s) "
            f"OR ({alias}.organization_id = %(vis_org)s AND %(vis_admin)s))"), \
        {"vis_agent": p.agent_id, "vis_org": p.organization_id, "vis_admin": p.org_role == "admin"}


def _page(rows: list[dict], limit: int) -> dict:
    return {"items": rows, "next": rows[-1]["id"] if len(rows) == limit else None}


def _rows(cur, cols) -> list[dict]:
    return [dict(zip(cols, r)) for r in cur]


REPO_COLS = ("id", "slug", "organization_id", "topic", "description", "visibility", "policy_version", "created_at",
             "claims", "open_merge_requests")
_REPO_SELECT = ("SELECT r.id, r.slug, r.organization_id, r.topic, r.description, r.visibility, r.policy_version, "
                "r.created_at, (SELECT count(*) FROM claims c WHERE c.repository_id = r.id), "
                "(SELECT count(*) FROM merge_requests mr WHERE mr.repository_id = r.id AND mr.state = 'open') "
                "FROM repositories r")


def list_repos(conn: psycopg.Connection, p: Principal | None, after: int = 0, limit: int = 50) -> dict:
    where, params = visible(p)
    rows = _rows(conn.execute(f"{_REPO_SELECT} WHERE {where} AND r.id > %(after)s ORDER BY r.id LIMIT %(limit)s",
                              params | {"after": after, "limit": limit}), REPO_COLS)
    return _page(rows, limit)


def get_repo(conn: psycopg.Connection, p: Principal | None, slug: str) -> dict | None:
    where, params = visible(p)
    row = conn.execute(f"{_REPO_SELECT} WHERE {where} AND r.slug = %(slug)s", params | {"slug": slug}).fetchone()
    if row is None:
        return None
    repo = dict(zip(REPO_COLS, row))
    repo["policy"] = conn.execute("SELECT rules FROM policies WHERE repository_id = %s AND version = %s",
                                  (repo["id"], repo["policy_version"])).fetchone()[0]
    repo["claims_by_state"] = dict(conn.execute(
        "SELECT state, count(*) FROM claims WHERE repository_id = %s GROUP BY state ORDER BY state", (repo["id"],)))
    return repo


def repo_history(conn: psycopg.Connection, repository_id: int, after: int = 0, limit: int = 50) -> dict:
    """Accepted revisions in the order they were accepted."""
    cols = ("id", "claim_id", "version", "content_hash", "author", "merge_request_id", "merged_by", "created_at")
    rows = _rows(conn.execute(
        "SELECT rv.id, rv.claim_id, rv.version, rv.content_hash, a.handle, mr.id, m.handle, rv.created_at "
        "FROM claim_revisions rv JOIN claims c ON c.id = rv.claim_id JOIN agents a ON a.id = rv.agent_id "
        "LEFT JOIN merge_requests mr ON mr.merged_revision_id = rv.id LEFT JOIN agents m ON m.id = mr.decided_by "
        "WHERE c.repository_id = %s AND rv.id > %s ORDER BY rv.id LIMIT %s", (repository_id, after, limit)), cols)
    return _page(rows, limit)


def _visible_claim(conn, p: Principal | None, claim_id: int) -> tuple | None:
    where, params = visible(p)
    return conn.execute(
        "SELECT c.id, r.slug, c.type, c.state, c.text, c.scope, a.handle, c.created_at, r.id "
        f"FROM claims c JOIN repositories r ON r.id = c.repository_id JOIN agents a ON a.id = c.agent_id "
        f"WHERE c.id = %(claim)s AND {where}", params | {"claim": claim_id}).fetchone()


EVIDENCE_COLS = ("id", "relation", "source_id", "source_title", "doc_sha256", "span_start", "span_end", "excerpt",
                 "is_primary", "license", "retrieved_at")


def _evidence(conn, claim_id: int) -> list[dict]:
    return _rows(conn.execute(
        "SELECT e.id, l.relation, e.source_id, s.title, e.doc_sha256, e.span_start, e.span_end, e.excerpt, "
        "e.is_primary, e.license, e.retrieved_at FROM evidence_links l JOIN evidence e ON e.id = l.evidence_id "
        "JOIN sources s ON s.id = e.source_id WHERE l.claim_id = %s ORDER BY e.id, l.relation", (claim_id,)),
        EVIDENCE_COLS)


def _head(conn, claim_id: int) -> dict | None:
    row = conn.execute("SELECT id, version, content_hash, created_at FROM claim_revisions WHERE claim_id = %s "
                       "ORDER BY version DESC LIMIT 1", (claim_id,)).fetchone()
    return dict(zip(("id", "version", "content_hash", "created_at"), row)) if row else None


def _relations(conn, p: Principal | None, claim_id: int) -> list[dict]:
    """Skeptic findings: other readable claims this one agrees or conflicts with."""
    where, params = visible(p)
    return _rows(conn.execute(
        "SELECT o.id, ag.verdict, ag.rule, ag.detail FROM claim_agreements ag "
        "JOIN claims o ON o.id = CASE WHEN ag.claim_a_id = %(claim)s THEN ag.claim_b_id ELSE ag.claim_a_id END "
        f"JOIN repositories r ON r.id = o.repository_id "
        f"WHERE (ag.claim_a_id = %(claim)s OR ag.claim_b_id = %(claim)s) AND {where} ORDER BY ag.verdict DESC, o.id",
        params | {"claim": claim_id}), ("claim_id", "verdict", "rule", "detail"))


def get_claim(conn: psycopg.Connection, p: Principal | None, claim_id: int) -> dict | None:
    row = _visible_claim(conn, p, claim_id)
    if row is None:
        return None
    claim = dict(zip(("id", "repository", "type", "state", "proposition", "scope", "contributor", "created_at"), row))
    head = _head(conn, claim_id)
    run = None
    if head:
        r = conn.execute("SELECT id, policy_version, checks, passed, created_at FROM verification_runs "
                         "WHERE claim_revision_id = %s ORDER BY id DESC LIMIT 1", (head["id"],)).fetchone()
        run = dict(zip(("id", "policy_version", "checks", "passed", "created_at"), r)) if r else None
    rel = _relations(conn, p, claim_id)
    return claim | {"head": head, "evidence": _evidence(conn, claim_id), "verification": run,
                    "contradicted_by": [x for x in rel if x["verdict"] == "contradicts"],
                    "agrees_with": [x for x in rel if x["verdict"] == "agrees"]}


def revisions(conn: psycopg.Connection, p: Principal | None, claim_id: int) -> list[dict] | None:
    if _visible_claim(conn, p, claim_id) is None:
        return None
    return _rows(conn.execute(
        "SELECT rv.id, rv.version, rv.parent_id, rv.content_hash, rv.content, a.handle, rv.created_at, mr.id, "
        "  (SELECT v.passed FROM verification_runs v WHERE v.claim_revision_id = rv.id ORDER BY v.id DESC LIMIT 1) "
        "FROM claim_revisions rv JOIN agents a ON a.id = rv.agent_id "
        "LEFT JOIN merge_requests mr ON mr.merged_revision_id = rv.id "
        "WHERE rv.claim_id = %s ORDER BY rv.version", (claim_id,)),
        ("id", "version", "parent_id", "content_hash", "content", "author", "created_at", "merge_request_id",
         "verified"))


def provenance(conn: psycopg.Connection, p: Principal | None, claim_id: int) -> dict | None:
    """The claim's lineage as a graph: revisions and who made and reviewed them, the passages it rests on,
    the documents and sources those come from, registered trials behind the sources, and related claims."""
    if _visible_claim(conn, p, claim_id) is None:
        return None
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def node(nid: str, kind: str, **attrs) -> str:
        nodes.setdefault(nid, {"id": nid, "kind": kind, **attrs})
        return nid

    def edge(src: str, rel: str, dst: str) -> None:
        edges.append({"from": src, "rel": rel, "to": dst})

    c = node(f"claim:{claim_id}", "claim")
    for rv in revisions(conn, p, claim_id):
        r = node(f"revision:{rv['id']}", "revision", version=rv["version"], content_hash=rv["content_hash"])
        edge(r, "revises", c)
        edge(node(f"agent:{rv['author']}", "agent"), "authored", r)
        if rv["parent_id"]:
            edge(r, "supersedes", f"revision:{rv['parent_id']}")
        if rv["merge_request_id"]:
            mr = node(f"mr:{rv['merge_request_id']}", "merge_request")
            edge(mr, "produced", r)
            for handle, verdict in conn.execute(
                    "SELECT a.handle, rw.verdict FROM reviews rw JOIN agents a ON a.id = rw.reviewer_id "
                    "WHERE rw.merge_request_id = %s", (rv["merge_request_id"],)):
                edge(node(f"agent:{handle}", "agent"), f"review:{verdict}", mr)
    for ev in _evidence(conn, claim_id):
        e = node(f"evidence:{ev['id']}", "evidence", excerpt=ev["excerpt"], is_primary=ev["is_primary"])
        edge(c, ev["relation"], e)
        d = node(f"document:{ev['source_id']}@{ev['doc_sha256'][:12]}", "document", sha256=ev["doc_sha256"])
        edge(e, "span_of", d)
        s = node(f"source:{ev['source_id']}", "source", title=ev["source_title"])
        edge(d, "part_of", s)
        for (nct,) in conn.execute("SELECT DISTINCT nct_id FROM trial_links WHERE source_id = %s", (ev["source_id"],)):
            edge(s, "reports", node(f"trial:{nct}", "trial"))
    for rel in _relations(conn, p, claim_id):
        edge(c, rel["verdict"], node(f"claim:{rel['claim_id']}", "claim"))
    return {"root": c, "nodes": list(nodes.values()), "edges": edges}


def get_evidence(conn: psycopg.Connection, p: Principal | None, evidence_id: int) -> dict | None:
    row = conn.execute(
        "SELECT e.id, e.kind, e.source_id, s.title, e.document_id, e.doc_sha256, e.span_start, e.span_end, e.excerpt, "
        "e.is_primary, e.license, e.retrieved_at FROM evidence e JOIN sources s ON s.id = e.source_id WHERE e.id = %s",
        (evidence_id,)).fetchone()
    if row is None:
        return None
    where, params = visible(p)
    claims = _rows(conn.execute(
        "SELECT c.id, r.slug, l.relation, c.state FROM evidence_links l JOIN claims c ON c.id = l.claim_id "
        f"JOIN repositories r ON r.id = c.repository_id WHERE l.evidence_id = %(ev)s AND {where} ORDER BY c.id",
        params | {"ev": evidence_id}), ("claim_id", "repository", "relation", "state"))
    if not claims:
        return None          # evidence is only shown through a claim the caller can read
    return dict(zip(("id", "kind", "source_id", "source_title", "document_id", "doc_sha256", "span_start", "span_end",
                     "excerpt", "is_primary", "license", "retrieved_at"), row)) | {"claims": claims}


def get_verification_run(conn: psycopg.Connection, p: Principal | None, run_id: int) -> dict | None:
    where, params = visible(p)
    row = conn.execute(
        "SELECT v.id, v.claim_revision_id, v.merge_request_id, v.policy_version, v.checks, v.passed, v.created_at "
        "FROM verification_runs v "
        "LEFT JOIN claim_revisions rv ON rv.id = v.claim_revision_id LEFT JOIN claims c ON c.id = rv.claim_id "
        "LEFT JOIN merge_requests mr ON mr.id = v.merge_request_id "
        "JOIN repositories r ON r.id = coalesce(c.repository_id, mr.repository_id) "
        f"WHERE v.id = %(run)s AND {where}", params | {"run": run_id}).fetchone()
    return dict(zip(("id", "claim_revision_id", "merge_request_id", "policy_version", "checks", "passed",
                     "created_at"), row)) if row else None


def search(conn: psycopg.Connection, p: Principal | None, q: str, *, repository: str | None = None,
           state: str | None = None, type_: str | None = None, limit: int = 20, offset: int = 0) -> dict:
    """Claims matching `q` (web-search syntax: words, "phrases", -exclusions), best first."""
    where, params = visible(p)
    params |= {"q": q, "repo": repository, "state": state, "type": type_, "limit": limit, "offset": offset}
    rows = _rows(conn.execute(
        "SELECT c.id, r.slug, c.type, c.state, c.text, ts_rank(c.search, query) AS rank, "
        "  ts_headline('english', c.text, query, 'StartSel=[, StopSel=], MaxWords=40, MinWords=10') "
        "FROM claims c JOIN repositories r ON r.id = c.repository_id, websearch_to_tsquery('english', %(q)s) query "
        f"WHERE c.search @@ query AND {where} "
        "AND (%(repo)s::text IS NULL OR r.slug = %(repo)s) AND (%(state)s::text IS NULL OR c.state = %(state)s) "
        "AND (%(type)s::text IS NULL OR c.type = %(type)s) "
        "ORDER BY rank DESC, c.id LIMIT %(limit)s OFFSET %(offset)s", params),
        ("id", "repository", "type", "state", "proposition", "rank", "highlight"))
    for r in rows:
        r["rank"] = round(float(r["rank"]), 6)
    return {"items": rows, "next_offset": offset + limit if len(rows) == limit else None}


def get_source(conn: psycopg.Connection, source_id: str) -> dict | None:
    """A corpus source's metadata and its stored documents (hash and length, not text: text carries
    per-paper licenses). Sources are shared reference material, readable by anyone."""
    row = conn.execute("SELECT id, pmid, pmcid, doi, title, pub_year, journal, pub_types, has_full_text, license "
                       "FROM sources WHERE id = %s", (source_id,)).fetchone()
    if row is None:
        return None
    src = dict(zip(("id", "pmid", "pmcid", "doi", "title", "pub_year", "journal", "pub_types", "has_full_text",
                    "license"), row))
    src["documents"] = _rows(conn.execute(
        "SELECT part, sha256, length(text) FROM documents WHERE source_id = %s ORDER BY part", (source_id,)),
        ("part", "sha256", "length"))
    src["trials"] = [t for (t,) in conn.execute(
        "SELECT DISTINCT nct_id FROM trial_links WHERE source_id = %s ORDER BY 1", (source_id,))]
    return src


def locate(conn: psycopg.Connection, source_id: str, quote: str) -> list[dict]:
    """Where a quote appears verbatim (up to typography) in a source's documents: the exact span to cite."""
    from ..reader import spans
    found = []
    for part, sha, text in conn.execute("SELECT part, sha256, text FROM documents WHERE source_id = %s "
                                        "ORDER BY part", (source_id,)):
        if (hit := spans.locate(quote, text)) is not None:
            found.append({"source_id": source_id, "part": part, "doc_sha256": sha, "start": hit[0], "end": hit[1],
                          "excerpt": text[hit[0]:hit[1]]})
    return found
