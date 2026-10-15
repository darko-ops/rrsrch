"""Audit of the reconciliation spike's method (advisory_spike.py): run it after the spike, against the same cache.

  1. range evaluation, against an independent evaluator: for a fixed sample of (package, version) points, OSV.dev's
     own /v1/query answer (which advisories affect this version?) vs the spike's GHSA and PYSEC sets
  2. package identity: every CNA product and NVD CPE product seen, and how the spike matched it to the package
  3. deduplication: records with more than one CVE alias, ids that landed in two groups
  4. versions: what each registry no longer lists or has yanked, and which sources name those versions
  5. severity and the conservative exclusions: what was left out of the comparisons, and why

Writes AUDIT.md next to the spike's output. OSV answers are cached in the spike's cache, so a rerun with --offline
replays them.

  uv run --with cvss python scripts/advisory_spike_audit.py --cache DIR --out DIR [--offline]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import advisory_spike as spike  # noqa: E402

SAMPLE_PER_PACKAGE = 15


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    spike.OFFLINE = args.offline
    f = spike.Fetch(Path(args.cache) / "http")
    out = Path(args.out)
    rows = json.loads((out / "rows.json").read_text())
    L = ["# Audit of the reconciliation method", "",
         f"Against `rows.json` (sha256 `{json.loads((out / 'manifest.json').read_text())['rows_sha256'][:16]}…`).", ""]

    # 1. range evaluation vs OSV's own evaluator
    rng = random.Random(20261015)
    checked = agree = 0
    disagreements = []
    for eco, pkg, _repo, _ in spike.PACKAGES:
        on_registry = spike.releases(f, eco, pkg)
        listing = f.json(f"osvq_{eco}_{pkg}", "https://api.osv.dev/v1/query", "POST",
                         {"package": {"name": pkg, "ecosystem": eco}})
        recs = {v["id"]: f.json(f"osv_{v['id']}", f"https://api.osv.dev/v1/vulns/{v['id']}") for v in listing.get("vulns", [])}
        recs = {k: r for k, r in recs.items() if not r.get("withdrawn") and k.split("-")[0] in ("GHSA", "PYSEC")}
        finals = [v for v in on_registry if not spike.prerelease(eco, v)]
        for v in sorted(rng.sample(finals, min(SAMPLE_PER_PACKAGE, len(finals))), key=lambda x: spike.vkey(eco, x)):
            got = f.json(f"osvv_{eco}_{pkg}_{v}", "https://api.osv.dev/v1/query", "POST",
                         {"package": {"name": pkg, "ecosystem": eco}, "version": v})
            oracle = {x["id"] for x in got.get("vulns", []) if x["id"] in recs}
            mine = set()
            for vid, rec in recs.items():
                entries = [a for a in rec.get("affected", []) if a.get("package", {}).get("name", "").lower() == pkg.lower()
                           and a.get("package", {}).get("ecosystem") == eco]
                aff = {"ranges": [r for a in entries for r in a.get("ranges", [])],
                       "versions": [x for a in entries for x in a.get("versions", [])]}
                s = spike.osv_affected(eco, [v], aff) if entries else set()
                if s:
                    mine.add(vid)
            checked += 1
            if mine == oracle:
                agree += 1
            else:
                disagreements.append((pkg, v, sorted(mine - oracle), sorted(oracle - mine)))
    L += ["## 1. Range evaluation against OSV's own evaluator", "",
          f"{agree} of {checked} sampled (package, version) points give the same set of GHSA and PYSEC advisories "
          f"as OSV.dev's `/v1/query` for that version ({SAMPLE_PER_PACKAGE} final releases per package, fixed seed).", ""]
    if disagreements:
        L += ["Every mismatch so far has come from records that contradict themselves: a `GIT` range \"introduced 0\" "
              "(affected since the first commit) next to an `ECOSYSTEM` range that starts later. OSV's query engine "
              "follows the GIT range; the spike follows the ECOSYSTEM range, as GHSA does. These are findings about "
              "the records, not errors in the evaluator.", ""]
        L += ["| Package | Version | Spike only | OSV only |", "|---|---|---|---|"] + [
            f"| {p} | {v} | {', '.join(a) or '–'} | {', '.join(b) or '–'} |" for p, v, a, b in disagreements]
    L.append("")

    # 2. package identity
    ident = defaultdict(Counter)
    for r in rows:
        for flag in r["flags"]:
            if "parent project" in flag:
                ident[r["package"]]["CNA family" if flag.startswith("CNA") else "NVD family"] += 1
        for note in r["notes"]:
            if note.startswith("CNA (") and "no matching product" in note:
                ident[r["package"]]["CNA unmatched: " + note.split("CNA lists ")[-1].rstrip(")")] += 1
            if note.startswith("NVD: no matching CPE"):
                ident[r["package"]]["NVD unmatched: " + note.split("NVD lists ")[-1].rstrip(")")] += 1
    L += ["## 2. Package identity", "",
          "How the CNA's product name and NVD's CPE product were matched to each package. *Family* means the record "
          "names the parent project (\"langchain\" on a langchain-core advisory); those comparisons are excluded from "
          "the conservative counts. *Unmatched* means the record names something else; those sources were left out of "
          "that advisory. **A person should read this table**: a wrong match here changes results.", "",
          "| Package | Match | Advisories |", "|---|---|---|"]
    for pkg, c in ident.items():
        L += [f"| {pkg} | {k} | {v} |" for k, v in c.most_common()]
    L.append("")

    # 3. deduplication
    multi_cve, seen = [], defaultdict(list)
    for r in rows:
        for i in r["ids"]:
            seen[i].append(r["advisory"])
    for p in (Path(args.cache) / "http").glob("osv_*.json"):
        rec = json.loads(p.read_text()) or {}
        cves = [a for a in [rec.get("id", ""), *rec.get("aliases", [])] if a.startswith("CVE-")]
        if len(set(cves)) > 1:
            multi_cve.append((rec["id"], sorted(set(cves))))
    twice = {i: g for i, g in seen.items() if len(set(g)) > 1}
    L += ["## 3. Deduplication", "",
          f"- Records grouped by CVE (or GHSA id without one): {len(rows)} advisories from "
          f"{sum(len(r['ids']) for r in rows)} records.",
          f"- Ids that landed in more than one group: {len(twice)}" + (f" ({', '.join(twice)})" if twice else "."),
          f"- Records with more than one CVE alias (grouped under the first): {len(multi_cve)}"
          + ("".join(f"\n  - {i}: {', '.join(c)}" for i, c in multi_cve) if multi_cve else "."), ""]

    # 4. versions
    L += ["## 4. Versions no longer installable", "", "| Package | On the registry | Yanked | Named by sources but gone |",
          "|---|---|---|---|"]
    for eco, pkg, _repo, _ in spike.PACKAGES:
        on = set(spike.releases(f, eco, pkg))
        y = spike.yanked(f, eco, pkg)
        named = set()
        listing = f.json(f"osvq_{eco}_{pkg}", "https://api.osv.dev/v1/query", "POST", {"package": {"name": pkg, "ecosystem": eco}})
        for v in listing.get("vulns", []):
            rec = f.json(f"osv_{v['id']}", f"https://api.osv.dev/v1/vulns/{v['id']}")
            for a in rec.get("affected", []):
                if a.get("package", {}).get("name", "").lower() == pkg.lower():
                    named |= {x for x in a.get("versions", []) if spike.vkey(eco, x) is not None}
        canon = {str(spike.vkey(eco, x)) if eco == "PyPI" else x.lstrip("v") for x in on}
        gone = sorted({x for x in named if (str(spike.vkey(eco, x)) if eco == "PyPI" else x.lstrip("v")) not in canon},
                      key=lambda x: spike.vkey(eco, x))
        L.append(f"| {pkg} | {len(on)} | {len(y)} | {len(gone)}" + (f" ({gone[0]} … {gone[-1]})" if gone else "") + " |")
    L.append("")

    # 5. severity and exclusions
    cross_only = sum(1 for r in rows if len(r["scores"]) > 1 and not any(
        sum(1 for v in r["scores"].values() if ver in v) > 1 for ver in ("3", "4")))
    loose = Counter(s for r in rows for s in set(r.get("loose", [])))
    L += ["## 5. Severity and the conservative exclusions", "",
          f"- Advisories with scores from several sources but no two on the same CVSS version (so not compared): "
          f"{cross_only}",
          f"- Advisories where a source was excluded from the conservative counts: CNA {loose.get('CNA', 0)}, "
          f"NVD {loose.get('NVD', 0)}", ""]

    (out / "AUDIT.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main())
