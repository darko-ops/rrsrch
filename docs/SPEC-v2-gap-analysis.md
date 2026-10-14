# SPEC v2 — Gap Analysis

Where the codebase stands against [`SPEC-v2.md`](SPEC-v2.md), as of `a18d651` (2026-10-13).

**Status key:** **Built** · **Partial** · **Missing**

## Summary

Today `engine/` is a **single-tenant, single-topic evidence pipeline** (MSC therapy for knee osteoarthritis). It already embodies the spec's hardest idea — *deterministic gates over LLM output, anchored to hashed source text* — but has none of the multi-party structure the spec is built around: no repositories, agents, roles, revisions, review workflow, or MCP.

What the engine does now:

1. Builds a fixed corpus from the included studies of 8 meta-analyses, snapshotting Europe PMC and ClinicalTrials.gov records with pinned SHA-256s.
2. Loads them into a Postgres ledger; an LLM extracts claims, each anchored to an exact character span of hashed text. Rule-failing claims are kept as rejections.
3. A deterministic skeptic finds pairwise agreements/contradictions between claims; a reconciler compares trial registrations to publications to flag endpoint drift.
4. A writer answers questions from lexically retrieved claims; every sentence must pass the citation gate or is refused and logged.
5. Answers are served as JSON by a small unauthenticated HTTP server, proxied and cached by the Vercel site, and scored on a 25-question benchmark.

So the spec's **Trust Engine (§10)** and **Evaluation (§27)** have real foundations; **Knowledge Network, Collaboration, Incentives, and Governance** are essentially greenfield.

## MVP scope (§26) vs. code

| MVP requirement | Status | Evidence | Gap |
|---|---|---|---|
| Agent registration | Missing | — | No agent/principal/org tables or endpoints |
| Authenticated API access | Missing (engine) / Partial (site) | Engine `serve/http.py` has no auth, CORS defaults to `*`. Site (`server.js`) has HMAC bearer tokens, bcrypt login, Google OAuth, device pairing; users stored in Vercel Blob | No scoped credentials, no roles, nothing on the engine |
| Public and private repositories | Missing | Closest: `user.projects` in `server.js` | No owner / visibility / contribution policy / tenancy |
| Structured knowledge claims | Partial | `claims` table (`db/migrations/0001_ledger.sql`), span-anchored with `doc_sha256`; extractor + prompt version recorded | No claim `type` (§7.2), no lifecycle `state` (§7.3), no scope/assumptions fields |
| Evidence and citations | Partial | `sources.license`, `snapshot_sha256`; `documents.sha256`; `fetched_at` per snapshot in `corpus/snapshots.lock.json` | No primary-vs-derivative flag; retrieval timestamp lives in lockfile, not DB; no supports/contradicts link table (agreements live in `claim_agreements`, claim↔claim only) |
| Basic provenance graph | Partial | claim → document → source FKs; `read_chunks` traces model inputs | No contributor or revision nodes; no circular-citation detection |
| Deterministic validation | **Built (domain-specific)** | Citation gate `check/gate.py:138` (cites/scope/direction/entities/numbers) with 39-case eval (`check/gate_cases.yaml`); skeptic `skeptic/agree.py:125`; version tags `reader-v1`, `writer-v1`, `skeptic-v1`, `reconcile-v1`, `coverage-v1` | Rules are clinical-vocabulary-specific; no generic schema/policy/merge stages (§10.2 steps 1–5, 7–10) |
| Revision history | Partial | Content hashes; `ChangedUnderClaims` guard blocks rewriting a document under existing claims (`ledger/db.py`) | No revision tables (documents UPDATE in place); no optimistic concurrency |
| Claim search | Partial | `writer/retrieve.py` — lexical + controlled-vocab scoring, full scan ("No embeddings yet") | pgvector + `claims.embedding` exist but unused; no Postgres FTS |
| MCP read + contribution tools | Missing | Legacy `rrsrch/` MCP (`search`, `recalls`, `deposit`, `corroborate`) was source-deleted in `82a9e10` | Nothing in `engine/` (see "Housekeeping") |
| Human-controlled merge approval | Missing | Only `review: true` on corpus manifest entries (`corpus/manifest.py`) | No merge requests, approvals, or blocking rules |
| Basic audit trail | Partial | Append-style records: `claim_rejections`, `read_chunks`, `report_sentences.check_log`, `evidence` jsonb on agreements/reconciliations | No actor-attributed `AuditEvent`; no integrity chaining |

## Data model (§17) vs. schema

| Spec entity | Exists? | Closest current thing |
|---|---|---|
| Organization, Principal, Agent, Membership | No | Site users (JSON blob in Vercel Blob) |
| Repository | No | — (implicitly: the whole DB is one repo) |
| Claim | Partial | `claims` |
| ClaimRevision | No | — |
| Evidence / EvidenceLink | Partial | `sources` + `documents` + claim spans; `claim_agreements` |
| Discussion, Message, ResearchTask, Review, MergeRequest, Subscription | No | — |
| VerificationRun | Partial | `report_sentences.check_log`, `report_coverage`, gate verdicts (not first-class runs) |
| ContributionEvent | No | Legacy `depositor_trust` (deleted) |
| AuditEvent | No | See audit row above |

## Roadmap phases beyond the MVP

| Spec area | Status | Notes |
|---|---|---|
| §8 Collaboration (discussions, challenges, tasks, notifications) | Missing | `claim_agreements` contradictions are the nearest analogue to a "challenge" |
| §11 Reputation | Missing | Legacy had `depositor_trust` (agreed/contradicted/score); source recoverable from `82a9e10~1` |
| §18.4 A2A | Missing | Phase 3 by spec — no action needed |
| §27 Evaluation harness | **Built (single-condition)** | `benchmark/questions.yaml` (25 Qs), `bench/run.py` scores faithfulness, coverage, rejection rate. Expected answers still await domain review. No A/B/C (isolated / shared / collaborative) conditions yet |

## Stack: spec (§16.2) vs. actual

| Component | Spec | Actual |
|---|---|---|
| Backend API | FastAPI | stdlib `http.server` (engine); Express (site) |
| DB | PostgreSQL | Postgres 16 + pgvector ✅ (hand-written SQL migrations, `ledger/db.py`) |
| Validation | Pydantic | dataclasses only; deps are just `httpx`, `psycopg`, `pyyaml` |
| Search | FTS + optional pgvector | lexical in Python |
| Queue / object storage | Redis / S3 | none (corpus snapshots on disk) |
| Web | Next.js / TS | React 19 (CRA) + Express on Vercel |
| Auth | OAuth + scoped service creds | site-only HMAC tokens + Google OAuth |
| Agent integration | HTTP + MCP | HTTP only |
| Deployment | Containers, managed DB | Engine on a local box exposed via Cloudflare tunnel (`scripts/expose-via-spark.sh`) |

## What to reuse vs. build

**Reuse — this is the moat and it's already working:**

- Span-anchored, hash-pinned claims and the `ChangedUnderClaims` invariant → basis for §7.4 evidence records and §17.2 integrity model.
- The citation gate and skeptic → become *Step 6 (Evidence Evaluation)* and part of *Step 7 (Independence)* of the §10.2 pipeline, rather than being the whole pipeline.
- Version-tagged rule/prompt sets → seed of "policy version" on every decision.
- The benchmark runner → baseline for condition **A** in §27.3.

**Build (in spec milestone order, §32):**

1. **M1 Canonical schema** — add `repositories`, `claim.type`, `claim.state`, `claim_revisions`, `evidence_links` (supports/contradicts/derived_from), `verification_runs`; Pydantic models + canonical-JSON hashing; migrate the existing MSC corpus into a first repository (`rrsrch/msc-knee-oa`) rather than discarding it.
2. **M2 Identity** — `organizations`, `principals`, `agents`, `memberships`, scoped API keys on the engine. Decide whether site auth (`server.js`) remains separate or becomes the identity provider.
3. **M3 Trust engine** — wrap gate/skeptic into the 10-step pipeline with explicit policy objects and deterministic merge authorization; `audit_events` with hash chaining.
4. **M4 Knowledge API** — the §18.1 Knowledge + Repositories endpoints.
5. **M5 MCP** — new server in `engine/` exposing `search_knowledge`, `get_claim`, `get_evidence`, `list_repositories`, `propose_claim`, `get_verification_status`.

## Decisions to make before M1

1. **HTTP framework.** Stay on stdlib `http.server` or adopt FastAPI as §16.2 proposes. The §18 surface (~30 endpoints, auth, pagination, idempotency, validation errors) is a strong argument for FastAPI + Pydantic now.
2. **Generic vs. clinical trust rules.** The gate is tuned to clinical vocabulary. §24.2 proposes a *security-controls* wedge. Either keep MSC as the pilot repository (existing benchmark, existing evidence) or start a second domain — which means generalising the gate's vocabulary layer.
3. **Identity source of truth.** Site users live in a Vercel Blob JSON file; that won't carry orgs/roles/memberships. Move identity into engine Postgres?
4. **Legacy code.** The deleted `rrsrch/` had a FastAPI app, SQLAlchemy models, MCP server, HMAC attestation and depositor trust scoring — several pieces map directly to M2/M5/§11. Recover selectively from `82a9e10~1` rather than rewrite.

## Housekeeping found during the audit

- The `rrsrch` MCP server in `~/.claude.json` points at `rrsrch/.venv/bin/rrsrch-mcp`, whose source was deleted in `82a9e10`; it fails to connect every session. Remove it or repoint it once an engine MCP exists (M5).
- `~/code/rrsrch` is the archive repo (`rrsrch-engine-archive`) but has uncommitted edits to `serve/answer.py`.
- `SPEC-v2.md` §13.3 has a truncated sentence in the source draft (marked `TODO`).
