"""Search answers rest on the knowledge network: public repositories only, never rejected or replaced claims,
reviewed claims first, and every citation says where its claim stands in review."""
import pytest
from test_writer import ScriptedLLM, conn  # noqa: F401  (conn is the writer fixture)

from rrsrch.serve import answer as answer_mod
from rrsrch.writer import retrieve

pytestmark = pytest.mark.db
Q = "Do MSCs reduce VAS pain at 12 months?"


def ids(conn_, q=Q):
    return [c.id for c in retrieve.candidates(conn_, q)]


def test_private_repositories_never_reach_a_public_answer(conn):
    hyal, plac, *_ = conn.claim_ids
    assert plac in ids(conn)
    repo = conn.execute("INSERT INTO repositories (slug, organization_id, topic, visibility, policy_version) "
                        "VALUES ('rrsrch/private', 'rrsrch', 't', 'private', 'v1') RETURNING id").fetchone()[0]
    conn.execute("INSERT INTO policies (repository_id, version, rules) VALUES (%s, 'v1', '{}')", (repo,))
    conn.execute("UPDATE claims SET repository_id = %s WHERE id = %s", (repo, plac))
    assert plac not in ids(conn) and hyal in ids(conn)


@pytest.mark.parametrize("state", ["rejected", "retracted", "superseded", "draft", "submitted"])
def test_claims_review_has_set_aside_are_not_used(conn, state):
    hyal = conn.claim_ids[0]
    conn.execute("UPDATE claims SET state = %s WHERE id = %s", (state, hyal))
    assert hyal not in ids(conn)


def test_contested_claims_stay_in_and_supported_ones_rank_first(conn):
    hyal, plac, *_ = conn.claim_ids
    assert ids(conn)[:2] == [hyal, plac]                     # equally relevant: by id
    conn.execute("UPDATE claims SET state = 'supported' WHERE id = %s", (plac,))
    conn.execute("UPDATE claims SET state = 'contested' WHERE id = %s", (hyal,))
    got = retrieve.candidates(conn, Q)
    assert [c.id for c in got][:2] == [plac, hyal]
    assert {c.id: c.state for c in got}[hyal] == "contested"


def test_citations_say_where_each_claim_stands(conn, monkeypatch):
    hyal, plac, func, *_ = conn.claim_ids
    monkeypatch.setattr(answer_mod.skeptic, "scan", lambda c: None)  # keep the contradiction planted below
    conn.execute("UPDATE claims SET state = 'supported' WHERE id = %s", (plac,))
    conn.execute("INSERT INTO challenges (claim_id, author_id, kind, statement, blocking) "
                 "VALUES (%s, (SELECT id FROM agents LIMIT 1), 'scope', 'single centre', true)", (hyal,))
    conn.execute("INSERT INTO claim_agreements (claim_a_id, claim_b_id, verdict, rule, detail, evidence, rules) "
                 "VALUES (%s, %s, 'contradicts', 'direction', 't', '{}', 'v1')", (min(hyal, func), max(hyal, func)))
    llm = ScriptedLLM({"verdict": "benefit", "sentences": [
        {"text": "At 12 months, VAS pain was lower with MSCs than with hyaluronic acid or placebo.",
         "cites": [hyal, plac]}]})
    out = answer_mod.answer(conn, llm, Q)
    cit = out["citations"]
    assert cit[str(plac)]["state"] == "supported" and cit[str(plac)]["repository"] == "rrsrch/msc-knee-oa"
    assert cit[str(hyal)]["open_challenges"] == 1 and cit[str(hyal)]["contradicted_by"] == [func]
    assert out["trust"] == {"claims": 2, "by_state": {"structurally_valid": 1, "supported": 1},
                            "challenged": 1, "contradicted": 1}
