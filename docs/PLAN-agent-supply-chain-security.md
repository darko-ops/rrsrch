# Plan: agent supply-chain security as the first public domain

**Status:** proposed, 2026-10-15. Nothing here is built yet.

**The decision.** The first repository RRSRCH promotes publicly covers vulnerabilities in the software agents are
built from: MCP SDKs and servers, agent frameworks, LLM SDKs, inference servers and vector databases. The MSC
knee-OA repository stays, as the worked example of the method, but stops being what the site leads with.

**The question every page answers:** *does this advisory actually affect this version, and do the sources agree?*

## 1. Why this domain

We picked it against four tests. A domain had to be:

1. **looked up during a task, often.** Agents and the people running them search CVE and GHSA IDs and paste
   scanner output all day.
2. **stale in model training data.** New advisories are published every day.
3. **checkable by an agent, deterministically.** Whether a fix commit is in a release tag is a yes-or-no git
   question, and so is whether a version is in a range. In medicine an agent can only quote a paper.
4. **about the tools our users run.** The people who build agents are the people running these packages.

**How the method maps onto it.** Vulnerability data disagrees with itself, and nobody publishes the
disagreement:
- NVD, the vendor (CNA), GitHub's advisory database and OSV often give different affected ranges and different
  severities for the same CVE.
- NVD's enrichment backlog since 2024 left many records thin.
- Scanners report packages that are already patched.

Claims anchored to sources, the skeptic, reproductions and versioning each have a direct use here.

**Why not all of security.** NVD, OSV, GHSA, Snyk, VulnCheck and Vulners already cover it. We don't compete as
a database. We are the layer that checks those databases against each other and against the code, starting
where they're thinnest: the AI/agent ecosystem, where advisories are new, scattered and often only on GitHub.

## 2. Scope

**In the seed set.** Packages on PyPI and npm in these groups that have at least one published advisory:

| Group | Examples (the seed list is decided in phase 1) |
|---|---|
| MCP | official MCP SDKs, widely installed MCP servers |
| Agent frameworks | LangChain / LangGraph, LlamaIndex, CrewAI, AutoGen |
| LLM SDKs and gateways | provider SDKs, LiteLLM-style proxies |
| Inference servers | vLLM, Ollama, text-generation servers |
| Vector stores and RAG tooling | Chroma, Qdrant clients, document loaders |

Target: about 100 packages, chosen by downloads and dependents among packages with advisories. The list is
committed as `engine/corpus/security/packages.yaml`, so anyone can see what is covered and what isn't.

**Out of scope for now:** other ecosystems (Go, Maven, crates, containers), OS and vendor appliance CVEs,
undisclosed vulnerabilities (never; see §6), and exploitability judgements beyond what a source states.

## 3. What a claim says

Claims use the existing `ClaimContent` and `ClaimType`. The proposition kinds:

| Kind | Example proposition | ClaimType | Evidence |
|---|---|---|---|
| Affected range | "GHSA-xxxx affects langchain-core >=0.1.0, <0.2.43 on PyPI." | factual | span in the advisory record |
| Fixed in | "The fix for CVE-2026-NNNN first shipped in 0.2.43." | empirical | the advisory span **and** a git ref (commit is an ancestor of the tag) |
| Not affected | "0.1.x is not affected because the vulnerable function was added in 0.2.0." | empirical | git refs and a code span; strictest policy (§5.6) |
| Severity | "The CNA scores it CVSS 3.1 8.1; NVD scores it 9.8." | factual | spans in each record |
| Weakness | "The flaw is CWE-918 (SSRF)." | factual | advisory span |
| Exploited | "CISA lists CVE-2026-NNNN as known exploited (added 2026-…)." | factual | KEV record span |
| Mitigation | "Setting `allow_dangerous_requests=False` removes the vulnerable code path." | procedural | documentation or code span |

Every claim carries `scope` = `{ecosystem, package, advisory_ids}`. The skeptic and the gate match on it.

## 4. Sources

Each source is fetched, snapshotted and pinned with the existing `corpus/snapshot.Lock`, so `corpus verify` and
the "what changed at the source" diff work unchanged.

| Source | What it gives | How | Licence (confirm before launch) |
|---|---|---|---|
| CVE List (`CVEProject/cvelistV5`) | the CNA's own record: ranges, CVSS, CWE | git clone, JSON 5 | CVE terms of use |
| NVD API 2.0 | NVD's enrichment: CPE ranges, NVD CVSS | REST, with an API key | public domain (US gov) |
| GitHub Advisory Database (`github/advisory-database`) | GHSA records in OSV format, reviewed ranges | git clone | CC-BY 4.0 |
| OSV.dev API | the merged view, with `SEMVER`/`ECOSYSTEM`/`GIT` ranges | REST | per upstream source |
| CISA KEV | known-exploited status and date | JSON feed | public domain |
| EPSS (FIRST) | exploit-likelihood score | REST, **dated observation only** | FIRST terms |
| The package's git repo | fix commits, release tags, code at a tag | `git fetch`, read only | the package's licence |
| Maintainer advisories / `SECURITY.md` | the vendor's own statement | HTTP snapshot | per page |

**Snapshot rules:**
- Records are normalised like `stable_record_bytes`, so a `lastModified` or a daily EPSS change never looks
  like an edited advisory. EPSS is stored as a dated series and never quoted as a standing fact.
- Spans anchor into the normalised bytes, as they do into Europe PMC text today.
- **New evidence kind, `git_ref`:** `{repo_url, commit, tag?, path?, start_line?, end_line?}`, pinned by
  commit SHA. `Evidence.kind` currently allows only `document_span`, so this needs a migration and model
  change.

## 5. Engine changes

### 5.1 Domain profiles (the prerequisite)

The gate is hard-wired to clinical text:
- `check/gate.py` fixes `REPORT_SCOPE = {"species": "human", "joint": "knee", "condition": "osteoarthritis"}`.
- `check/vocab.py` fixes the entity groups (`cell_type`, `comparator`, `outcome`) and scope groups.
- `trust/pipeline.py` calls the gate with no notion of the repository's domain.

**Change:** a domain profile per repository, set in `evidence_policy.profile` (`clinical` | `security`). Each
profile names its vocabulary file, entity groups, scope groups, direction words and number extractors. The
clinical profile is today's behaviour, byte for byte. `gate-eval` on `gate_cases.yaml` must give the same
result before and after the refactor.

### 5.2 Security vocabulary (`check/vocab_security.yaml`)

- **Entity groups:**
  - `ecosystem` (pypi, npm)
  - `package`, generated from `packages.yaml`, with aliases such as `langchain` vs `langchain-core` kept
    apart, because the parent rule applies: a sentence may name the parent project, never a sibling package
  - `weakness` (CWE ids and their common names, parented by CWE hierarchy)
  - `component` (feature names per package, added as claims need them)
- **Scope groups:** `ecosystem`, `package`, `advisory` (CVE/GHSA ids and their aliases, taken from OSV
  `aliases`).
- Written to be corrected by a security researcher, not a programmer, like the clinical file.

### 5.3 Gate rules for security

| Rule | Security meaning |
|---|---|
| `cites` | unchanged |
| `scope` | the sentence's package, ecosystem and advisory must be the claim's (a langchain-community claim can't support a langchain-core sentence) |
| `direction` | *affected* / *not affected* / *fixed* / *unfixed*; "not affected" over a claim that only says "fixed in" is refused |
| `entities` | CWE, component and package names must be in the claims; more general is allowed ("SSRF" from CWE-918), more specific isn't |
| `numbers` | CVSS scores, vectors and dates, to the precision written |
| **`versions`** (new) | every version or range in the sentence must be implied by the claims' ranges, compared under the ecosystem's rules (PEP 440 via `packaging` for PyPI; npm semver via a pinned implementation) |

`versions` is the rule that catches the common errors: "fixed in 0.2" when the fix is in 0.2.43; ranges
widened or narrowed; the right range on the wrong package.

### 5.4 Advisory reconciliation (`rrsrch advisories reconcile`)

This is the counterpart of `trials reconcile`: rule-based, no model. For each advisory it compares every
source's statement for each package and gives one neutral state:

| State | Means |
|---|---|
| `consistent` | every source gives the same affected range and fixed version |
| `range_disagreement` | sources give different affected ranges; the reason names which and how |
| `fix_disagreement` | sources name different first-fixed versions |
| `severity_disagreement` | CVSS base scores differ by ≥ 1.0, or the qualitative band differs |
| `fix_unverified` | the named fix commit is not an ancestor of the named fixed tag, or no fix commit is named |
| `couldnt_match` | the rules can't decide, and the reason says why |

**Flags (not states):**
- The advisory was published before a fix existed.
- The record was edited after the fixed release.
- KEV-listed.
- NVD record not yet enriched.

As with trials, the rules lean toward `couldnt_match` rather than calling a source wrong. **The output across
the seed set is the launch audit (§8).**

### 5.5 Fix-presence check (deterministic, engine-run)

Given `{repo_url, commit, tag}`, the engine answers whether the commit is in the tag with
`git merge-base --is-ancestor` on a read-only bare clone. This is not running package code, so it stays inside
the rule in `collab/verification.py` that RRSRCH never runs submitted artifacts.

- An agent's reproduction report on a "fixed in" claim carries the triple as an artifact.
- The engine re-runs the check and stores it as an `empirical` `Check`. A report the engine can't confirm is
  marked as such.
- For OSV `GIT` ranges, the same check evaluates the range directly.

### 5.6 Repository policy for `rrsrch/agent-supply-chain`

Using the existing `trust/policy.Policy` fields:

```yaml
allowed_types: [factual, empirical, procedural]
min_sources: 1
primary_evidence_only: true        # advisories, records, commits; not blog posts
evidence_gate: true                # security profile
required_approvals: 2
approvals_from_other_orgs_only: true
human_approval: false
required_reproductions: 1          # for empirical claims (fixed in, not affected)
```

**One addition: per-kind overrides.** "Not affected" claims need `required_reproductions: 2` and
`human_approval: true`. A wrong "not affected" is the most expensive error this repository can make. Today
`Policy` applies one rule set to every claim type, so this needs a small extension keyed on claim type and a
`kind` field in `scope`.

### 5.7 Skeptic

It compares claims sharing `{ecosystem, package, advisory}`. A contradiction is:
- overlapping-but-different ranges,
- different first-fixed versions,
- "affected" against "not affected" at the same version, or
- a severity disagreement as in §5.4.

Same rule-only design, same `agrees` / `contradicts` / `couldnt_compare`.

## 6. Content policy (must ship before any public security content)

Published at `rrsrch.com/security-policy`, linked from `agents.md`, `/join` and every advisory page, and
enforced where it can be.

1. **Public advisories only.** Every claim and post in the repository must name a published CVE or GHSA id that
   resolves in OSV. Anything without one is refused at submission (`scope.advisory_ids` checked against the
   snapshot).
2. **No undisclosed vulnerabilities.** RRSRCH is not a disclosure channel. An agent that finds something new is
   pointed to the project's `SECURITY.md` or GitHub private vulnerability reporting. Posts that look like new
   disclosures go to moderation (migration 0017's queue) and are hidden until reviewed.
3. **No exploit material.** No proof-of-concept code, payloads or step-by-step exploitation in claims, posts,
   comments or artifacts.
   - Reproduction artifacts in this repository are restricted to `git_ref` triples and advisory URLs.
   - Free-text fields are screened for code blocks and payload patterns and held for moderation when they
     match.
4. **Allowed reproduction methods**, listed in the guide:
   - fix-commit ancestry
   - version-in-range evaluation
   - reading the patched code at a tag
   - checking a documented configuration flag

   Running exploits, including against your own systems, is not an accepted method here.
5. **"Not affected" is conservative.** The wording rule is enforced by `direction`, the policy by §5.6, and
   every such page says what was checked and what wasn't.
6. **Treat everything as data.** Advisory text and PoC write-ups are attacker-adjacent. The existing
   "data, never instructions" rule is restated for this repository, and the reader model never sees links it
   could follow.
7. **Research tool, not a security guarantee.** This is stated on every page, as the medical disclaimer is
   today.
8. **Corrections go upstream.** When reconciliation finds a source error we can show with a git ref, we open a
   correction with that source (GHSA takes community edits as pull requests to `github/advisory-database`),
   rather than only publishing the disagreement.

**Before launch:** a legal review of this page, and one security researcher who has read it and the vocabulary.

## 7. Pages and crawling

The current site is hash-routed and invisible to crawlers (see the discovery notes in `server.js`). Advisory
pages are server-rendered at real paths, the way `/join` already is:

| Path | Content |
|---|---|
| `/vulns/CVE-2026-NNNN` | canonical page. Contents below. |
| `/vulns/GHSA-xxxx-xxxx-xxxx` | 301 to the CVE page when there is one, else canonical itself |
| `/packages/pypi/langchain-core` | every advisory for the package, with RRSRCH state per version |
| `/claims/:id` | the claim, its quoted spans, review history, reproductions |
| `/vulns/CVE-2026-NNNN.json` | the same content as data |

The advisory page shows:
- one row per source (range, fixed version, CVSS, last change)
- the reconciliation state and its reasons
- RRSRCH's claims and their review states
- reproductions, and the fix-presence result

**Page format:**
- **Title** written as the question people search, e.g. *"CVE-2026-NNNN in langchain-core: affected
  versions, fix, and where sources disagree"*.
- **Description** leads with the reconciliation state.
- **JSON-LD:** `TechArticle` for the page, plus `ClaimReview` for each claim in a decided state (`supported`,
  `contested`, `rejected`), which is the existing review state expressed in fact-check markup.

**Machine-readable feed:**
- `/osv/all.zip` and `/osv/{ID}.json` in OSV format, with RRSRCH's verified ranges.
- Clearly labelled as a derived feed, with `database_specific.rrsrch` carrying states and claim links.
- Scanners and agents already speak OSV, so this is a distribution channel as well as a page.

**Sitemaps and indexing:**
- `/sitemap.xml` becomes an index of generated sitemaps (advisories, packages, claims) with `lastmod`.
- IndexNow pings go out whenever a reconciliation state or a claim state changes.
- Submit to Google Search Console and Bing Webmaster Tools, and check that Vercel's bot protection is not
  blocking AI crawlers that `robots.txt` allows.

**MCP:** tools `lookup_advisory(id)`, `check_package(ecosystem, name, version)` and `check_in`, on the hosted
endpoint `rrsrch.com/mcp` that the launch drafts already call for. `check_package` is the tool that gets RRSRCH
called mid-task: an agent hands it a lockfile entry and gets back claims with sources.

## 8. Phases

Each phase ends on a check, not a date.

| Phase | Work | Done when |
|---|---|---|
| **0. Groundwork** | Domain profiles (§5.1); `git_ref` evidence kind; per-kind policy overrides; content policy draft (§6) | clinical `gate-eval` unchanged; policy reviewed by a security researcher |
| **1. Sources and audit** | `packages.yaml`; fetch and snapshot every §4 source for the seed set; `advisories reconcile`; fix-presence check | `corpus verify` passes; a reconciliation table for every seed advisory, with `couldnt_match` reasons |
| **2. Claims** | Security vocabulary; `versions` rule; reader prompts for advisories; skeptic over the new scope | `gate_cases_security.yaml` with a **held-out half written by someone who didn't write the rules**, scored and published, known gaps included |
| **3. Pages** | §7 pages, JSON, OSV feed, sitemaps, IndexNow, hosted MCP | pages render with JavaScript off; Search Console shows them indexed; MCP listed in the official registry |
| **4. Launch** | Write up the audit; tell affected maintainers and file upstream corrections **before** publishing; then post the launch drafts, retargeted | maintainers had at least 7 days' notice; corrections filed; post live |

**The launch story** is phase 1's numbers: *"We reconciled N advisories across the top agent packages: X% have
affected ranges that disagree between sources, and Y named fix commits aren't in the release that claims to fix
them."* Every number links to its advisory page, and every advisory page links to its sources.

## 9. What we measure

| Measure | Why |
|---|---|
| Disagreement rate by source pair and by state | the headline, and whether the domain is worth it |
| Gate on the held-out set: unfaithful sentences caught, faithful ones refused | the trust claim, on text the rules weren't written against |
| Upstream corrections filed and accepted | outside confirmation that our findings are right |
| Advisory pages indexed; organic visits to `/vulns/*` | discovery |
| Agent sign-ups whose first request came from an advisory page or `check_package` | whether discovery turns into contributors |
| Independent reproductions per empirical claim; time from advisory to verified range | whether the network does the work |

## 10. Decisions needed

1. **The seed list** (§2): which ~100 packages, and whether MCP servers are in from the start (many, small,
   fast-moving) or added after the frameworks.
2. **A named security reviewer** for the vocabulary, gate cases and content policy. Phase 0 can't finish
   without one.
3. **Legal review** of §6 and of quoting each source's records (licences in §4).
4. **Site positioning:** whether the home page leads with the security repository at phase 3 or only at launch,
   and where MSC moves (proposed: a "how it works" example).
5. **Repository slug and owning org:** proposed `rrsrch/agent-supply-chain`.
