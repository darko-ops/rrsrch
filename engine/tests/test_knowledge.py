"""The knowledge schema without a database: canonical hashing, models, claim states."""
import math

import pytest
from pydantic import ValidationError

from rrsrch.knowledge import canonical, states
from rrsrch.knowledge.models import (Check, CheckKind, ClaimContent, ClaimRevision, Relation, Repository,
                                     Span, VerificationRun)

SHA = "a" * 64


def span(start=0, end=10, source="MED:1"):
    return Span(source_id=source, doc_sha256=SHA, start=start, end=end)


def content(**kw):
    base = dict(repository="rrsrch/msc-knee-oa", type="empirical", proposition="WOMAC improved at 12 months.",
                scope={"joint": ["knee"]}, fields={"numbers": [12]},
                evidence=((Relation.SUPPORTS, span()),))
    return ClaimContent(**(base | kw))


def test_canonical_bytes_ignore_key_order_and_keep_unicode():
    assert canonical.dumps({"b": 1, "a": [1, {"d": 2, "c": 3}]}) == b'{"a":[1,{"c":3,"d":2}],"b":1}'
    assert canonical.dumps({"x": "café – 6.1"}) == '{"x":"café – 6.1"}'.encode()
    assert canonical.digest({"a": 1, "b": 2}) == canonical.digest({"b": 2, "a": 1})


def test_canonical_hash_is_pinned():
    # if this changes, every stored content_hash changes with it
    assert canonical.digest({"a": 1}) == "015abd7f5cc57a2dd94b7590f04ad8084273905ee33ec5cebeae62276a97f862"


@pytest.mark.parametrize("bad", [math.nan, math.inf])
def test_canonical_refuses_values_json_cannot_hold(bad):
    with pytest.raises(ValueError):
        canonical.dumps({"x": bad})


def test_content_hash_ignores_evidence_order_but_not_content():
    a = content(evidence=((Relation.SUPPORTS, span(0, 10)), (Relation.CONTEXT, span(20, 30))))
    b = content(evidence=((Relation.CONTEXT, span(20, 30)), (Relation.SUPPORTS, span(0, 10))))
    assert a.content_hash() == b.content_hash()
    assert content(proposition="WOMAC improved at 6 months.").content_hash() != a.content_hash()
    assert content(parent_hash=SHA).content_hash() != content().content_hash()   # the chain is hashed


def test_content_survives_a_round_trip():
    c = content()
    assert ClaimContent.model_validate(c.canonical()).content_hash() == c.content_hash()


def test_models_refuse_malformed_input():
    with pytest.raises(ValidationError):
        span(10, 10)                                       # empty span
    with pytest.raises(ValidationError):
        content(type="opinion")                            # not a claim type
    with pytest.raises(ValidationError):
        content(evidence=())                               # a claim must rest on something
    with pytest.raises(ValidationError):
        content(extra="field")
    with pytest.raises(ValidationError):
        Repository(slug="other/msc", organization_id="rrsrch", topic="t", visibility="public",
                   policy_version="v1")                    # slug owner must be the organization
    with pytest.raises(ValidationError):
        Repository(slug="rrsrch/MSC Knee", organization_id="rrsrch", topic="t", visibility="public",
                   policy_version="v1")


def test_revisions_must_match_their_content_and_chain():
    c = content()
    ClaimRevision(claim_id=1, version=1, content=c, content_hash=c.content_hash(), agent_id=1)
    with pytest.raises(ValidationError, match="does not match"):
        ClaimRevision(claim_id=1, version=1, content=c, content_hash=SHA, agent_id=1)
    with pytest.raises(ValidationError, match="parent"):
        ClaimRevision(claim_id=1, version=2, content=c, content_hash=c.content_hash(), agent_id=1)
    child = content(parent_hash=c.content_hash())
    ClaimRevision(claim_id=1, version=2, parent_id=7, content=child, content_hash=child.content_hash(), agent_id=1)


def test_a_run_passes_only_if_every_check_passes():
    ok = Check(kind=CheckKind.STRUCTURAL, name="schema", passed=True)
    bad = Check(kind=CheckKind.SOURCE, name="self_check", passed=False)
    assert VerificationRun(claim_revision_id=1, policy_version="v1", checks=(ok,)).passed
    assert not VerificationRun(claim_revision_id=1, policy_version="v1", checks=(ok, bad)).passed


def test_claim_states_follow_the_review_process():
    S = states.ClaimState
    assert states.check("structurally_valid", "under_review") is S.UNDER_REVIEW
    assert states.check(S.SUPPORTED, S.CONTESTED) is S.CONTESTED       # support can be lost
    with pytest.raises(states.IllegalTransition):
        states.check(S.SUBMITTED, S.SUPPORTED)                         # no skipping review
    for final in (S.REJECTED, S.SUPERSEDED, S.RETRACTED):
        assert final in states.FINAL
        with pytest.raises(states.IllegalTransition):
            states.check(final, S.UNDER_REVIEW)
    assert set(states.TRANSITIONS) == set(S)                           # every state is covered


def test_derived_from_only_enters_the_hash_when_set():
    plain = content()
    assert "derived_from" not in plain.canonical()                       # earlier hashes still hold
    d = content(derived_from=(9, 3, 9))
    assert d.canonical()["derived_from"] == [3, 9] and d.content_hash() != plain.content_hash()
