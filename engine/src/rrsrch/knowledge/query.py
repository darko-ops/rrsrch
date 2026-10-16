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
             "claims", "open_merge_requests", "created_via", "created_by")
_REPO_SELECT = ("SELECT r.id, r.slug, r.organization_id, r.topic, r.description, r.visibility, r.policy_version, "
                "r.created_at, (SELECT count(*) FROM claims c WHERE c.repository_id = r.id), "
                "(SELECT count(*) FROM merge_requests mr WHERE mr.repository_id = r.id AND mr.state = 'open'), "
                "r.created_via, (SELECT handle FROM agents a WHERE a.id = r.created_by) "
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
                 "is_primary", "license", "retrieved_at", "kind", "git", "source_provenance", "source_url", "source_origin")
_GIT = ("CASE WHEN e.kind = 'git_ref' THEN json_build_object('repo_url', e.repo_url, 'commit', e.commit_sha, "
        "'tag', e.git_tag, 'path', e.path, 'start_line', e.start_line, 'end_line', e.end_line) END")


def _evidence(conn, claim_id: int) -> list[dict]:
    return _rows(conn.execute(
        "SELECT e.id, l.relation, e.source_id, s.title, e.doc_sha256, e.span_start, e.span_end, e.excerpt, "
        f"e.is_primary, e.license, e.retrieved_at, e.kind, {_GIT}, s.provenance, s.url, s.origin FROM evidence_links l "
        "JOIN evidence e ON e.id = l.evidence_id LEFT JOIN sources s ON s.id = e.source_id "
        "WHERE l.claim_id = %s ORDER BY e.id, l.relation", (claim_id,)),
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
    challenges = _rows(conn.execute(
        "SELECT ch.id, ch.details->>'objection', ch.blocking, ch.state, a.handle FROM reviews ch "
        "JOIN agents a ON a.id = ch.reviewer_id WHERE ch.claim_id = %s AND ch.kind = 'objection' "
        "AND ch.state IN ('open', 'upheld') ORDER BY ch.id", (claim_id,)),
        ("id", "kind", "blocking", "state", "author"))
    derived = [d for (d,) in conn.execute("SELECT derived_from_id FROM claim_derivations WHERE claim_id = %s "
                                          "ORDER BY 1", (claim_id,))]
    from ..trust import disclosure      # trust builds on knowledge; imported here to keep that direction
    return claim | {"head": head, "evidence": _evidence(conn, claim_id), "verification": run,
                    "contradicted_by": [x for x in rel if x["verdict"] == "contradicts"],
                    "agrees_with": [x for x in rel if x["verdict"] == "agrees"],
                    "challenges": challenges, "derived_from": derived,
                    "embargo": disclosure.active_embargo(conn, claim_id),
                    "disclosure": disclosure.record_of(conn, claim_id)}


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
        if ev["kind"] == "git_ref":           # a commit, not a passage of a document: no source or trial behind it
            g = ev["git"]
            edge(e, "at_commit", node(f"commit:{g['repo_url'].removeprefix('https://')}@{g['commit'][:12]}", "commit",
                                      repo_url=g["repo_url"], commit=g["commit"], tag=g.get("tag")))
            continue
        d = node(f"document:{ev['source_id']}@{ev['doc_sha256'][:12]}", "document", sha256=ev["doc_sha256"])
        edge(e, "span_of", d)
        s = node(f"source:{ev['source_id']}", "source", title=ev["source_title"])
        edge(d, "part_of", s)
        for (nct,) in conn.execute("SELECT DISTINCT nct_id FROM trial_links WHERE source_id = %s", (ev["source_id"],)):
            edge(s, "reports", node(f"trial:{nct}", "trial"))
    for rel in _relations(conn, p, claim_id):
        edge(c, rel["verdict"], node(f"claim:{rel['claim_id']}", "claim"))
    for (parent,) in conn.execute("SELECT derived_from_id FROM claim_derivations WHERE claim_id = %s", (claim_id,)):
        edge(c, "derived_from", node(f"claim:{parent}", "claim"))
    for (child,) in conn.execute("SELECT claim_id FROM claim_derivations WHERE derived_from_id = %s", (claim_id,)):
        edge(node(f"claim:{child}", "claim"), "derived_from", c)
    for ch in conn.execute("SELECT ch.id, ch.state, a.handle FROM reviews ch JOIN agents a ON a.id = ch.reviewer_id "
                           "WHERE ch.claim_id = %s AND ch.kind = 'objection'", (claim_id,)):
        x = node(f"challenge:{ch[0]}", "challenge", state=ch[1])
        edge(x, "challenges", c)
        edge(node(f"agent:{ch[2]}", "agent"), "raised", x)
    return {"root": c, "nodes": list(nodes.values()), "edges": edges}


def get_evidence(conn: psycopg.Connection, p: Principal | None, evidence_id: int) -> dict | None:
    row = conn.execute(
        "SELECT e.id, e.kind, e.source_id, s.title, e.document_id, e.doc_sha256, e.span_start, e.span_end, e.excerpt, "
        f"e.is_primary, e.license, e.retrieved_at, {_GIT} FROM evidence e LEFT JOIN sources s ON s.id = e.source_id "
        "WHERE e.id = %s",
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
                     "excerpt", "is_primary", "license", "retrieved_at", "git"), row)) | {"claims": claims}


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
    row = conn.execute("SELECT s.id, s.pmid, s.pmcid, s.doi, s.title, s.pub_year, s.journal, s.pub_types, s.has_full_text, "
                       "s.license, s.kind, s.provenance, s.url, s.content_type, a.handle, s.fetched_at, s.origin "
                       "FROM sources s LEFT JOIN agents a ON a.id = s.added_by WHERE s.id = %s", (source_id,)).fetchone()
    if row is None:
        return None
    src = dict(zip(("id", "pmid", "pmcid", "doi", "title", "pub_year", "journal", "pub_types", "has_full_text",
                    "license", "kind", "provenance", "url", "content_type", "added_by", "fetched_at", "origin"), row))
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


def atlas(conn: psycopg.Connection, repository_id: int, limit: int = 300) -> dict:
    """One repository's knowledge graph, newest claims first up to `limit`. Edges only between nodes shown.

    Nodes: claim:N, source:ID, trial:NCT, agent:handle. Edges: claim -supports/contradicts/context-> source
    (one per relation, with how many spans), source -reports-> trial, agent -authored-> claim, and claim to
    claim: agrees / contradicts (skeptic findings) and derived_from.
    """
    total = conn.execute("SELECT count(*) FROM claims WHERE repository_id = %s", (repository_id,)).fetchone()[0]
    claims = _rows(conn.execute(
        "SELECT c.id, c.text, c.state, c.type, a.handle, "
        "  (SELECT count(*) FROM reviews ch WHERE ch.claim_id = c.id AND ch.kind = 'objection' AND ch.state = 'open') "
        "FROM claims c JOIN agents a ON a.id = c.agent_id WHERE c.repository_id = %s ORDER BY c.id DESC LIMIT %s",
        (repository_id, limit)), ("id", "text", "state", "type", "author", "open_challenges"))
    ids = [c["id"] for c in claims]
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for c in claims:
        nodes[f"claim:{c['id']}"] = {"id": f"claim:{c['id']}", "kind": "claim", "claim_id": c["id"],
                                     "label": c["text"], "state": c["state"], "type": c["type"],
                                     "open_challenges": c["open_challenges"]}
        nodes.setdefault(f"agent:{c['author']}", {"id": f"agent:{c['author']}", "kind": "agent",
                                                  "label": c["author"]})
        edges.append({"from": f"agent:{c['author']}", "rel": "authored", "to": f"claim:{c['id']}"})
    for claim_id, relation, source_id, title, year, primary, spans in conn.execute(
            "SELECT l.claim_id, l.relation, e.source_id, s.title, s.pub_year, bool_and(e.is_primary), count(*) "
            "FROM evidence_links l JOIN evidence e ON e.id = l.evidence_id JOIN sources s ON s.id = e.source_id "
            "WHERE l.claim_id = ANY(%s) GROUP BY 1, 2, 3, 4, 5", (ids,)):
        nodes.setdefault(f"source:{source_id}", {"id": f"source:{source_id}", "kind": "source", "label": title,
                                                 "source_id": source_id, "year": year, "is_primary": primary})
        edges.append({"from": f"claim:{claim_id}", "rel": relation, "to": f"source:{source_id}", "spans": spans})
    sources = [n["source_id"] for n in nodes.values() if n["kind"] == "source"]
    for source_id, nct in conn.execute("SELECT DISTINCT source_id, nct_id FROM trial_links WHERE source_id = ANY(%s)",
                                       (sources,)):
        nodes.setdefault(f"trial:{nct}", {"id": f"trial:{nct}", "kind": "trial", "label": nct})
        edges.append({"from": f"source:{source_id}", "rel": "reports", "to": f"trial:{nct}"})
    for a, b, verdict in conn.execute(
            "SELECT claim_a_id, claim_b_id, verdict FROM claim_agreements WHERE claim_a_id = ANY(%s) AND claim_b_id = ANY(%s)",
            (ids, ids)):
        edges.append({"from": f"claim:{a}", "rel": "agrees" if verdict == "agrees" else "contradicts",
                      "to": f"claim:{b}"})
    for child, parent in conn.execute(
            "SELECT claim_id, derived_from_id FROM claim_derivations WHERE claim_id = ANY(%s) AND derived_from_id = ANY(%s)",
            (ids, ids)):
        edges.append({"from": f"claim:{child}", "rel": "derived_from", "to": f"claim:{parent}"})
    counts: dict[str, int] = {}
    for n in nodes.values():
        counts[n["kind"]] = counts.get(n["kind"], 0) + 1
    return {"nodes": list(nodes.values()), "edges": edges, "counts": counts, "claims_total": total,
            "truncated": total > len(claims)}


CONTEXT_CHARS = 240


def review_queue(conn: psycopg.Connection, repository_id: int, states: tuple[str, ...], after: int = 0,
                 limit: int = 20) -> dict:
    """Claims waiting for review, oldest first, each with the passage it rests on shown in context."""
    rows = _rows(conn.execute(
        "SELECT c.id, c.text, c.state, c.type, a.handle, s.id, s.title, s.pub_year, d.text, c.span_start, c.span_end, "
        "  (SELECT count(*) FROM reviews ch WHERE ch.claim_id = c.id AND ch.kind = 'objection' AND ch.state = 'open') "
        "FROM claims c JOIN agents a ON a.id = c.agent_id JOIN documents d ON d.id = c.document_id "
        "JOIN sources s ON s.id = d.source_id "
        "WHERE c.repository_id = %s AND c.state = ANY(%s) AND c.id > %s ORDER BY c.id LIMIT %s",
        (repository_id, list(states), after, limit)),
        ("id", "proposition", "state", "type", "contributor", "source_id", "source_title", "year", "doc", "start",
         "end", "open_challenges"))
    ids = [r["id"] for r in rows]
    reviews: dict[int, list] = {}
    for cid, handle, verdict, findings in conn.execute(
            "SELECT v.claim_id, a.handle, v.verdict, v.findings FROM reviews v JOIN agents a ON a.id = v.reviewer_id "
            "JOIN claim_revisions rv ON rv.id = v.revision_id WHERE v.claim_id = ANY(%s) AND v.kind = 'decision' "
            "AND rv.version = (SELECT max(version) FROM claim_revisions WHERE claim_id = v.claim_id) ORDER BY v.id",
            (ids,)):
        reviews.setdefault(cid, []).append({"reviewer": handle, "verdict": verdict, "findings": findings})
    for r in rows:
        doc, a, b = r.pop("doc"), r.pop("start"), r.pop("end")
        r["passage"] = {"before": doc[max(0, a - CONTEXT_CHARS):a], "excerpt": doc[a:b], "after": doc[b:b + CONTEXT_CHARS]}
        r["reviews"] = reviews.get(r["id"], [])
    total = conn.execute("SELECT count(*) FROM claims WHERE repository_id = %s AND state = ANY(%s)",
                         (repository_id, list(states))).fetchone()[0]
    return {"items": rows, "next": rows[-1]["id"] if len(rows) == limit else None, "waiting": total}


def review_trials(conn: psycopg.Connection, repository_id: int, states: tuple[str, ...], offset: int = 0,
                  limit: int = 20) -> dict:
    """Sources (trials) with claims waiting for review, most waiting first, so a reviewer can read one abstract
    and check all of its claims together."""
    rows = _rows(conn.execute(
        "SELECT s.id, s.title, s.pub_year, count(*) FROM claims c JOIN documents d ON d.id = c.document_id "
        "JOIN sources s ON s.id = d.source_id WHERE c.repository_id = %s AND c.state = ANY(%s) "
        "GROUP BY s.id, s.title, s.pub_year ORDER BY count(*) DESC, s.id LIMIT %s OFFSET %s",
        (repository_id, list(states), limit + 1, offset)), ("source_id", "title", "year", "waiting"))
    total = conn.execute(
        "SELECT count(DISTINCT d.source_id) FROM claims c JOIN documents d ON d.id = c.document_id "
        "WHERE c.repository_id = %s AND c.state = ANY(%s)", (repository_id, list(states))).fetchone()[0]
    return {"items": rows[:limit], "next_offset": offset + limit if len(rows) > limit else None, "trials": total}


def review_trial(conn: psycopg.Connection, repository_id: int, states: tuple[str, ...], source_id: str) -> dict | None:
    """One source's documents, each once, with every claim on them that is waiting for review and its span."""
    src = conn.execute("SELECT id, title, pub_year FROM sources WHERE id = %s", (source_id,)).fetchone()
    if src is None:
        return None
    claims = _rows(conn.execute(
        "SELECT c.id, c.text, c.state, c.type, a.handle, d.part, c.span_start, c.span_end, "
        "  (SELECT count(*) FROM reviews ch WHERE ch.claim_id = c.id AND ch.kind = 'objection' AND ch.state = 'open') "
        "FROM claims c JOIN agents a ON a.id = c.agent_id JOIN documents d ON d.id = c.document_id "
        "WHERE c.repository_id = %s AND c.state = ANY(%s) AND d.source_id = %s ORDER BY d.part <> 'abstract', d.part, c.span_start, c.id",
        (repository_id, list(states), source_id)),
        ("id", "proposition", "state", "type", "contributor", "part", "start", "end", "open_challenges"))
    reviews: dict[int, list] = {}
    for cid, handle, verdict, findings in conn.execute(
            "SELECT v.claim_id, a.handle, v.verdict, v.findings FROM reviews v JOIN agents a ON a.id = v.reviewer_id "
            "JOIN claim_revisions rv ON rv.id = v.revision_id WHERE v.claim_id = ANY(%s) AND v.kind = 'decision' "
            "AND rv.version = (SELECT max(version) FROM claim_revisions WHERE claim_id = v.claim_id) ORDER BY v.id",
            ([c["id"] for c in claims],)):
        reviews.setdefault(cid, []).append({"reviewer": handle, "verdict": verdict, "findings": findings})
    for c in claims:
        c["reviews"] = reviews.get(c["id"], [])
    parts = sorted({c["part"] for c in claims})
    documents = [{"part": part, "text": text} for part, text in conn.execute(
        "SELECT part, text FROM documents WHERE source_id = %s AND part = ANY(%s) ORDER BY part <> 'abstract', part",
        (source_id, parts))]
    return {"source_id": src[0], "title": src[1], "year": src[2], "documents": documents, "claims": claims}
