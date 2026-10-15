"""Advisory reconciliation spike (docs/security/PLAN.md §5.4, run before phase 0).

For ten packages, every published advisory is compared across the sources that state an affected range, on the
package's actual releases:

  GHSA   GitHub's reviewed advisory (OSV format, from api.osv.dev)
  PYSEC  the PyPA advisory database (OSV format), PyPI only
  CNA    the CVE record's CNA container (cveawg.mitre.org), matched to the package by product name
  NVD    NVD's CPE configurations (the yearly JSON 2.0 feeds), matched by CPE product

Two sources agree on a range when they mark exactly the same released versions affected; comparing release sets
sidesteps how each source spells a range. Also compared: first fixed version, CVSS base score (and band), and
whether GHSA's fix commit is an ancestor of the first fixed release's tag (git merge-base on a commits-only clone).
KEV listing and an unenriched NVD record are flags. The rules lean toward `couldnt_match` over calling a source
wrong. This is a spike: no snapshots, no ledger writes. Responses are cached under --cache.

Its output names packages and possible errors in their advisories, so it is written OUTSIDE the repository (which
is public) until each lead is checked and maintainers have had notice (docs/security/PLAN.md §8, phase 4).

  uv run --with cvss python scripts/advisory_spike.py --cache /tmp/spike --out ~/rrsrch-private/security-spike
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import httpx
from packaging.version import InvalidVersion, Version

PACKAGES = [  # (ecosystem, package, github repo, NVD/CNA product names that mean this package)
    ("PyPI", "langchain", "langchain-ai/langchain", {"langchain"}),
    ("PyPI", "langchain-core", "langchain-ai/langchain", {"langchain-core", "langchain_core"}),
    ("PyPI", "langchain-community", "langchain-ai/langchain", {"langchain-community", "langchain_community"}),
    ("PyPI", "llama-index-core", "run-llama/llama_index", {"llama-index-core", "llama_index_core"}),
    ("PyPI", "litellm", "BerriAI/litellm", {"litellm"}),
    ("PyPI", "vllm", "vllm-project/vllm", {"vllm"}),
    ("PyPI", "chromadb", "chroma-core/chroma", {"chromadb", "chroma"}),
    ("PyPI", "mcp", "modelcontextprotocol/python-sdk", {"mcp", "python-sdk", "mcp-python-sdk"}),
    ("npm", "@modelcontextprotocol/sdk", "modelcontextprotocol/typescript-sdk",
     {"@modelcontextprotocol/sdk", "typescript-sdk", "sdk", "mcp-typescript-sdk"}),   # the CNA's and NVD's names
    ("npm", "@langchain/community", "langchain-ai/langchainjs", {"@langchain/community", "community"}),
]
# Product names that name the family, not this package (e.g. "langchain" on a langchain-core advisory)
FAMILY = {"langchain-core": {"langchain"}, "langchain-community": {"langchain"}, "llama-index-core": {"llama_index", "llama-index", "llamaindex"},
          "@langchain/community": {"langchainjs", "langchain"}}
UA = {"User-Agent": "rrsrch-advisory-spike/0.1 (+https://rrsrch.com)"}
OFFLINE = False       # --offline: everything must come from the snapshot; any network access is an error


class NotInSnapshot(RuntimeError):
    pass
norm = lambda s: re.sub(r"[^a-z0-9@/]+", "-", str(s or "").lower()).strip("-")


class Fetch:
    def __init__(self, cache: Path):
        self.cache = cache
        cache.mkdir(parents=True, exist_ok=True)
        self.http = httpx.Client(headers=UA, timeout=60, follow_redirects=True)
        self.last_nvd = 0.0

    def json(self, key: str, url: str, method="GET", body=None, nvd=False, tries=6):
        f = self.cache / (re.sub(r"[^A-Za-z0-9._-]+", "_", key) + ".json")
        if f.exists():
            return json.loads(f.read_text())
        if OFFLINE:
            raise NotInSnapshot(f"{key} is not in the snapshot")
        for i in range(tries):
            if nvd:                                         # 5 requests / 30 s without a key
                time.sleep(max(0, 6.5 - (time.time() - self.last_nvd)))
                self.last_nvd = time.time()
            try:
                r = self.http.request(method, url, json=body)
            except httpx.HTTPError:
                time.sleep(5 * (i + 1)); continue
            if r.status_code == 404:
                data = None
                break
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(10 * (i + 1)); continue
            r.raise_for_status()
            data = json.loads(r.text, strict=False)
            break
        else:
            return {"_unavailable": True}
        f.write_text(json.dumps(data))
        return data

    def cached(self, key: str, compute):
        """A non-HTTP lookup (e.g. gh api), cached like a response so a snapshot replays it."""
        f = self.cache / (re.sub(r"[^A-Za-z0-9._-]+", "_", key) + ".json")
        if f.exists():
            return json.loads(f.read_text())
        if OFFLINE:
            raise NotInSnapshot(f"{key} is not in the snapshot")
        data = compute()
        f.write_text(json.dumps(data))
        return data


# --- NVD: the yearly bulk feeds (same records as the API, without its 5-requests-per-30-seconds limit) ----------

_NVD_YEARS: dict[str, dict] = {}


def nvd_record(f: Fetch, cve_id: str) -> dict:
    year = cve_id.split("-")[1]
    if year not in _NVD_YEARS:
        import gzip
        path = f.cache / f"nvdfeed_{year}.json.gz"
        if not path.exists() and OFFLINE:
            raise NotInSnapshot(f"NVD feed {year} is not in the snapshot")
        if not path.exists():
            r = f.http.get(f"https://nvd.nist.gov/feeds/json/cve/2.0/nvdcve-2.0-{year}.json.gz", timeout=600)
            if r.status_code != 200:
                _NVD_YEARS[year] = {}
            else:
                path.write_bytes(r.content)
        if path.exists():
            feed = json.loads(gzip.decompress(path.read_bytes()))
            _NVD_YEARS[year] = {v["cve"]["id"]: v for v in feed.get("vulnerabilities", [])}
    if not _NVD_YEARS[year]:   # feed unavailable: fall back to the API
        return f.json(f"nvd_{cve_id}", f"https://services.nvd.nist.gov/rest/json/cves/2.0?cveId={cve_id}", nvd=True)
    got = _NVD_YEARS[year].get(cve_id)
    return {"vulnerabilities": [got]} if got else {"vulnerabilities": []}


# --- versions -------------------------------------------------------------------------------------------------------

def vkey(eco: str, v: str):
    if eco == "PyPI":
        try:
            return Version(v)
        except InvalidVersion:
            return None
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?", v or "")
    if not m:
        return None
    pre = m.group(4)
    # semver: a prerelease sorts before its release
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), 0 if pre else 1,
            tuple((0, int(p)) if p.isdigit() else (1, p) for p in (pre or "").split(".")) if pre else ())


def yanked(f: Fetch, eco: str, pkg: str) -> set[str]:
    """PyPI releases whose every file is yanked (installable only when pinned exactly; pip skips them otherwise)."""
    if eco != "PyPI":
        return set()
    d = f.json(f"pypi_{pkg}", f"https://pypi.org/pypi/{pkg}/json")
    return {v for v, files in d["releases"].items() if files and all(x.get("yanked") for x in files)}


def releases(f: Fetch, eco: str, pkg: str) -> list[str]:
    if eco == "PyPI":
        d = f.json(f"pypi_{pkg}", f"https://pypi.org/pypi/{pkg}/json")
        vs = [v for v, files in d["releases"].items() if files]
    else:
        d = f.json(f"npm_{pkg}", f"https://registry.npmjs.org/{pkg.replace('/', '%2F')}")
        vs = list(d["versions"])
    return sorted([v for v in vs if vkey(eco, v) is not None], key=lambda v: vkey(eco, v))


def osv_affected(eco: str, rels: list[str], affected: dict) -> set[str] | None:
    """Released versions an OSV `affected` entry marks affected: its ECOSYSTEM/SEMVER ranges, else `versions`."""
    out: set[str] = set()
    ranges = [r for r in affected.get("ranges", []) if r.get("type") in ("ECOSYSTEM", "SEMVER")]
    for r in ranges:
        lo = hi = None
        incl = False
        spans = []
        for ev in r.get("events", []):
            if "introduced" in ev:
                lo = ev["introduced"]
            elif "fixed" in ev or "last_affected" in ev:
                hi, incl = ev.get("fixed") or ev.get("last_affected"), "last_affected" in ev
                spans.append((lo, hi, incl)); lo = None
        if lo is not None:
            spans.append((lo, None, False))
        for lo, hi, incl in spans:
            klo = None if lo in (None, "0") else vkey(eco, lo)
            khi = None if hi is None else vkey(eco, hi)
            if (lo not in (None, "0") and klo is None) or (hi is not None and khi is None):
                return None
            for v in rels:
                k = vkey(eco, v)
                if (klo is None or k >= klo) and (khi is None or (k <= khi if incl else k < khi)):
                    out.add(v)
    if not ranges:
        if not affected.get("versions"):
            return None
        by_key = {str(vkey(eco, r)): r for r in rels}
        out = {by_key[str(vkey(eco, v))] for v in affected["versions"] if vkey(eco, v) is not None and str(vkey(eco, v)) in by_key}
    return out


def fixed_versions(affected: dict) -> set[str]:
    return {ev["fixed"] for r in affected.get("ranges", []) if r.get("type") in ("ECOSYSTEM", "SEMVER")
            for ev in r.get("events", []) if "fixed" in ev}


def expr_affected(eco: str, rels: list[str], expr: str) -> set[str] | None:
    """'>= 0.1.0, < 0.2.43' style (GitHub as CNA), or a single version."""
    conds = []
    for part in [p.strip() for p in expr.split(",") if p.strip()]:
        m = re.match(r"^(>=|<=|>|<|=|==)?\s*v?([0-9][^\s]*)$", part)
        if not m:
            return None
        k = vkey(eco, m.group(2))
        if k is None:
            return None
        conds.append((m.group(1) or "==", k))
    ops = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, "<": lambda a, b: a < b,
           "=": lambda a, b: a == b, "==": lambda a, b: a == b}
    return {v for v in rels if all(ops[o](vkey(eco, v), k) for o, k in conds)}


def cna_affected(eco, rels, cna: dict, pkg: str, products: set[str]):
    """(released versions affected, how it matched) from the CNA container, or (None, reason)."""
    entries = cna.get("affected") or []
    names = {norm(p) for p in products} | {norm(pkg)}
    fam = {norm(p) for p in FAMILY.get(pkg, set())}
    match, how = [], None
    for e in entries:
        cands = {norm(e.get("packageName")), norm(e.get("product")), norm(str(e.get("product", "")).split("/")[-1])}
        if cands & names:
            match.append(e); how = how or "package"
        elif cands & fam:
            match.append(e); how = how or "family"
    if not match:
        prods = sorted({str(e.get("product")) for e in entries})
        return None, f"no matching product (CNA lists {', '.join(prods) or 'nothing'})", set()
    out: set[str] = set()
    fixes: set[str] = set()
    for e in match:
        for v in e.get("versions") or []:
            if v.get("status") != "affected":
                continue
            ver = str(v.get("version", "")).strip()
            lt, le = v.get("lessThan"), v.get("lessThanOrEqual")
            if lt and lt != "*":
                fixes.add(lt)
            for m in re.finditer(r"<\s*(?!=)\s*v?([0-9][^\s,]*)", ver):
                fixes.add(m.group(1))
            if lt or le:
                lo = None if ver.lower() in ("", "0", "*", "unspecified", "n/a", "0.0.0") else vkey(eco, ver)
                hi = vkey(eco, lt or le) if (lt or le) not in ("*",) else None
                if (lt or le) not in ("*",) and hi is None:
                    return None, f"unparseable bound {lt or le!r}", set()
                if lo is None and ver.lower() not in ("", "0", "*", "unspecified", "n/a", "0.0.0"):
                    return None, f"unparseable version {ver!r}", set()
                out |= {r for r in rels if (lo is None or vkey(eco, r) >= lo)
                        and (hi is None or (vkey(eco, r) < hi if lt else vkey(eco, r) <= hi))}
            elif ver.lower() in ("n/a", "unspecified", "*", ""):
                return None, "version given as n/a", set()
            else:
                got = expr_affected(eco, rels, ver)
                if got is None:
                    return None, f"unparseable version {ver!r}", set()
                out |= got
    return out, how, fixes


def nvd_affected(eco, rels, cve: dict, pkg: str, products: set[str]):
    names = {norm(p).replace("@", "").replace("/", "-") for p in products} | {norm(pkg).replace("@", "").replace("/", "-")}
    fam = {norm(p) for p in FAMILY.get(pkg, set())}
    out, how, seen, fixes, exact = set(), None, set(), set(), []
    for conf in cve.get("configurations") or []:
        for node in conf.get("nodes", []):
            for m in node.get("cpeMatch", []):
                if not m.get("vulnerable"):
                    continue
                parts = m["criteria"].split(":")
                product, version = norm(parts[4]), parts[5]
                if version not in ("*", "-") and parts[6] not in ("*", "-", ""):
                    version += parts[6]          # CPE keeps a pre-release in the update field: 0.11.1 + rc0
                seen.add(f"{parts[3]}:{parts[4]}")
                if product in names:
                    how = how or "package"
                elif product in fam:
                    how = how or "family"
                else:
                    continue
                exact.append(version not in ("*", "-"))
                if m.get("versionEndExcluding"):
                    fixes.add(m["versionEndExcluding"])
                if version not in ("*", "-"):
                    k = vkey(eco, version.replace("\\", ""))
                    if k is None:
                        return None, f"unparseable CPE version {version!r}", set(), False
                    out |= {r for r in rels if k is not None and vkey(eco, r) == k}
                    continue
                raw = {o: m[f] for o, f in (("ge", "versionStartIncluding"), ("gt", "versionStartExcluding"),
                                             ("le", "versionEndIncluding"), ("lt", "versionEndExcluding")) if m.get(f)}
                b = {o: vkey(eco, v) for o, v in raw.items()}
                if any(k is None for k in b.values()):
                    return None, f"unparseable CPE bound ({', '.join(f'{o} {v}' for o, v in raw.items())})", set(), False
                out |= {r for r in rels if all((
                    "ge" not in b or vkey(eco, r) >= b["ge"], "gt" not in b or vkey(eco, r) > b["gt"],
                    "le" not in b or vkey(eco, r) <= b["le"], "lt" not in b or vkey(eco, r) < b["lt"]))}
    if how is None:
        return None, (f"no matching CPE (NVD lists {', '.join(sorted(seen))})" if seen else "no CPE configurations"), set(), False
    return out, how, fixes, bool(exact) and all(exact)


# --- severity -------------------------------------------------------------------------------------------------------

def score(vector: str) -> tuple[str, float] | None:
    from cvss import CVSS3, CVSS4          # only needed for scoring: `uv run --with cvss`
    try:
        if vector.startswith("CVSS:4"):
            return ("4", float(CVSS4(vector).base_score))
        if vector.startswith("CVSS:3"):
            return ("3", float(CVSS3(vector).scores()[0]))
    except Exception:
        return None
    return None


def band(s: float) -> str:
    return "none" if s == 0 else "low" if s < 4 else "medium" if s < 7 else "high" if s < 9 else "critical"


def osv_score(rec: dict) -> dict[str, float]:
    out = {}
    for s in rec.get("severity") or []:
        if s.get("type") in ("CVSS_V3", "CVSS_V4") and (got := score(s["score"])):
            out.setdefault(got[0], got[1])
    return out


def cna_score(cna: dict) -> dict[str, float]:
    out = {}
    for m in cna.get("metrics") or []:
        for k, v in (("cvssV3_1", "3"), ("cvssV3_0", "3"), ("cvssV4_0", "4")):
            if k in m and m[k].get("baseScore") is not None:
                out.setdefault(v, float(m[k]["baseScore"]))
    return out


def nvd_score(cve: dict) -> dict[str, float]:
    """NVD's own (Primary) scores, by CVSS major version."""
    out = {}
    mets = cve.get("metrics") or {}
    for k, v in (("cvssMetricV31", "3"), ("cvssMetricV30", "3"), ("cvssMetricV40", "4")):
        for m in mets.get(k, []):
            if m.get("type") == "Primary":
                out.setdefault(v, float(m["cvssData"]["baseScore"]))
    return out


# --- fix presence ---------------------------------------------------------------------------------------------------

class Repos:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.tags: dict[str, set[str]] = {}

    def path(self, repo: str) -> Path:
        p = self.root / repo.replace("/", "__")
        if not p.exists() and OFFLINE:
            raise NotInSnapshot(f"git clone of {repo} is not in the snapshot")
        if not p.exists():   # commits and tags only: enough for ancestry
            subprocess.run(["git", "clone", "-q", "--bare", "--filter=tree:0", f"https://github.com/{repo}.git", str(p)], check=True)
        if repo not in self.tags:
            self.tags[repo] = set(subprocess.run(["git", "-C", str(p), "tag"], capture_output=True, text=True).stdout.split())
        return p

    def tag_for(self, repo: str, pkg: str, version: str) -> str | None:
        self.path(repo)
        short = pkg.split("/")[-1]
        for t in (f"v{version}", version, f"{pkg}=={version}", f"{pkg}@{version}", f"{short}=={version}",
                  f"{pkg}-v{version}", f"{pkg}-{version}", f"{short}-v{version}", f"{short}@{version}", f"{short}-{version}"):
            if t in self.tags[repo]:
                return t
        return None

    def has(self, repo: str, sha: str) -> bool:
        p = self.path(repo)
        if subprocess.run(["git", "-C", str(p), "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True).returncode == 0:
            return True
        if OFFLINE:
            return False
        return subprocess.run(["git", "-C", str(p), "fetch", "-q", "--filter=tree:0", "origin", sha],
                              capture_output=True).returncode == 0

    def ancestor(self, repo: str, sha: str, tag: str) -> bool:
        p = self.path(repo)
        return subprocess.run(["git", "-C", str(p), "merge-base", "--is-ancestor", sha, f"refs/tags/{tag}"]).returncode == 0

    def cherry_picked(self, repo: str, sha: str, tag: str) -> str | None:
        """A commit in the tag's history that carries the same change: same subject, or the same "(#PR)" number,
        within a year of the original (release branches get fixes as cherry-picks with new SHAs)."""
        p = self.path(repo)
        subj = subprocess.run(["git", "-C", str(p), "log", "-1", "--format=%s%x00%ct", sha], capture_output=True,
                              text=True).stdout.strip().split("\0")
        if len(subj) != 2:
            return None
        subject, when = subj[0], int(subj[1])
        pr = re.search(r"\(#(\d+)\)\s*$", subject)
        base = re.sub(r"\s*\(#\d+\)\s*$", "", subject).strip()
        log = subprocess.run(["git", "-C", str(p), "log", f"--since={when - 86400 * 365}", "--format=%H%x00%s",
                              f"refs/tags/{tag}"], capture_output=True, text=True).stdout
        for line in log.splitlines():
            h, _, s = line.partition("\0")
            if (base and re.sub(r"\s*\(#\d+\)\s*$", "", s).strip() == base) or (pr and f"(#{pr.group(1)})" in s) \
                    or (pr and f"#{pr.group(1)}" in s and "cherry" in s.lower()):
                return h
        return None


def fix_commits(f: Fetch, rec: dict, repo: str) -> list[tuple[str, str]]:
    """(sha, how) from the advisory's references: commit URLs, or a pull request's merge commit (via gh)."""
    out = []
    for ref in rec.get("references") or []:
        url = ref.get("url", "")
        m = re.match(rf"https://github\.com/{re.escape(repo)}/commit/([0-9a-f]{{7,40}})", url, re.I)
        if m:
            out.append((m.group(1), "commit"))
            continue
        m = re.match(rf"https://github\.com/{re.escape(repo)}/pull/(\d+)", url, re.I)
        if m:
            def look(n=m.group(1)):
                r = subprocess.run(["gh", "api", f"repos/{repo}/pulls/{n}", "--jq", ".merge_commit_sha + \" \" + (.merged|tostring)"],
                                   capture_output=True, text=True)
                return r.stdout.split() if r.returncode == 0 else []
            parts = f.cached(f"ghpr_{repo}_{m.group(1)}", look)
            if len(parts) == 2 and parts[1] == "true":
                out.append((parts[0], f"PR #{m.group(1)}"))
    return list(dict.fromkeys(out))


# --- reconcile ------------------------------------------------------------------------------------------------------

def prerelease(eco: str, v: str) -> bool:
    k = vkey(eco, v)
    return (k.is_prerelease or k.is_devrelease) if eco == "PyPI" else k[3] == 0


def installable(eco: str, v: str, on_registry: set[str], gone: set[str]) -> bool:
    """A final release someone can install today: on the registry, not yanked, not a pre-release."""
    return v in on_registry and v not in gone and not prerelease(eco, v)


def why_harmless(eco: str, vs: set[str], on_registry: set[str], gone: set[str]) -> list[str]:
    out = Counter("no longer on the registry" if v not in on_registry else "yanked" if v in gone else
                  "pre-release" for v in vs)
    return [f"{n} {k}" for k, n in sorted(out.items(), key=lambda kv: (-kv[1], kv[0]))]   # stable across runs


def describe(eco, rels, s: set[str]) -> str:
    if not s:
        return "none"
    vs = sorted(s, key=lambda v: vkey(eco, v))
    return f"{len(vs)} releases ({vs[0]} … {vs[-1]})"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="/tmp/rrsrch-advisory-spike")
    ap.add_argument("--out", required=True, help="a directory outside the repository")
    ap.add_argument("--no-git", action="store_true")
    ap.add_argument("--export-sets", action="store_true",
                    help="also write sets.json: every source's affected versions per advisory, as runs over each "
                         "package's version list (for the demo)")
    ap.add_argument("--offline", action="store_true",
                    help="use only the snapshot in --cache; any lookup that isn't there is an error")
    args = ap.parse_args()
    global OFFLINE
    OFFLINE = args.offline
    f = Fetch(Path(args.cache) / "http")
    repos = Repos(Path(args.cache) / "git")
    kev = {v["cveID"]: v["dateAdded"] for v in f.json("kev", "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json")["vulnerabilities"]}
    rows = []
    exports: dict[str, dict] = {}
    for eco, pkg, repo, products in PACKAGES:
        rels = releases(f, eco, pkg)
        listing = f.json(f"osvq_{eco}_{pkg}", "https://api.osv.dev/v1/query", "POST", {"package": {"name": pkg, "ecosystem": eco}})
        ids = [v["id"] for v in listing.get("vulns", [])]
        # one row per advisory: group GHSA / PYSEC records by their CVE (or GHSA id when there is no CVE)
        groups: dict[str, dict] = {}
        for vid in ids:
            rec = f.json(f"osv_{vid}", f"https://api.osv.dev/v1/vulns/{vid}")
            if rec.get("withdrawn"):
                continue
            cve = next((a for a in [vid, *rec.get("aliases", [])] if a.startswith("CVE-")), None)
            key = cve or next((a for a in [vid, *rec.get("aliases", [])] if a.startswith("GHSA-")), vid)
            g = groups.setdefault(key, {"cve": cve, "recs": {}})
            g["recs"]["GHSA" if vid.startswith("GHSA-") else "PYSEC" if vid.startswith("PYSEC-") else vid.split("-")[0]] = rec
        # the versions to compare on: what the registry lists now, plus every version a source names (registries
        # lose releases: litellm's 1.15-1.53 are gone from PyPI, but advisories and NVD still name them)
        named = {v for g in groups.values() for rec in g["recs"].values() for a in rec.get("affected", [])
                 if a.get("package", {}).get("name", "").lower() == pkg.lower() for v in a.get("versions", [])}
        named |= {ev.get(k) for g in groups.values() for rec in g["recs"].values() for a in rec.get("affected", [])
                  if a.get("package", {}).get("name", "").lower() == pkg.lower() for r in a.get("ranges", [])
                  for ev in r.get("events", []) for k in ("fixed", "last_affected") if ev.get(k)}
        on_registry = set(rels)
        gone = yanked(f, eco, pkg)
        # one spelling per version: "v0.1.11" (a git tag some records list) is 0.1.11
        canon = {}
        for v in list(rels) + sorted(x for x in named if x):
            k = vkey(eco, v)
            if k is not None:
                canon.setdefault(str(k) if eco == "PyPI" else v.lstrip("v"), v if v in on_registry else v.lstrip("v"))
        rels = sorted(set(canon.values()), key=lambda v: vkey(eco, v))
        print(f"{pkg}: {len(groups)} advisories, {len(on_registry)} releases on the registry, {len(rels)} versions compared",
              file=sys.stderr)
        index = {v: i for i, v in enumerate(rels)}
        exports[pkg] = {"ecosystem": eco, "repo": repo, "versions": rels, "on_registry": sorted(on_registry & set(rels)),
                        "yanked": sorted(gone), "advisories": {}}

        def runs(vs: set[str]) -> list[list[int]]:
            out: list[list[int]] = []
            for i in sorted(index[v] for v in vs):
                if out and out[-1][1] == i - 1:
                    out[-1][1] = i
                else:
                    out.append([i, i])
            return out
        for key, g in sorted(groups.items()):
            row = {"ecosystem": eco, "package": pkg, "advisory": key, "ids": sorted({r["id"] for r in g["recs"].values()}),
                   "sources": {}, "flags": [], "notes": []}
            sets, fixes, scores = {}, {}, {}
            for name, rec in g["recs"].items():
                # a record can list the package more than once (one entry per release line): take them all
                entries = [a for a in rec.get("affected", []) if a.get("package", {}).get("name", "").lower() == pkg.lower()
                           and a.get("package", {}).get("ecosystem") == eco]
                aff = {"ranges": [r for a in entries for r in a.get("ranges", [])],
                       "versions": [v for a in entries for v in a.get("versions", [])]} if entries else None
                if not aff:
                    row["notes"].append(f"{name} has no entry for {pkg}")
                    continue
                s = osv_affected(eco, rels, aff)
                if s is None:
                    row["notes"].append(f"{name} range couldn't be evaluated")
                else:
                    sets[name] = s
                fx = fixed_versions(aff)
                fixes[name] = sorted(fx, key=lambda v: vkey(eco, v) or vkey(eco, "0"))[0] if fx else None
                if (sc := osv_score(rec)) :
                    scores[name] = sc
                row["sources"][name] = {"affected": describe(eco, rels, s) if s is not None else "?", "fixed": fixes[name], "cvss": scores.get(name)}
            if g["cve"]:
                cverec = f.json(f"cve_{g['cve']}", f"https://cveawg.mitre.org/api/cve/{g['cve']}")
                if cverec and not cverec.get("_unavailable"):
                    cna = cverec["containers"]["cna"]
                    row["cna"] = cverec["cveMetadata"].get("assignerShortName")
                    s, how, cfix = cna_affected(eco, rels, cna, pkg, products)
                    if s is None:
                        row["notes"].append(f"CNA ({row['cna']}): {how}")
                    else:
                        sets["CNA"] = s
                        if how == "family":
                            row["flags"].append("CNA names the parent project, not the package")
                            row.setdefault("loose", []).append("CNA")
                        fixes["CNA"] = min(cfix, key=lambda v: vkey(eco, v) or vkey(eco, "0")) if cfix and all(vkey(eco, v) for v in cfix) else None
                    if (sc := cna_score(cna)) :
                        scores["CNA"] = sc
                    row["sources"]["CNA"] = {"affected": describe(eco, rels, s) if s is not None else "?", "fixed": fixes.get("CNA"), "cvss": scores.get("CNA")}
                nvd = nvd_record(f, g["cve"])
                if nvd.get("_unavailable"):
                    row["notes"].append("NVD unavailable during the run")
                elif nvd.get("vulnerabilities"):
                    cve = nvd["vulnerabilities"][0]["cve"]
                    row["nvd_status"] = cve.get("vulnStatus")
                    if not cve.get("configurations"):
                        row["flags"].append(f"NVD not enriched ({cve.get('vulnStatus')})")
                    s, how, nfix, exact_only = nvd_affected(eco, rels, cve, pkg, products)
                    if exact_only:
                        row["flags"].append("NVD lists exact versions only")
                        row.setdefault("loose", []).append("NVD")
                    if s is None:
                        if cve.get("configurations"):
                            row["notes"].append(f"NVD: {how}")
                    else:
                        sets["NVD"] = s
                        if how == "family":
                            row["flags"].append("NVD's CPE names the parent project, not the package")
                            row.setdefault("loose", []).append("NVD")
                        fixes["NVD"] = min(nfix, key=lambda v: vkey(eco, v) or vkey(eco, "0")) if nfix and all(vkey(eco, v) for v in nfix) else None
                    if (sc := nvd_score(cve)) :
                        scores["NVD"] = sc
                    row["sources"]["NVD"] = {"affected": describe(eco, rels, s) if s is not None else "?", "fixed": fixes.get("NVD"), "cvss": scores.get("NVD")}
                if g["cve"] in kev:
                    row["flags"].append(f"KEV-listed ({kev[g['cve']]})")

            # pairwise comparisons
            conds = []
            names = sorted(sets)
            pairs = []
            for i, a in enumerate(names):
                for b in names[i + 1:]:
                    if sets[a] != sets[b]:
                        only_a, only_b = sets[a] - sets[b], sets[b] - sets[a]
                        if all(prerelease(eco, v) for v in only_a | only_b):
                            row["notes"].append(f"{a}/{b} differ only on pre-releases ({describe(eco, rels, only_a | only_b)})")
                            continue
                        shape = ("narrower" if not only_a or not only_b else
                                 "no overlap" if not (sets[a] & sets[b]) else "partial overlap")
                        # does it change the answer to "is version X affected?" for a release you can install?
                        inst_a = sorted((v for v in only_a if installable(eco, v, on_registry, gone)), key=lambda v: vkey(eco, v))
                        inst_b = sorted((v for v in only_b if installable(eco, v, on_registry, gone)), key=lambda v: vkey(eco, v))
                        pairs.append({"pair": f"{a}/{b}", "shape": shape, f"only_{a}": describe(eco, rels, only_a),
                                      f"only_{b}": describe(eco, rels, only_b),
                                      "changes_answer": bool(inst_a or inst_b),
                                      "installable": {f"{a}_affected_{b}_not": inst_a, f"{b}_affected_{a}_not": inst_b},
                                      "harmless_because": [] if inst_a or inst_b else
                                      why_harmless(eco, only_a | only_b, on_registry, gone)})
            row["range_pairs"] = pairs
            loose = set(row.get("loose", []))
            row["changes_answer"] = any(p["changes_answer"] for p in pairs)
            row["changes_answer_strict"] = any(p["changes_answer"] and not set(p["pair"].split("/")) & loose for p in pairs)
            if pairs:
                conds.append("range_disagreement")
            fx = {k: v for k, v in fixes.items() if v}
            fkeys = {k: vkey(eco, v) for k, v in fx.items()}
            if len({str(v) for v in fkeys.values()}) > 1:
                conds.append("fix_disagreement")
                lo, hi = min(fkeys.values()), max(fkeys.values())
                between = [v for v in rels if lo <= vkey(eco, v) < hi and installable(eco, v, on_registry, gone)]
                row["fix_gap"] = {"installable_between": len(between), "examples": between[:3] + between[-2:] if len(between) > 5 else between}
            # only scores of the same CVSS version are compared (4.0 and 3.1 scores aren't on one scale)
            for ver in ("3", "4"):
                vals = [v[ver] for v in scores.values() if ver in v]
                if len(vals) > 1 and (max(vals) - min(vals) >= 1.0 or len({band(v) for v in vals}) > 1):
                    conds.append("severity_disagreement")
                    break
            row["scores"] = scores
            # fix presence: GHSA's fix commits vs the tag of GHSA's first fixed version
            ghsa = g["recs"].get("GHSA")
            fixv = fixes.get("GHSA")
            if ghsa and not args.no_git:
                commits = fix_commits(f, ghsa, repo)
                if not fixv:
                    row["fix"] = "no fixed version"
                    row["flags"].append("no fixed version published")
                elif not commits:
                    row["fix"] = "no fix commit named"
                    conds.append("fix_unverified")
                else:
                    tag = repos.tag_for(repo, pkg, fixv)
                    if not tag:
                        row["fix"] = f"no tag found for {fixv}"
                        row["notes"].append(f"no release tag for {fixv} in {repo}")
                    else:
                        results = []
                        for sha, how in commits:
                            if not repos.has(repo, sha):
                                results.append((sha, how, "commit not found"))
                            else:
                                if repos.ancestor(repo, sha, tag):
                                    results.append((sha, how, "in tag"))
                                elif (twin := repos.cherry_picked(repo, sha, tag)):
                                    results.append((sha, how, f"in tag as cherry-pick {twin[:12]}"))
                                else:
                                    results.append((sha, how, "NOT in tag"))
                        row["fix"] = {"tag": tag, "commits": [{"sha": s[:12], "via": h, "result": r} for s, h, r in results]}
                        if not any(r.startswith("in tag") for _, _, r in results):
                            conds.append("fix_unverified")
            if len(sets) < 2 and not conds:
                state = "couldnt_match"
                row["notes"].append(f"only {len(sets)} source(s) gave a usable range")
            else:
                state = conds[0] if conds else "consistent"
            row["state"], row["conditions"] = state, conds
            exports[pkg]["advisories"][key] = {"ids": row["ids"], "sets": {k: runs(v) for k, v in sets.items()},
                                               "fixed": {k: v for k, v in fixes.items() if v}}
            rows.append(row)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "rows.json").write_text(json.dumps(rows, indent=1, default=str, sort_keys=True))
    summarise(rows, out)
    if args.export_sets:
        (out / "sets.json").write_text(json.dumps(exports, sort_keys=True, separators=(",", ":")))
    write_manifest(Path(args.cache), out)
    return 0


def _sha(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(cache: Path, out: Path) -> None:
    """What this run read and wrote, by hash, so a rerun with --offline against the same cache can be shown to
    give the same rows: every cached response and feed, every git ref in each clone, the script, the outputs."""
    import hashlib
    http = {p.name: _sha(p) for p in sorted((cache / "http").iterdir()) if p.is_file()}
    git = {}
    for repo in sorted((cache / "git").iterdir()) if (cache / "git").exists() else []:
        refs = subprocess.run(["git", "-C", str(repo), "for-each-ref", "--format=%(refname) %(objectname)"],
                              capture_output=True, text=True).stdout
        git[repo.name] = {"refs": len(refs.splitlines()), "refs_sha256": hashlib.sha256(refs.encode()).hexdigest()}
    manifest = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "offline": OFFLINE,
                "script_sha256": _sha(Path(__file__)), "rows_sha256": _sha(out / "rows.json"),
                "http": http, "git": git}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True))


def summarise(rows: list[dict], out: Path) -> None:
    n = len(rows)
    states = Counter(r["state"] for r in rows)
    conds = Counter(c for r in rows for c in r["conditions"])
    pairs = Counter(p["pair"] for r in rows for p in r["range_pairs"])
    compared = Counter()
    for r in rows:
        names = sorted(k for k in ("CNA", "GHSA", "NVD", "PYSEC") if r["sources"].get(k, {}).get("affected") not in (None, "?"))
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                compared[f"{a}/{b}"] += 1
    flags = Counter(re.sub(r" \(.*\)$", "", fl) for r in rows for fl in r["flags"])
    shapes = defaultdict(Counter)
    for r in rows:
        for p in r["range_pairs"]:
            shapes[p["pair"]][p["shape"]] += 1
    # the conservative count: leave out comparisons with a source that matched only by the parent project's name,
    # or NVD records that list only the exact versions a reporter tested
    strict = sum(1 for r in rows if any(not set(p["pair"].split("/")) & set(r.get("loose", [])) for p in r["range_pairs"]))
    strict_fix = sum(1 for r in rows if "fix_disagreement" in r["conditions"] and len(
        {v for k, v in ((k, x.get("fixed")) for k, x in r["sources"].items()) if v and k not in r.get("loose", [])}) > 1)
    changes = sum(1 for r in rows if r.get("changes_answer"))
    changes_strict = sum(1 for r in rows if r.get("changes_answer_strict"))
    harmless = Counter(h.split(" ", 1)[1] for r in rows for p in r["range_pairs"] if not p["changes_answer"]
                       for h in p["harmless_because"])
    harmless_pairs = sum(1 for r in rows for p in r["range_pairs"] if not p["changes_answer"])
    # which source says an installable release is NOT affected while another source (matched on the package
    # itself, with a real range) says it is: the error that leaves a scanner silent
    misses = Counter()
    for r in rows:
        loose = set(r.get("loose", []))
        missed = set()
        for p in r["range_pairs"]:
            if set(p["pair"].split("/")) & loose:
                continue
            for k, vs in p["installable"].items():
                says, _, other = k.partition("_affected_")
                if vs:
                    missed.add(other.removesuffix("_not"))
        misses.update(missed)
    fixr = Counter()
    for r in rows:
        fx = r.get("fix")
        if isinstance(fx, dict):
            res = [c["result"] for c in fx["commits"]]
            fixr["checked: a named commit is in the fixed tag" if "in tag" in res else
                 "checked: in the fixed tag only as a cherry-pick" if any(r.startswith("in tag") for r in res) else
                 "checked: no named commit is in the fixed tag"] += 1
        elif fx:
            fixr[re.sub(r" for .*", "", fx)] += 1
    by_pkg = defaultdict(Counter)
    for r in rows:
        by_pkg[r["package"]][r["state"]] += 1
    pct = lambda k, d: f"{k} ({100 * k / d:.0f}%)" if d else "0"
    L = [f"# Advisory reconciliation spike: {n} advisories, 10 packages", "",
         f"Generated by `engine/scripts/advisory_spike.py` on {time.strftime('%Y-%m-%d')}. Rows: `rows.json`.", "",
         "## States (first condition found, in the order range → fix → severity → fix presence)", "",
         "| State | Advisories |", "|---|---|"] + [f"| {s} | {pct(c, n)} |" for s, c in states.most_common()] + [
         "", "## Every condition (an advisory can have several)", "", "| Condition | Advisories |", "|---|---|"] + [
         f"| {c} | {pct(k, n)} |" for c, k in conds.most_common()] + [
         "", "## Range disagreement by source pair", "", "| Pair | Disagree | Compared |", "|---|---|---|"] + [
         f"| {p} | {pct(pairs[p], compared[p])} | {compared[p]} |" for p in sorted(compared)] + [
         "", "## How the ranges differ", "",
         "narrower: one source's range sits inside the other's; partial overlap: each has versions the other "
         "lacks; no overlap: they share no version.", "", "| Pair | narrower | partial overlap | no overlap |", "|---|---|---|---|"] + [
         f"| {p} | " + " | ".join(str(shapes[p].get(k, 0)) for k in ("narrower", "partial overlap", "no overlap")) + " |"
         for p in sorted(shapes)] + [
         "", "**Conservative counts**, leaving out comparisons with a source matched only by its parent project's "
         "name and NVD records that list only the exact versions a reporter tested:", "",
         f"- range disagreement: {pct(strict, n)}", f"- first-fixed version disagreement: {pct(strict_fix, n)}",
         "", "## Does it change the answer?", "",
         "A disagreement matters when it changes the answer to \"is version X affected?\" for a release someone can "
         "install today (on the registry, not yanked, not a pre-release).", "",
         f"- Advisories where it does: {pct(changes, n)}; conservatively {pct(changes_strict, n)}",
         f"- Differing source pairs where it doesn't: {harmless_pairs}, because the versions in question are: "
         + (", ".join(f"{k} ({v})" for k, v in harmless.most_common()) or "none"), "",
         "Advisories where a source says an installable release is **not** affected while another says it is "
         "(conservative comparisons only):", "", "| Source saying \"not affected\" | Advisories |", "|---|---|"] + [
         f"| {k} | {v} |" for k, v in misses.most_common()] + [
         "", "## Fix presence (GHSA's fix commit vs the tag of GHSA's first fixed version)", "", "| Result | Advisories |", "|---|---|"] + [
         f"| {k} | {v} |" for k, v in fixr.most_common()] + [
         "", "## Flags", "", "| Flag | Advisories |", "|---|---|"] + [f"| {k} | {v} |" for k, v in flags.most_common()] + [
         "", "## By package", "", "| Package | " + " | ".join(sorted(states)) + " |", "|---|" + "---|" * len(states)] + [
         f"| {p} | " + " | ".join(str(c.get(s, 0)) for s in sorted(states)) + " |" for p, c in by_pkg.items()]
    (out / "SUMMARY.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    sys.exit(main())
