"""Phase 0 of the security domain (docs/security/PLAN.md §5): domain profiles, git_ref evidence, per-kind policy
overrides. The clinical behaviour must not change; test_check.py and `rrsrch gate-eval` hold the gate to that."""
import pytest
from pydantic import ValidationError
from test_trust import MAINTAINER, STRICT, approve, content, failed, proposal, span
from test_trust_db import world  # noqa: F401  (a fixture)

from rrsrch.check import evaluate, gate, profiles
from rrsrch.knowledge.models import ClaimContent, GitRef
from rrsrch.trust import pipeline
from rrsrch.trust.policy import Policy

COMMIT = "0123456789abcdef0123456789abcdef01234567"
REF = {"repo_url": "https://github.com/langchain-ai/langchain", "commit": COMMIT, "tag": "langchain-core==0.2.43"}


@pytest.fixture
def security_on(monkeypatch):
    """The security features are dark by default (trust/features.py); these tests are about the features themselves."""
    monkeypatch.setenv("RRSRCH_SECURITY_FEATURES", "on")


# profiles

def test_the_clinical_profile_is_the_default_and_the_gate_is_unchanged_under_it():
    assert profiles.get("clinical") is profiles.CLINICAL
    assert gate.REPORT_SCOPE == profiles.CLINICAL.report_scope
    claims, cases = evaluate.load_cases()
    for case in cases:
        cited = [gate.CitedClaim(n, claims[n]["text"], {g: frozenset(v) for g, v in claims[n]["context"].items()})
                 for n in case["claims"]]
        assert gate.check(case["sentence"], cited).to_json() == \
            gate.check(case["sentence"], cited, profile=profiles.CLINICAL).to_json()


def test_a_policy_naming_an_unknown_profile_is_refused():
    assert Policy().profile == "clinical"
    with pytest.raises(ValidationError, match="unknown evidence profile 'security'"):
        Policy(profile="security")


# git refs

def test_git_refs_are_pinned_to_a_full_commit_on_a_public_forge():
    assert GitRef(**REF).label() == "github.com/langchain-ai/langchain@0123456789ab (in langchain-core==0.2.43?)"
    lines = GitRef(**REF | {"path": "libs/core/x.py", "start_line": 3, "end_line": 9})
    assert lines.label().startswith("github.com/langchain-ai/langchain@0123456789ab:libs/core/x.py#L3-L9")
    for bad in ({"commit": COMMIT[:12]},                                      # a short SHA can move
                {"commit": COMMIT.upper()},
                {"repo_url": "https://example.com/a/b"},                      # not a public forge
                {"repo_url": "http://github.com/a/b"},
                {"path": "../etc/passwd"}, {"path": "/abs"}, {"tag": "v1..2"},
                {"path": "a.py", "start_line": 5},                            # lines go together
                {"start_line": 1, "end_line": 2},                             # lines need a path
                {"path": "a.py", "start_line": 5, "end_line": 4}):
        with pytest.raises(ValidationError):
            GitRef(**REF | bad)


def test_adding_git_refs_leaves_span_only_content_hashes_alone():
    c = ClaimContent.model_validate(content())
    assert "git" not in str(c.canonical()) and "repo_url" not in str(c.canonical())
    both = ClaimContent.model_validate(content(evidence=[["supports", span()], ["supports", REF]]))
    assert isinstance(both.evidence[1][1], GitRef) and both.content_hash() != c.content_hash()
    again = ClaimContent.model_validate(content(evidence=[["supports", REF], ["supports", span()]]))
    assert again.content_hash() == both.content_hash()                       # evidence order is not content


def test_git_refs_need_a_policy_that_takes_them_and_never_stand_alone(security_on):
    with_ref = {"evidence": [["supports", span()], ["supports", REF]]}
    assert "evidence_kinds" in failed(proposal(**with_ref))
    takes = STRICT.model_copy(update={"allowed_evidence": ("document_span", "git_ref")})
    assert failed(proposal(policy=takes, **with_ref)) == set()
    # a commit adds to a quoted passage; it can't be the only support
    assert "min_sources" in failed(proposal(policy=takes, evidence=[["supports", REF]]))


# per-kind overrides

NOT_AFFECTED = {"kind": "not_affected", "required_reproductions": 2, "human_approval": True, "required_approvals": 2}


def test_overrides_apply_to_the_claims_they_name():
    p = Policy(required_approvals=1, kinds=("fixed_in", "not_affected"), overrides=[NOT_AFFECTED])
    assert p.for_claim("empirical", {"kind": "fixed_in"}).required_reproductions == 0
    strict = p.for_claim("empirical", {"kind": "not_affected"})
    assert (strict.required_reproductions, strict.human_approval, strict.required_approvals) == (2, True, 2)
    by_type = Policy(overrides=[{"type": "procedural", "human_approval": True}])          # type-keyed: no kinds needed
    assert by_type.for_claim("procedural", {}).human_approval and not by_type.for_claim("factual", {}).human_approval


def test_overrides_can_only_tighten():
    with pytest.raises(ValidationError, match="only tighten"):
        Policy(required_approvals=2, kinds=("x",), overrides=[{"kind": "x", "required_approvals": 1}])
    with pytest.raises(ValidationError, match="only tighten"):
        Policy(human_approval=True, kinds=("x",), overrides=[{"kind": "x", "human_approval": False}])
    with pytest.raises(ValidationError, match="names the claim kind or type"):
        Policy(overrides=[{"required_approvals": 3}])


def test_a_merge_is_judged_by_the_claims_own_rules():
    p = STRICT.model_copy(update={"kinds": ("fixed_in", "not_affected"), "overrides": (
        Policy.model_validate({"kinds": ["not_affected"], "overrides": [{"kind": "not_affected", "required_approvals": 2}]}).overrides)})
    merger = MAINTAINER
    one = [approve(2)]
    plain = proposal(policy=p, reviews=one, scope={"kind": "fixed_in"})
    assert pipeline.authorize(plain, pipeline.verify(plain)[1], merger)
    risky = proposal(policy=p, reviews=one, scope={"kind": "not_affected"})
    no = pipeline.authorize(risky, pipeline.verify(risky)[1], merger)
    assert not no and any("policy needs 2" in r for r in no.reasons)
    two = proposal(policy=p, reviews=[approve(2), approve(3)], scope={"kind": "not_affected"})
    assert pipeline.authorize(two, pipeline.verify(two)[1], merger)



# against a real Postgres

@pytest.mark.db
def test_a_merged_git_ref_is_stored_and_shown_with_its_claim(world, security_on):
    import psycopg
    from test_knowledge_api import claim_of
    from test_trust_db import PILOT
    client, h, url = world
    rules = client.get(f"/v1/repos/{PILOT}").json()["repository"]["policy"]
    body = {"repository": PILOT, "content": content() | {"evidence": [["supports", span()], ["supports", REF]]}}
    refused = client.post("/v1/merge-requests", headers=h["bot"], json=body).json()
    assert any(c["name"] == "evidence_kinds" and not c["passed"] for c in refused["checks"])

    r = client.patch(f"/v1/repos/{PILOT}", headers=h["admin"],
                     json={"policy": rules | {"allowed_evidence": ["document_span", "git_ref"]}})
    assert r.status_code == 200, r.json()
    r = client.post(f"/v1/repos/{PILOT}/claims", headers=h["bot"], json={"content": body["content"]})
    assert r.status_code == 201, r.json()
    mr = r.json()["merge_request_id"]
    client.post(f"/v1/merge-requests/{mr}/reviews", headers=h["ext"], json={"verdict": "approve"})
    r = client.post(f"/v1/merge-requests/{mr}/merge", headers=h["admin"])
    assert r.status_code == 200, r.json()
    rev = r.json()["revision_id"]
    cid = claim_of(url, rev)
    ev = client.get(f"/v1/claims/{cid}").json()["claim"]["evidence"]
    git = [e for e in ev if e["kind"] == "git_ref"]
    assert len(git) == 1 and git[0]["git"]["commit"] == COMMIT and git[0]["source_id"] is None
    assert git[0]["excerpt"].startswith("github.com/langchain-ai/langchain@0123456789ab")
    assert client.get(f"/v1/evidence/{git[0]['id']}").json()["evidence"]["git"]["tag"] == "langchain-core==0.2.43"
    with psycopg.connect(url) as c:
        assert c.execute("SELECT count(*) FROM evidence WHERE kind = 'git_ref'").fetchone()[0] == 1
    prov = client.get(f"/v1/claims/{cid}/provenance")
    assert prov.status_code == 200, prov.text
    commits = [n for n in prov.json()["nodes"] if n["kind"] == "commit"]
    assert len(commits) == 1 and commits[0]["commit"] == COMMIT
    assert not any(n["id"] == "source:None" for n in prov.json()["nodes"])


@pytest.mark.db
def test_claim_reviews_use_the_claims_own_rules(world, security_on):
    import psycopg
    from test_claim_review import reader_claim, review
    from test_trust_db import PILOT, QUOTE
    client, h, url = world
    rules = client.get(f"/v1/repos/{PILOT}").json()["repository"]["policy"]
    r = client.patch(f"/v1/repos/{PILOT}", headers=h["admin"],
                     json={"policy": rules | {"kinds": ["fixed_in", "not_affected"],
                                              "overrides": [{"kind": "not_affected", "required_reproductions": 1}]}})
    assert r.status_code == 200, r.json()
    plain, risky = reader_claim(url), reader_claim(url, text=QUOTE + " ")
    with psycopg.connect(url) as c:
        c.execute("UPDATE claims SET scope = scope || '{\"kind\": \"not_affected\"}' WHERE id = %s", (risky,))
    assert review(client, h["ext"], plain, "approve").json()["state"] == "supported"
    held = review(client, h["ext"], risky, "approve").json()
    assert held["state"] == "under_review" and held["reasons"] == ["0 independent reproduction(s), policy needs 1"]


# from the review of PR #102

def test_kind_overrides_cant_be_dodged():
    with pytest.raises(ValidationError, match="aren't in kinds"):
        Policy(overrides=[{"kind": "not_affected", "required_approvals": 3}])          # kind not declared
    p = STRICT.model_copy(update={"kinds": ("fixed_in", "not_affected")})
    assert "claim_kind" in failed(proposal(policy=p))                                  # no scope.kind
    assert "claim_kind" in failed(proposal(policy=p, scope={"kind": "not-affected"}))  # misspelt
    assert "claim_kind" not in failed(proposal(policy=p, scope={"kind": "not_affected"}))
    assert "claim_kind" not in failed(proposal())                                      # repositories without kinds


def test_matching_overrides_combine_to_the_strictest():
    p = Policy(kinds=("not_affected",), overrides=[{"type": "empirical", "required_approvals": 3},
                                                   {"kind": "not_affected", "required_approvals": 2, "human_approval": True}])
    got = p.for_claim("empirical", {"kind": "not_affected"})
    assert (got.required_approvals, got.human_approval) == (3, True)


def test_allowed_evidence_always_includes_passages():
    with pytest.raises(ValidationError, match="must include document_span"):
        Policy(allowed_evidence=("git_ref",))


def test_git_refs_have_one_spelling_and_real_tag_names():
    a = GitRef(**REF | {"repo_url": "https://GitHub.com/LangChain-AI/langchain.git/"})
    assert a.repo_url == "https://github.com/langchain-ai/langchain"
    for bad in ({"tag": "HEAD"}, {"tag": "v1@{1}"}, {"tag": "v1.lock"}, {"path": "-rf"}, {"path": ":(glob)**"},
                {"repo_url": "https://github.com/o/.."}, {"repo_url": "https://github.com/-o/r"}):
        with pytest.raises(ValidationError):
            GitRef(**REF | bad)


# the switch (trust/features.py)

def test_commit_evidence_is_refused_while_the_switch_is_off(monkeypatch):
    monkeypatch.delenv("RRSRCH_SECURITY_FEATURES", raising=False)
    takes = STRICT.model_copy(update={"allowed_evidence": ("document_span", "git_ref")})
    p = proposal(policy=takes, evidence=[["supports", span()], ["supports", REF]])
    checks = {c.name: c for c in pipeline.verify(p)[1]}
    assert not checks["evidence_kinds"].passed and "disabled on this server" in checks["evidence_kinds"].detail
    monkeypatch.setenv("RRSRCH_SECURITY_FEATURES", "operator")
    assert {c.name: c for c in pipeline.verify(p)[1]}["evidence_kinds"].passed


@pytest.mark.db
def test_security_policies_need_the_switch_and_stay_private_in_testing(world, monkeypatch):
    from test_trust_db import PILOT
    client, h, url = world
    secure = {"allowed_evidence": ["document_span", "git_ref"], "required_approvals": 0}
    new = {"slug": "rrsrch/supply-chain-test", "topic": "t", "visibility": "private", "policy": secure}

    monkeypatch.delenv("RRSRCH_SECURITY_FEATURES", raising=False)          # off: nobody
    r = client.post("/v1/repos", headers=h["admin"], json=new)
    assert r.status_code == 403 and "aren't enabled" in r.json()["error"]
    rules = client.get(f"/v1/repos/{PILOT}").json()["repository"]["policy"]
    assert client.patch(f"/v1/repos/{PILOT}", headers=h["admin"],
                        json={"policy": rules | {"kinds": ["x"]}}).status_code == 403
    assert client.post("/v1/repos", headers=h["admin"], json=new | {"policy": {"required_approvals": 0}}).status_code == 201

    monkeypatch.setenv("RRSRCH_SECURITY_FEATURES", "operator")             # operator: network admins, private only
    assert client.patch("/v1/repos/rrsrch/supply-chain-test", headers=h["admin"], json={"policy": secure}).status_code == 200
    r = client.patch("/v1/repos/rrsrch/supply-chain-test", headers=h["admin"], json={"visibility": "public"})
    assert r.status_code == 403 and "private repositories" in r.json()["error"]
    assert client.patch(f"/v1/repos/{PILOT}", headers=h["admin"],
                        json={"policy": rules | {"allowed_evidence": ["document_span", "git_ref"]}}).status_code == 403

    monkeypatch.setenv("RRSRCH_SECURITY_FEATURES", "on")                   # on: the public launch
    assert client.patch("/v1/repos/rrsrch/supply-chain-test", headers=h["admin"], json={"visibility": "public"}).status_code == 200
