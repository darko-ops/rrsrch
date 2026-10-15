"""The reconciliation spike's method (scripts/advisory_spike.py): each correction the audit depends on."""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import advisory_spike as spike  # noqa: E402

RELS = ["0.1.0", "0.2.0", "0.3.0a1", "0.3.0", "0.3.1", "1.0.0", "1.0.1", "1.1.0"]


def osv(*ranges, versions=()):
    return {"ranges": [{"type": "ECOSYSTEM", "events": e} for e in ranges], "versions": list(versions)}


def test_every_affected_entry_counts():
    # two release lines, as GHSA writes them: one entry each, combined by the caller into one ranges list
    both = osv([{"introduced": "0"}, {"fixed": "0.3.1"}], [{"introduced": "1.0.0"}, {"fixed": "1.0.1"}])
    assert spike.osv_affected("PyPI", RELS, both) == {"0.1.0", "0.2.0", "0.3.0a1", "0.3.0", "1.0.0"}
    assert spike.osv_affected("PyPI", RELS, osv([{"introduced": "0.2.0"}, {"last_affected": "0.3.0"}])) == \
        {"0.2.0", "0.3.0a1", "0.3.0"}


def test_versions_lists_are_matched_by_value_not_spelling():
    assert spike.osv_affected("PyPI", RELS, {"ranges": [], "versions": ["v0.2.0", "0.3.1"]}) == {"0.2.0", "0.3.1"}


def test_cna_ranges_in_every_shape():
    def cna(*versions, product="widget"):
        return {"affected": [{"product": product, "versions": list(versions)}]}
    s, how, fixes = spike.cna_affected("PyPI", RELS, cna({"version": ">= 0.2.0, < 1.0.1", "status": "affected"}), "widget", {"widget"})
    assert s == {"0.2.0", "0.3.0a1", "0.3.0", "0.3.1", "1.0.0"} and how == "package" and fixes == {"1.0.1"}
    s, _, fixes = spike.cna_affected("PyPI", RELS, cna({"version": "unspecified", "lessThan": "0.3.0", "status": "affected"}), "widget", {"widget"})
    assert s == {"0.1.0", "0.2.0", "0.3.0a1"} and fixes == {"0.3.0"}
    assert spike.cna_affected("PyPI", RELS, cna({"version": "n/a", "status": "affected"}), "widget", {"widget"})[0] is None
    _, how, _ = spike.cna_affected("PyPI", RELS, cna({"version": "< 0.2.0", "status": "affected"}, product="widgets-org/widget"),
                                   "widget-core", {"widget-core"})
    assert how.startswith("no matching product")
    spike.FAMILY["widget-core"] = {"widget"}
    try:
        _, how, _ = spike.cna_affected("PyPI", RELS, cna({"version": "< 0.2.0", "status": "affected"}), "widget-core", {"widget-core"})
        assert how == "family"
    finally:
        del spike.FAMILY["widget-core"]


def test_nvd_cpe_ranges_exact_versions_and_unparseable_bounds():
    def cve(*matches):
        return {"configurations": [{"nodes": [{"cpeMatch": [dict(m, vulnerable=True) for m in matches]}]}]}
    s, how, fixes, exact = spike.nvd_affected("PyPI", RELS, cve(
        {"criteria": "cpe:2.3:a:acme:widget:*:*:*:*:*:python:*:*", "versionStartIncluding": "0.2.0", "versionEndExcluding": "1.0.0"}),
        "widget", {"widget"})
    assert s == {"0.2.0", "0.3.0a1", "0.3.0", "0.3.1"} and fixes == {"1.0.0"} and not exact
    s, _, _, exact = spike.nvd_affected("PyPI", RELS, cve({"criteria": "cpe:2.3:a:acme:widget:0.3.1:*:*:*:*:*:*:*"}), "widget", {"widget"})
    assert s == {"0.3.1"} and exact                       # only the version a reporter tested
    s, _, _, _ = spike.nvd_affected("PyPI", RELS, cve({"criteria": "cpe:2.3:a:acme:widget:0.3.0:a1:*:*:*:*:*:*"}), "widget", {"widget"})
    assert s == {"0.3.0a1"}                               # the update field is part of the version
    s, how, _, _ = spike.nvd_affected("PyPI", RELS, cve(
        {"criteria": "cpe:2.3:a:acme:widget:*:*:*:*:*:*:*:*", "versionEndExcluding": "1.52.10-stable"}), "widget", {"widget"})
    assert s is None and "unparseable" in how


def test_pre_releases_and_semver_order():
    assert spike.prerelease("PyPI", "0.3.0a1") and spike.prerelease("PyPI", "1.0.0.dev2") and not spike.prerelease("PyPI", "1.0.0.post1")
    assert spike.vkey("npm", "1.2.0-beta.1") < spike.vkey("npm", "1.2.0") < spike.vkey("npm", "1.10.0")
    assert spike.prerelease("npm", "1.2.0-rc.1") and not spike.prerelease("npm", "1.2.0")


def test_only_installable_final_releases_change_the_answer():
    on = {"0.2.0", "0.3.0", "1.0.0"}
    assert spike.installable("PyPI", "0.3.0", on, gone=set())
    assert not spike.installable("PyPI", "0.3.0", on, gone={"0.3.0"})      # yanked
    assert not spike.installable("PyPI", "0.3.1", on, gone=set())          # no longer on the registry
    assert not spike.installable("PyPI", "0.3.0a1", on | {"0.3.0a1"}, gone=set())
    assert spike.why_harmless("PyPI", {"0.3.1", "0.3.0"}, on, {"0.3.0"}) == ["1 no longer on the registry", "1 yanked"]


def test_severity_is_compared_within_one_cvss_version():
    pytest.importorskip("cvss")
    assert spike.score("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H") == ("3", 9.8)
    assert spike.score("CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N")[0] == "4"
    assert spike.cna_score({"metrics": [{"cvssV4_0": {"baseScore": 9.3}}, {"cvssV3_1": {"baseScore": 8.1}}]}) == {"4": 9.3, "3": 8.1}


def test_cherry_picks_count_as_shipped(tmp_path):
    def git(*a):
        return subprocess.run(["git", "-C", str(tmp_path / "r"), *a], check=True, capture_output=True, text=True).stdout.strip()
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path / "r")], check=True)
    git("config", "user.email", "t@example.org"); git("config", "user.name", "t")
    git("commit", "-q", "--allow-empty", "-m", "start")
    git("checkout", "-q", "-b", "release")
    git("checkout", "-q", "main")
    git("commit", "-q", "--allow-empty", "-m", "Fix SSRF in the URL loader (#42)")
    fix = git("rev-parse", "HEAD")
    git("checkout", "-q", "release")
    git("commit", "-q", "--allow-empty", "-m", "Fix SSRF in the URL loader (#42) (cherry picked)")
    git("tag", "v1.0.1")
    git("checkout", "-q", "main")
    git("commit", "-q", "--allow-empty", "-m", "unrelated")
    git("tag", "v2.0.0")
    repos = spike.Repos(tmp_path)
    repos.tags["o/r"] = set(git("tag").split())
    (tmp_path / "o__r").symlink_to(tmp_path / "r")
    assert not repos.ancestor("o/r", fix, "v1.0.1")
    assert repos.cherry_picked("o/r", fix, "v1.0.1")
    assert repos.ancestor("o/r", fix, "v2.0.0")
    assert repos.tag_for("o/r", "widget", "1.0.1") == "v1.0.1"


def test_offline_refuses_anything_outside_the_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(spike, "OFFLINE", True)
    f = spike.Fetch(tmp_path)
    with pytest.raises(spike.NotInSnapshot):
        f.json("osv_GHSA-xxxx", "https://api.osv.dev/v1/vulns/GHSA-xxxx")
    (tmp_path / "osv_GHSA-xxxx.json").write_text('{"id": "GHSA-xxxx"}')
    assert f.json("osv_GHSA-xxxx", "https://api.osv.dev/v1/vulns/GHSA-xxxx") == {"id": "GHSA-xxxx"}
