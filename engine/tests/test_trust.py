"""The validation pipeline and merge decision, without a database."""
import hashlib
from dataclasses import replace

import pytest

from rrsrch.identity.access import Decision
from rrsrch.trust import pipeline
from rrsrch.trust.policy import Policy

TITLE = "Bone marrow MSCs versus hyaluronic acid for knee osteoarthritis"
TEXT = ("Methods: 40 patients were randomised. Results: At 12 months, WOMAC scores improved more with MSCs "
        "than with hyaluronic acid (p = 0.01), while VAS pain did not differ (p = 0.41).")
SHA = hashlib.sha256(TEXT.encode()).hexdigest()
QUOTE = "At 12 months, WOMAC scores improved more with MSCs than with hyaluronic acid (p = 0.01)"
START = TEXT.index(QUOTE)
REVIEW = pipeline.Doc("MED:2", "b" * 64, "A review of MSC trials. " * 5, is_primary=False, title="A review")
DOCS = {("MED:1", SHA): pipeline.Doc("MED:1", SHA, TEXT, True, TITLE, TEXT), ("MED:2", "b" * 64): REVIEW}
STRICT = Policy(allowed_types=("empirical",), primary_evidence_only=True, evidence_gate=True,
                required_approvals=1, human_approval=True)


def span(source="MED:1", sha=SHA, start=START, end=START + len(QUOTE)):
    return {"source_id": source, "doc_sha256": sha, "start": start, "end": end}


def content(**kw):
    base = {"repository": "rrsrch/msc-knee-oa", "type": "empirical",
            "proposition": "At 12 months, WOMAC improved more with MSCs than hyaluronic acid (p = 0.01).",
            "evidence": [["supports", span()]]}
    return base | kw


def proposal(policy=STRICT, reviews=(), head=None, **kw):
    return pipeline.Proposal(content=content(**kw), repository="rrsrch/msc-knee-oa", policy=policy, author_id=1,
                             author_org="rrsrch", author_status="active", known_sources=frozenset({"MED:1", "MED:2"}),
                             docs=DOCS, head_hash=head, reviews=tuple(reviews))


def failed(p):
    parsed, checks = pipeline.verify(p)
    return {c.name for c in checks if not c.passed}


def approve(rid, org="lab", kind="human", status="active", verdict="approve"):
    return pipeline.Review(rid, org, kind, status, verdict)


def test_a_well_supported_claim_passes_every_check():
    parsed, checks = pipeline.verify(proposal())
    assert parsed is not None and all(c.passed for c in checks)
    assert {c.kind.value for c in checks} == {"structural", "provenance", "integrity", "source", "factual"}


@pytest.mark.parametrize("change, broken", [
    ({"repository": "rrsrch/other"}, "repository"),
    ({"type": "interpretive"}, "claim_type"),
    ({"evidence": [["supports", span(source="MED:9")]]}, "sources_known"),
    ({"evidence": [["supports", span(sha="c" * 64)]]}, "spans_current"),
    ({"evidence": [["supports", span(end=len(TEXT) + 5)]]}, "spans_current"),
    ({"evidence": [["supports", span(source="MED:2", sha="b" * 64, start=0, end=10)]]}, "primary_evidence"),
    ({"parent_hash": "d" * 64}, "parent_is_head"),
])
def test_each_check_catches_its_own_problem(change, broken):
    assert broken in failed(proposal(**change))


def test_the_evidence_gate_refuses_wording_the_passage_does_not_support():
    assert "evidence_gate:numbers" in failed(proposal(proposition="At 24 months, WOMAC improved more with MSCs (p = 0.01)."))
    assert "evidence_gate:direction" in failed(proposal(proposition="MSCs reduced VAS pain more than hyaluronic acid."))
    assert not failed(proposal(policy=STRICT.model_copy(update={"evidence_gate": False}),
                               proposition="MSCs reduced VAS pain more than hyaluronic acid."))


def test_duplicate_spans_of_one_source_count_once():
    two = Policy(min_sources=2)
    dup = [["supports", span()], ["supports", span(start=0, end=10)]]
    assert "min_sources" in failed(proposal(policy=two, evidence=dup))


def test_malformed_content_stops_at_the_schema():
    parsed, checks = pipeline.verify(proposal(type="opinion"))
    assert parsed is None and [c.name for c in checks] == ["schema"] and "type" in checks[0].detail


def test_head_must_match_for_revisions():
    assert "parent_is_head" in failed(proposal(head="e" * 64))
    assert not failed(proposal(head="e" * 64, parent_hash="e" * 64))


MAINTAINER = Decision(True, "maintainer")


def decide(reviews, policy=STRICT, merger=MAINTAINER):
    p = proposal(policy=policy, reviews=reviews)
    return pipeline.authorize(p, pipeline.verify(p)[1], merger)


def test_merge_needs_an_independent_human_approval():
    assert decide([approve(2)])
    no = decide([])
    assert not no and any("approval" in r for r in no.reasons)
    assert not decide([approve(1)])                                   # the author's own approval
    assert not decide([approve(2, kind="service")])                   # policy wants a human
    assert not decide([approve(2, status="suspended")])
    other_orgs = STRICT.model_copy(update={"approvals_from_other_orgs_only": True})
    assert not decide([approve(2, org="rrsrch")], policy=other_orgs)
    assert decide([approve(2, org="lab")], policy=other_orgs)


def test_objections_block_and_every_reason_is_listed():
    d = decide([approve(2), approve(3, verdict="reject")], merger=Decision(False, "contributor cannot maintain"))
    assert not d
    assert any("merger" in r for r in d.reasons) and any("reject" in r for r in d.reasons)
    p = proposal(reviews=[approve(2)], proposition="At 24 months, WOMAC improved more with MSCs (p = 0.01).")
    d = pipeline.authorize(p, pipeline.verify(p)[1], MAINTAINER)
    assert not d and any("evidence_gate" in r for r in d.reasons)


def test_papers_reporting_the_same_trial_are_one_source():
    t = {"A": frozenset({"NCT1"}), "B": frozenset({"NCT1"}), "C": frozenset({"NCT2"}), "D": frozenset({"NCT2", "NCT3"}),
         "E": frozenset({"NCT3"})}
    assert pipeline.independent_sources({"A", "B"}, t) == 1
    assert pipeline.independent_sources({"A", "C"}, t) == 2
    assert pipeline.independent_sources({"C", "D", "E"}, t) == 1          # linked through NCT2 and NCT3
    assert pipeline.independent_sources({"X", "Y"}, {}) == 2


def test_two_reports_of_one_trial_dont_meet_a_two_source_policy():
    other = pipeline.Doc("MED:3", SHA, TEXT, True, TITLE, TEXT)
    two = Policy(min_sources=2)
    ev = [["supports", span()], ["supports", span(source="MED:3")]]
    base = proposal(policy=two, evidence=ev)
    p = replace(base, docs={**DOCS, ("MED:3", SHA): other}, known_sources=frozenset({"MED:1", "MED:3"}))
    assert not failed(p)
    same_trial = replace(p, trials={"MED:1": frozenset({"NCT9"}), "MED:3": frozenset({"NCT9"})})
    assert "min_sources" in failed(same_trial)
    assert "same trial" in next(c.detail for c in pipeline.verify(same_trial)[1] if c.name == "min_sources")


def test_derivations_must_exist_and_never_loop():
    p = proposal(derived_from=[7])
    assert "derived_from_known" in failed(p)
    assert not failed(replace(p, known_claims=frozenset({7})))
    revising = replace(proposal(derived_from=[7], parent_hash="e" * 64), head_hash="e" * 64, claim_id=5,
                       known_claims=frozenset({7}))
    assert not failed(revising)
    assert "no_circular_derivation" in failed(replace(revising, ancestors=frozenset({7, 9, 5})))
    assert "no_circular_derivation" in failed(replace(revising, content=revising.content | {"derived_from": [5]},
                                                      known_claims=frozenset({5})))


def test_open_blocking_challenges_hold_a_merge():
    p = replace(proposal(reviews=[approve(2)]), blocking_challenges=(4,))
    d = pipeline.authorize(p, pipeline.verify(p)[1], MAINTAINER)
    assert not d and "blocking challenge 4 is open" in d.reasons
