"""rrsrch command line.

  rrsrch corpus discover PMID [PMID ...]   draft the corpus from meta-analyses
  rrsrch corpus fetch [--refresh]          snapshot every source and trial locally
  rrsrch corpus verify                     prove local snapshots match the lockfile
  rrsrch corpus status                     what the corpus holds, and what needs review
  rrsrch ledger load                       migrate Postgres, load the corpus, record claim revisions
  rrsrch read plan                         what the reader would send the model (no model needed)
  rrsrch read run [--source ID] [--limit N] extract claims with the model in RRSRCH_LLM_URL
  rrsrch read stats                        claims, rejections by rule, coverage
  rrsrch gate "SENTENCE" CLAIM_ID [...]    check a sentence against ledger claims
  rrsrch gate-eval                         score the gate on its evaluation set
  rrsrch write "QUESTION"                  answer from the ledger; every sentence gated
  rrsrch trials reconcile [-v]             registrations against their papers: matched, drift, ...
  rrsrch skeptic run                       find ledger claims that agree or contradict
  rrsrch skeptic show                      list stored contradictions
  rrsrch serve [--host] [--port]           HTTP answer API for the site (POST /v1/answer)
  rrsrch bench check                       validate the benchmark against the answer key
  rrsrch bench run [--only ID]             write and score a report for each benchmark question
  rrsrch org add ID NAME                   create an organization
  rrsrch agent add HANDLE --org ORG [--kind K] [--admin]   register an agent
  rrsrch agent key HANDLE --scope S [...] [--days N]       issue an API key (shown once; lives while used)
  rrsrch agent revoke HANDLE               revoke an agent and all its keys
  rrsrch repo member SLUG HANDLE ROLE      grant a repository role (or `none` to remove)
  rrsrch audit verify                      check every audit event's hash and link
  rrsrch indexnow [--once] [--seed]        announce changed public claims and questions to IndexNow
  rrsrch mcp [--api URL] [--read-only]     MCP server (stdio) over the API, as RRSRCH_API_KEY
  rrsrch eval run --db URL [...]           run conditions A/B/C on the benchmark (needs RRSRCH_LLM_URL)
  rrsrch eval report RESULT.json           score a run and print the comparison table
"""
from __future__ import annotations

import argparse
import json
import re
import sys

from .corpus import discover, manifest, snapshot, text
from .sources.ctgov import ClinicalTrials, find_nct_ids
from .sources.europepmc import EuropePMC

# Fallback query when a Table 1 citation isn't in the reference list Europe PMC
# resolved. Any hit is marked for review: a search is a likely match, not a proof.
FALLBACK_QUERY = ('AUTH:"{surname}" AND PUB_YEAR:{year} AND (knee OR osteoarthritis) '
                  'AND (mesenchymal OR stromal OR "stem cell" OR "stromal vascular")')
# Second fallback: the cited title. Only a record whose whole title matches it,
# ignoring case and punctuation, counts; preprints yield to the journal version.
TITLE_QUERY = 'TITLE:"{phrase}"'


def _norm_title(t: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", t.lower()).split())


def _search_title(epmc: EuropePMC, title: str) -> dict | None:
    want = _norm_title(title)
    phrase = " ".join(want.split()[:12])
    hits = [h for h in epmc.search(TITLE_QUERY.format(phrase=phrase), page_size=10)
            if _norm_title(h.get("title") or "") == want]
    if len(hits) > 1:
        hits = [h for h in hits if h.get("source") != "PPR"]
    return {"id": f'{hits[0]["source"]}:{hits[0]["id"]}', "title": hits[0]["title"]} if len(hits) == 1 else None


def _search_one(epmc: EuropePMC, query: str) -> dict | None:
    hits = [h for h in epmc.search(query, page_size=5)
            if not discover.REVIEW_RE.search(h.get("title") or "")]
    return {"id": f'{hits[0]["source"]}:{hits[0]["id"]}', "title": hits[0]["title"]} if len(hits) == 1 else None


def cmd_discover(args) -> int:
    epmc = EuropePMC()
    data = manifest.load()
    if args.topic:
        data["topic"] = args.topic
    for pmid in args.pmids:
        rec = epmc.record(f"MED:{pmid}")
        if not rec or not rec.get("pmcid"):
            print(f"{pmid}: no open full text, so no Table 1 to read; skipped", file=sys.stderr)
            continue
        xml = epmc.full_text_xml(rec["pmcid"])
        if xml is None:
            print(f"{pmid}: Europe PMC has no full-text XML; skipped", file=sys.stderr)
            continue
        citations = discover.table1_citations(xml)
        resolutions = discover.resolve(citations, epmc.references(pmid))
        searched = {}
        for i, r in enumerate(resolutions):
            if r.status not in ("unresolved", "ambiguous"):
                continue
            hit = None
            if r.citation.year:
                hit = _search_one(epmc, FALLBACK_QUERY.format(surname=r.citation.surname,
                                                              year=r.citation.year))
            title = discover.cited_title(r.citation.cited_as)
            if hit is None and len(title.split()) >= 5:
                hit = _search_title(epmc, title)
            if hit:
                searched[i] = hit
        ma = {"pmid": pmid, "pmcid": rec["pmcid"], "title": rec["title"],
              "year": int(rec["pubYear"]), "included_studies_from": "table-1"}
        manifest.merge_meta_analysis(data, ma, resolutions, searched)
        counts = {}
        for i, r in enumerate(resolutions):
            k = "found-by-search (review)" if i in searched else r.status
            counts[k] = counts.get(k, 0) + 1
        print(f"{pmid}: {len(citations)} included studies cited in Table 1 -> {counts}")
    manifest.save(data)
    return cmd_status(args)


def cmd_fetch(args) -> int:
    epmc, ct = EuropePMC(), ClinicalTrials()
    data = manifest.load()
    lock = snapshot.Lock()
    changes = []
    ids = [s["id"] for s in data["studies"]] + [f'MED:{m["pmid"]}' for m in data["answer_key"]]
    study_ids = {s["id"] for s in data["studies"]}
    ncts: dict[str, str] = {}
    for sid in ids:
        d = snapshot.record_dir(sid)
        if (d / "record.json").exists() and not args.refresh:
            rec = json.loads((d / "record.json").read_text())
        else:
            rec = epmc.record(sid)
            if rec is None:
                print(f"{sid}: not found in Europe PMC", file=sys.stderr)
                continue
            changes.append(lock.write(d / "record.json", snapshot.stable_record_bytes(rec),
                                      f"europepmc:{sid}"))
        ft = d / "fulltext.xml"
        if rec.get("pmcid") and rec.get("isOpenAccess") == "Y" and (args.refresh or not ft.exists()):
            xml = epmc.full_text_xml(rec["pmcid"])
            if xml is not None:
                changes.append(lock.write(ft, xml, f"europepmc:{rec['pmcid']}/fullTextXML"))
        if sid in study_ids:
            body = text.abstract_text(rec.get("abstractText"))
            if ft.exists():
                body += "\n" + text.fulltext_body(ft.read_bytes())
            for n in find_nct_ids(body):
                ncts.setdefault(n, sid)
    for nct in sorted(ncts):
        p = snapshot.trial_path(nct)
        if p.exists() and not args.refresh:
            continue
        raw = ct.study(nct)
        if raw is None:
            print(f"{nct} (cited by {ncts[nct]}): not on ClinicalTrials.gov", file=sys.stderr)
            continue
        changes.append(lock.write(p, raw, f"ctgov:{nct}"))
    lock.save()
    summary = {}
    for c in changes:
        summary[c.kind] = summary.get(c.kind, 0) + 1
    print(f"snapshots: {summary or 'nothing new'}; trials referenced: {len(ncts)}")
    for c in changes:
        if c.kind == "changed":
            print(f"  changed at source: {c.path}")
    return 0


def cmd_verify(args) -> int:
    problems = snapshot.Lock().verify()
    for path, why in problems:
        print(f"{why}: {path}")
    print("all snapshots match the lockfile" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def cmd_status(args) -> int:
    data = manifest.load()
    studies = data["studies"]
    print(f"answer key: {len(data['answer_key'])} meta-analyses; corpus: {len(studies)} studies")
    review = [s for s in studies if s.get("review")]
    for s in review:
        print(f"  review: {s['id']}  cited as {list(s['cited_as'].values())[0]!r} -> {s['title'][:70]}")
    for u in data["unresolved"]:
        print(f"  unresolved: {u['cited_as']!r} in {u['meta_analysis']} ({u['status']})")
    return 0


def cmd_ledger_load(args) -> int:
    from .knowledge import store
    from .ledger import db
    with db.connect() as conn:
        applied = db.migrate(conn)
        if applied:
            print(f"migrations applied: {', '.join(applied)}")
        rep = db.load_corpus(conn, manifest.load())
        recorded = store.sync(conn, snapshot.Lock().entries)
    if recorded:
        print(f"recorded revisions and evidence for {recorded} claim(s)")
    print(f"loaded {rep.sources} sources, documents {rep.documents}, "
          f"{rep.trials} trials, {rep.links} trial links")
    for m in rep.missing_snapshots:
        print(f"  no snapshot yet (run `rrsrch corpus fetch`): {m}")
    for n in rep.unregistered_ncts:
        print(f"  cited NCT with no ClinicalTrials.gov record: {n}")
    return 0


def cmd_read_plan(args) -> int:
    from .ledger import db
    from .reader.extract import chunks
    with db.connect() as conn:
        rows = conn.execute("SELECT source_id, part, text FROM documents WHERE part IN ('abstract', 'fulltext') "
                            "ORDER BY source_id, part").fetchall()
    total = {"abstract": [0, 0, 0], "fulltext": [0, 0, 0]}   # docs, chunks, chars
    for sid, part, text in rows:
        cs = chunks(part, text)
        t = total[part]
        t[0] += 1; t[1] += len(cs); t[2] += sum(len(c.text) for c in cs)
        if args.verbose:
            print(f"{sid} {part}: {len(cs)} chunk(s), {sum(len(c.text) for c in cs)} of {len(text)} chars")
    for part, (d, c, ch) in total.items():
        print(f"{part}: {d} documents -> {c} chunks, {ch:,} characters to read")
    return 0


def cmd_read_run(args) -> int:
    from .ledger import db
    from .reader.extract import read_corpus
    from .reader.llm import LLM
    llm = LLM.from_env()
    with db.connect() as conn:
        # autocommit: each chunk's `with conn.transaction()` then commits on its own. Without it the whole run
        # is one open transaction, so a crash hours in loses every claim, and the run blocks migrations.
        conn.autocommit = True
        db.migrate(conn)
        rep = read_corpus(conn, llm, args.source or None, args.limit)
    print(f"read {rep.chunks_read} chunks ({rep.chunks_skipped} already read): "
          f"{rep.claims} claims in, rejected {rep.rejected}")
    return 0


def cmd_read_agent(args) -> int:
    """The reader as a standing agent: finds its own work and proposes claims through the API (reader/agent.py)."""
    from .reader.agent import from_env
    agent = from_env(dry_run=args.dry_run)
    if args.once or args.dry_run:
        agent.cycle()
    else:
        agent.run_forever()
    return 0


def cmd_read_stats(args) -> int:
    from .ledger import db
    with db.connect() as conn:
        for extractor, n_items, n_claims in conn.execute(
                "SELECT extractor, sum(n_items), sum(n_claims) FROM read_chunks GROUP BY 1 ORDER BY 1"):
            print(f"{extractor}: model proposed {n_items}, ledger accepted {n_claims} "
                  f"({(n_claims / n_items * 100) if n_items else 0:.0f}%)")
        for reason, n in conn.execute("SELECT reason, count(*) FROM claim_rejections GROUP BY 1 ORDER BY 2 DESC"):
            print(f"  rejected {n:>4}  {reason}")
        n_src, with_claims = conn.execute(
            "SELECT count(*), count(*) FILTER (WHERE EXISTS (SELECT 1 FROM claims c JOIN documents d "
            "ON d.id = c.document_id WHERE d.source_id = s.id)) FROM sources s").fetchone()
        print(f"sources with at least one claim: {with_claims} of {n_src}")
    return 0


def cmd_gate(args) -> int:
    from .check import gate
    from .ledger import db
    with db.connect() as conn:
        cited = []
        for cid in args.claims:
            row = conn.execute(
                "SELECT c.text, s.title, (SELECT text FROM documents a WHERE a.source_id = s.id "
                "AND a.part = 'abstract') FROM claims c JOIN documents d ON d.id = c.document_id "
                "JOIN sources s ON s.id = d.source_id WHERE c.id = %s", (int(cid),)).fetchone()
            if row is None:
                print(f"no claim {cid}", file=sys.stderr)
                return 2
            cited.append(gate.CitedClaim(cid, row[0], gate.source_context(row[1], row[2] or "")))
    v = gate.check(args.sentence, cited)
    for rule, ok, detail in v.log:
        print(f"  {'ok  ' if ok else 'FAIL'} {rule:<10} {detail}")
    print("PASS" if v.passed else f"REJECTED by {v.rule}")
    return 0 if v.passed else 1


def cmd_gate_eval(args) -> int:
    from .check import evaluate
    score = evaluate.run()
    for r in score.results:
        if not r.correct or args.verbose:
            tag = "gap " if r.case.get("known_gap") else ("ok  " if r.correct else "MISS")
            print(f"{tag} {r.case['kind']:<9} want {r.case['expect']:<6} got {r.verdict.rule:<10} "
                  f"{r.case['sentence'][:70]}")
    s = score.summary()
    print(f"unfaithful sentences caught: {s['caught']}; faithful sentences refused: {s['false_rejects']}; "
          f"known gaps caught: {s['known_gaps_caught']}")
    misses = [r for r in score.results if not r.correct and not r.case.get("known_gap")]
    return 1 if misses else 0


def cmd_bench_check(args) -> int:
    from .bench import questions
    bench = questions.load()
    rep = questions.check(bench)
    for p in rep.problems:
        print(f"{p.question}: {p.detail}")
    for q in bench["questions"]:
        ids = rep.studies.get(q["id"], [])
        full = sum(1 for i in ids if (snapshot.record_dir(i) / "fulltext.xml").exists())
        if args.verbose:
            print(f"{q['id']} [{q['kind']}] {q['question']}\n    expected: {q['expected']['verdict']}; "
                  f"{len(q['support'])} answer-key findings; {len(ids)} corpus studies ({full} full text)")
    print(f"{len(bench['questions'])} questions; {rep.quotes_checked} quotes found verbatim"
          + (f", {rep.quotes_unchecked} unchecked (run rrsrch corpus fetch)" if rep.quotes_unchecked else "")
          + f"; {len(rep.problems)} problem(s)")
    return 1 if rep.problems else 0


def cmd_write(args) -> int:
    from .ledger import db
    from .reader.llm import LLM
    from .writer import write as writer
    with db.connect() as conn:
        db.migrate(conn)
        rep = writer.write(conn, LLM.from_env(), args.question)
    if rep.bad_reply:
        print(f"no report: {rep.bad_reply}", file=sys.stderr)
    print(f"verdict: {rep.verdict}\n\n{rep.render()}\n")
    for s in rep.sentences:
        if not s.verdict.passed:
            print(f"  refused ({s.verdict.rule}): {s.text}\n      {s.verdict.detail}")
    f = rep.faithfulness
    print(f"report {rep.id}: {len(rep.kept)}/{len(rep.sentences)} sentences passed the gate"
          + (f" ({f:.0%})" if f is not None else "") + f"; {len(rep.shown)} claims shown")
    return 0 if rep.kept else 1


def cmd_bench_run(args) -> int:
    from .bench import questions, run
    from .ledger import db
    from .reader.llm import LLM
    with db.connect() as conn:
        db.migrate(conn)
        score = run.run(conn, LLM.from_env(), questions.load(), only=args.only)
    s = score.summary()
    pct = lambda x: "n/a" if x is None else f"{x:.0%}"  # noqa: E731
    print(f"\n{s['questions']} questions")
    print(f"faithfulness: {pct(s['faithfulness'])} of {s['sentences_proposed']} proposed sentences passed the gate")
    print(f"coverage:     {pct(s['coverage'])} of expected points made (model-judged)")
    print(f"verdicts:     {s['verdicts_matched']}/{s['questions']} matched the answer key")
    print(f"writer refusals by rule: {s['writer_rejections'] or 'none'}")
    r = s["reader"]
    print(f"reader: {r['claims_accepted']} claims accepted, rejection rate {pct(r['rejection_rate'])}, "
          f"refused by rule {r['claims_refused'] or 'none'}")
    return 0


def cmd_trials_reconcile(args) -> int:
    from collections import Counter
    from .ledger import db
    from .trials import reconcile
    with db.connect() as conn:
        db.migrate(conn)
        results = reconcile.reconcile_all(conn)
        n_sources, n_linked = conn.execute(
            "SELECT count(*), count(*) FILTER (WHERE EXISTS (SELECT 1 FROM trial_links l "
            "WHERE l.source_id = s.id)) FROM sources s").fetchone()
    for r in results:
        flags = f"  [{', '.join(r.flags)}]" if r.flags else ""
        print(f"{r.nct_id}  {r.source_id or '-':<14} {r.state}{flags}")
        if args.verbose or r.state == "endpoint_drift":
            for why in r.reasons:
                print(f"      {why}")
    counts = Counter(r.state for r in results)
    print("\n" + ", ".join(f"{s}: {counts.get(s, 0)}" for s in reconcile.STATES)
          + f"  ({len(results)} trial-paper pairs)")
    print(f"{n_sources - n_linked} of {n_sources} studies name no ClinicalTrials.gov registration in their text; "
          f"they may be registered elsewhere or not at all.")
    print("Only ClinicalTrials.gov was searched; trials registered elsewhere are not reconciled.")
    return 0


def cmd_skeptic_run(args) -> int:
    from .ledger import db
    from .skeptic import run as skeptic
    with db.connect() as conn:
        db.migrate(conn)
        rep = skeptic.scan(conn)
    print(f"compared {rep.pairs_compared} claim pair(s) across {rep.claims} claim(s)")
    if rep.skipped_same_text:
        print(f"skipped {rep.skipped_same_text} near-duplicate pair(s) from the same source")
    stored = rep.stored or {}
    print(f"stored: {stored.get('contradicts', 0)} contradict, {stored.get('agrees', 0)} agree")
    return 0


def cmd_serve(args) -> int:
    from .serve import api
    api.run(host=args.host, port=args.port)
    return 0


def cmd_skeptic_show(args) -> int:
    from .ledger import db
    from .skeptic import run as skeptic
    with db.connect() as conn:
        db.migrate(conn)
        rows = skeptic.contradictions(conn)
        n_agree = conn.execute(
            "SELECT count(*) FROM claim_agreements WHERE verdict = 'agrees'").fetchone()[0]
    if not rows:
        print(f"no contradictions stored ({n_agree} agreeing pair(s) on file)")
        print("run `rrsrch skeptic run` after the reader has filled the ledger")
        return 0
    for r in rows:
        print(f"#{r['id']}  {r['source_a']} ↔ {r['source_b']}")
        print(f"  {r['detail']}")
        print(f"  A [{r['claim_a_id']}]: {r['claim_a'][:200]}")
        print(f"  B [{r['claim_b_id']}]: {r['claim_b'][:200]}")
        if args.verbose:
            print()
    print(f"\n{len(rows)} contradiction(s), {n_agree} agreeing pair(s)")
    return 0


def _identity(fn):
    """Run fn(conn, store, audit) in one transaction on a migrated ledger; ValueErrors become exit code 1."""
    from .identity import store
    from .ledger import db
    from .trust import audit
    try:
        with db.connect() as conn:
            db.migrate(conn)
            return fn(conn, store, audit) or 0
    except (ValueError, LookupError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def cmd_org_add(args) -> int:
    def go(conn, store, audit):
        store.create_organization(conn, args.id, args.name)
        audit.append(conn, "organization.create", f"org:{args.id}", detail={"name": args.name})
    return _identity(go)


def cmd_agent_add(args) -> int:
    def go(conn, store, audit):
        a = store.register_agent(conn, args.org, args.handle, args.kind, model=args.model,
                                 org_role="admin" if args.admin else "member")
        audit.append(conn, "agent.register", f"agent:{a['handle']}",
                     detail={"organization_id": args.org, "kind": args.kind, "org_role": a["org_role"]})
        print(f"registered {a['handle']} ({a['kind']}, {a['org_role']} of {a['organization_id']})")
    return _identity(go)


def cmd_agent_key(args) -> int:
    def go(conn, store, audit):
        agent = store.get_agent(conn, args.handle)
        if agent is None:
            raise LookupError(f"no agent {args.handle}")
        token, key_id, expires = store.issue_key(conn, agent["id"], set(args.scope), days=args.days,
                                                 label=args.label)
        audit.append(conn, "key.issue", f"agent:{args.handle}",
                     detail={"key_id": key_id, "scopes": sorted(args.scope), "days": args.days})
        life = f"expires {expires:%Y-%m-%d}" if args.days else f"valid while used (now until {expires:%Y-%m-%d})"
        print(f"key {key_id} for {args.handle}, scopes {sorted(args.scope)}, {life}")
        print("store it now; it is not shown again:")
        print(token)
    return _identity(go)


def cmd_agent_revoke(args) -> int:
    def go(conn, store, audit):
        agent = store.get_agent(conn, args.handle)
        if agent is None:
            raise LookupError(f"no agent {args.handle}")
        n = store.revoke_agent(conn, agent["id"])
        audit.append(conn, "agent.revoke", f"agent:{args.handle}", detail={"keys_revoked": n})
        print(f"revoked {args.handle} and {n} live key(s)")
    return _identity(go)


def cmd_repo_member(args) -> int:
    def go(conn, store, audit):
        repo, agent = store.get_repo(conn, args.slug), store.get_agent(conn, args.handle)
        if repo is None or agent is None:
            raise LookupError(f"no {'repository ' + args.slug if repo is None else 'agent ' + args.handle}")
        if args.role == "none":
            removed = store.remove_member(conn, repo.id, agent["id"])
            audit.append(conn, "member.remove", f"agent:{args.handle}", repository_id=repo.id,
                         detail={"removed": removed})
            print("removed" if removed else "was not a member")
        else:
            store.set_member(conn, repo.id, agent["id"], args.role, granted_by=None)
            audit.append(conn, "member.set", f"agent:{args.handle}", repository_id=repo.id,
                         detail={"role": args.role})
            print(f"{args.handle} is now {args.role} of {args.slug}")
    return _identity(go)


def cmd_mcp(args) -> int:
    import os

    from .serve import mcp_tools
    mcp_tools.run(args.api or os.environ.get("RRSRCH_API_URL", "http://127.0.0.1:8787"),
                  os.environ.get("RRSRCH_API_KEY"), read_only=args.read_only)
    return 0


def cmd_eval_run(args) -> int:
    import json
    import os
    from pathlib import Path

    import psycopg

    from .bench import questions
    from .evals import run as ev
    from .evals import scoring
    from .evals.agent import LLMAgent
    from .evals.budget import Budget
    from .ledger import db
    from .reader.llm import LLM
    ledger = os.environ.get("RRSRCH_DATABASE_URL", db.DEFAULT_URL)
    if ev.same_database(args.db, ledger):
        print("error: --db is the ledger database, or one of the two couldn't be reached to tell them apart\n"
              "(check --db and RRSRCH_DATABASE_URL). Run evaluations on a copy, e.g.\n"
              "  createdb -T rrsrch rrsrch_eval   (or pg_dump rrsrch | psql rrsrch_eval)", file=sys.stderr)
        return 2
    conditions = tuple(c.strip().upper() for c in args.conditions.split(",") if c.strip())
    if not conditions or set(conditions) - set(ev.CONDITIONS):
        print(f"error: --conditions must be some of {','.join(ev.CONDITIONS)}", file=sys.stderr)
        return 2
    if args.model:
        os.environ["RRSRCH_READER_MODEL"] = args.model
    try:
        llm = LLM.from_env()                  # URL, model and RRSRCH_LLM_TIMEOUT, validated
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    import httpx
    model_client = httpx.Client(timeout=llm.timeout)
    tasks = ev.tasks_from_benchmark(questions.load(), args.only)
    cfg = ev.Config(conditions=conditions, agents=args.agents, repeats=args.repeats,
                    seeded_errors=args.seeded_errors,
                    budget=Budget(max_tool_calls=args.max_tool_calls, max_tokens=args.max_tokens))
    harness = ev.Harness(lambda: psycopg.connect(args.db), cfg)
    try:
        result = harness.run(tasks, lambda cond, i, handle: LLMAgent(handle, llm.base_url, llm.model,
                                                                     client=model_client), progress=print)
    finally:
        model_client.close()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    raw = out / f"eval-{cfg.run_id}.json"
    raw.write_text(json.dumps(result, indent=1, default=str))
    scored = scoring.score(result)
    (out / f"eval-{cfg.run_id}.md").write_text(scoring.markdown(scored))
    print(scoring.markdown(scored))
    print(f"wrote {raw}")
    return 0


def cmd_eval_report(args) -> int:
    import json
    from pathlib import Path

    from .evals import scoring
    print(scoring.markdown(scoring.score(json.loads(Path(args.result).read_text()))))
    return 0


def cmd_audit_verify(args) -> int:
    from .ledger import db
    from .trust import audit
    with db.connect() as conn:
        n = conn.execute("SELECT count(*) FROM audit_events").fetchone()[0]
        problems = audit.verify(conn)
    for pr in problems:
        print(pr)
    print(f"{n} event(s), {'chain intact' if not problems else f'{len(problems)} problem(s)'}")
    return 1 if problems else 0


def cmd_indexnow(args) -> int:
    import time

    from .collab import indexnow
    from .ledger import db
    while True:
        with db.connect() as conn:
            if args.seed:
                print(f"queued {indexnow.seed(conn)} public page(s)")
                conn.commit()
                args.seed = False
            out = indexnow.send(conn)
        print(f"indexnow: {out['sent']} sent, {out['failed']} failed, {out['pending']} pending"
              + (f" (skipped: {out['skipped']})" if out.get("skipped") else ""), flush=True)
        if args.once:
            return 1 if out["failed"] else 0
        time.sleep(600)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="rrsrch")
    sub = p.add_subparsers(dest="group", required=True)
    corpus = sub.add_parser("corpus").add_subparsers(dest="cmd", required=True)
    d = corpus.add_parser("discover", help="draft the corpus from meta-analyses (PubMed ids)")
    d.add_argument("pmids", nargs="+")
    d.add_argument("--topic")
    d.set_defaults(fn=cmd_discover)
    f = corpus.add_parser("fetch", help="snapshot every source and trial locally")
    f.add_argument("--refresh", action="store_true", help="re-fetch and report what changed at the source")
    f.set_defaults(fn=cmd_fetch)
    corpus.add_parser("verify").set_defaults(fn=cmd_verify)
    corpus.add_parser("status").set_defaults(fn=cmd_status)
    ledger = sub.add_parser("ledger").add_subparsers(dest="cmd", required=True)
    ledger.add_parser("load").set_defaults(fn=cmd_ledger_load)
    read = sub.add_parser("read").add_subparsers(dest="cmd", required=True)
    rp = read.add_parser("plan", help="what the reader would send the model")
    rp.add_argument("-v", "--verbose", action="store_true")
    rp.set_defaults(fn=cmd_read_plan)
    rr = read.add_parser("run", help="extract claims with the configured model")
    rr.add_argument("--source", action="append", help="only this source id (repeatable)")
    rr.add_argument("--limit", type=int, help="only the first N sources")
    rr.set_defaults(fn=cmd_read_run)
    ra = read.add_parser("agent", help="run the reader as a standing agent that proposes claims through the API")
    ra.add_argument("--once", action="store_true", help="one cycle, then exit")
    ra.add_argument("--dry-run", action="store_true",
                    help="one cycle that reads and prints what it would propose or post, writing nothing")
    ra.set_defaults(fn=cmd_read_agent)
    read.add_parser("stats").set_defaults(fn=cmd_read_stats)
    g = sub.add_parser("gate", help="check a sentence against ledger claims")
    g.add_argument("sentence")
    g.add_argument("claims", nargs="+", metavar="CLAIM_ID")
    g.set_defaults(fn=cmd_gate)
    ge = sub.add_parser("gate-eval", help="score the gate on its evaluation set")
    ge.add_argument("-v", "--verbose", action="store_true")
    ge.set_defaults(fn=cmd_gate_eval)
    trials = sub.add_parser("trials").add_subparsers(dest="cmd", required=True)
    tr = trials.add_parser("reconcile", help="registrations against their papers")
    tr.add_argument("-v", "--verbose", action="store_true")
    tr.set_defaults(fn=cmd_trials_reconcile)
    skeptic = sub.add_parser("skeptic").add_subparsers(dest="cmd", required=True)
    skeptic.add_parser("run", help="find ledger claims that agree or contradict").set_defaults(
        fn=cmd_skeptic_run)
    ss = skeptic.add_parser("show", help="list stored contradictions")
    ss.add_argument("-v", "--verbose", action="store_true")
    ss.set_defaults(fn=cmd_skeptic_show)
    sv = sub.add_parser("serve", help="HTTP answer API (POST /v1/answer)")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8787)
    sv.set_defaults(fn=cmd_serve)
    bench = sub.add_parser("bench").add_subparsers(dest="cmd", required=True)
    bc = bench.add_parser("check", help="validate the benchmark against the answer key")
    bc.add_argument("-v", "--verbose", action="store_true")
    bc.set_defaults(fn=cmd_bench_check)
    br = bench.add_parser("run", help="write and score a report for each benchmark question")
    br.add_argument("--only", action="append", metavar="ID", help="only this question (repeatable)")
    br.set_defaults(fn=cmd_bench_run)
    w = sub.add_parser("write", help="answer a question from the ledger, every sentence gated")
    w.add_argument("question")
    w.set_defaults(fn=cmd_write)
    org = sub.add_parser("org").add_subparsers(dest="cmd", required=True)
    oa = org.add_parser("add", help="create an organization")
    oa.add_argument("id")
    oa.add_argument("name")
    oa.set_defaults(fn=cmd_org_add)
    agent = sub.add_parser("agent").add_subparsers(dest="cmd", required=True)
    aa = agent.add_parser("add", help="register an agent")
    aa.add_argument("handle")
    aa.add_argument("--org", required=True)
    aa.add_argument("--kind", choices=("service", "model", "human"), default="service")
    aa.add_argument("--model", help="model/provider, if you want it disclosed")
    aa.add_argument("--admin", action="store_true", help="make it an admin of its organization")
    aa.set_defaults(fn=cmd_agent_add)
    ak = agent.add_parser("key", help="issue an API key")
    ak.add_argument("handle")
    ak.add_argument("--scope", action="append", required=True,
                    choices=("read", "propose", "review", "maintain", "administer", "agents"))
    ak.add_argument("--days", type=int, default=None,
                    help="a fixed lifetime; without it the key stays valid while used (expires after 90 idle days)")
    ak.add_argument("--label", default="")
    ak.set_defaults(fn=cmd_agent_key)
    ar = agent.add_parser("revoke", help="revoke an agent and all its keys")
    ar.add_argument("handle")
    ar.set_defaults(fn=cmd_agent_revoke)
    repo = sub.add_parser("repo").add_subparsers(dest="cmd", required=True)
    rm = repo.add_parser("member", help="grant a repository role")
    rm.add_argument("slug")
    rm.add_argument("handle")
    rm.add_argument("role", choices=("observer", "contributor", "reviewer", "maintainer", "owner", "none"))
    rm.set_defaults(fn=cmd_repo_member)
    au = sub.add_parser("audit").add_subparsers(dest="cmd", required=True)
    au.add_parser("verify", help="check the audit chain").set_defaults(fn=cmd_audit_verify)
    ix = sub.add_parser("indexnow", help="send the IndexNow queue (RRSRCH_INDEXNOW_KEY); loops every 10 minutes")
    ix.add_argument("--once", action="store_true", help="send once and exit (for a timer)")
    ix.add_argument("--seed", action="store_true", help="first queue every public claim and question")
    ix.set_defaults(fn=cmd_indexnow)
    mc = sub.add_parser("mcp", help="MCP server over stdio; acts as the agent whose key is in RRSRCH_API_KEY")
    mc.add_argument("--api", help="API base URL (default $RRSRCH_API_URL or http://127.0.0.1:8787)")
    mc.add_argument("--read-only", action="store_true", help="offer only the read tools")
    mc.set_defaults(fn=cmd_mcp)
    ev = sub.add_parser("eval").add_subparsers(dest="cmd", required=True)
    er = ev.add_parser("run", help="run the A/B/C experiment on the benchmark questions")
    er.add_argument("--db", required=True, help="a dedicated evaluation database (a copy of the ledger)")
    er.add_argument("--conditions", default="A,B,C")
    er.add_argument("--agents", type=int, default=3)
    er.add_argument("--repeats", type=int, default=1)
    er.add_argument("--seeded-errors", type=int, default=2)
    er.add_argument("--max-tool-calls", type=int, default=30)
    er.add_argument("--max-tokens", type=int, default=60_000)
    er.add_argument("--model", help="model name (default $RRSRCH_READER_MODEL)")
    er.add_argument("--only", nargs="+", help="benchmark question ids")
    er.add_argument("--out", default="evals")
    er.set_defaults(fn=cmd_eval_run)
    ep = ev.add_parser("report", help="score a saved run")
    ep.add_argument("result")
    ep.set_defaults(fn=cmd_eval_report)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
