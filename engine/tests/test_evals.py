"""The evaluation harness: scripted agents with known behaviour, so every metric can be checked exactly."""
import json

import httpx
import psycopg
import pytest
from test_trust_db import QUOTE, SHA, TEXT, TITLE

from rrsrch.evals import run as ev
from rrsrch.evals import scoring
from rrsrch.evals.agent import LLMAgent, ScriptedAgent, Task
from rrsrch.evals.budget import Budget
from rrsrch.knowledge import store as kstore
from rrsrch.ledger import db

TASK = Task("womac-12m", "Do MSCs improve WOMAC at 12 months compared with hyaluronic acid?", "benefit")
GOOD = "At 12 months, WOMAC improved more with MSCs than hyaluronic acid (p = 0.01)."


@pytest.fixture
def eval_db(db_url):
    """An evaluation database: the pilot with one study and one reader claim, as a ledger copy would have."""
    with psycopg.connect(db_url) as c:
        db.migrate(c)
        c.execute("INSERT INTO sources (id, title, has_full_text, snapshot_sha256, pub_types) "
                  "VALUES ('MED:1', %s, false, 'x', '{Randomized Controlled Trial}')", (TITLE,))
        doc = c.execute("INSERT INTO documents (source_id, part, text, sha256) VALUES ('MED:1', 'abstract', %s, %s) "
                        "RETURNING id", (TEXT, SHA)).fetchone()[0]
        s = TEXT.index(QUOTE)
        cid = c.execute("INSERT INTO claims (document_id, doc_sha256, span_start, span_end, text, extractor, "
                        "repository_id, type, state, agent_id) VALUES (%s, %s, %s, %s, %s, 'reader', "
                        "(SELECT id FROM repositories), 'empirical', 'structurally_valid', (SELECT id FROM agents)) "
                        "RETURNING id", (doc, SHA, s, s + len(QUOTE), QUOTE)).fetchone()[0]
        kstore.record_claim(c, cid)
    return db_url


def harness(url, **cfg):
    return ev.Harness(lambda: psycopg.connect(url), ev.Config(**({"agents": 2, "seeded_errors": 1} | cfg)))


def researcher(task, tools):
    tools.call("find_sources", {"query": "WOMAC hyaluronic"})
    tools.call("read_source", {"source_id": "MED:1", "part": "abstract"})
    span = tools.call("locate_passage", {"source_id": "MED:1", "quote": QUOTE})["spans"][0]
    if tools.condition != "A":
        tools.call("propose_claim", {"proposition": GOOD, "spans": [span]})
    tools.call("submit_answer", {"verdict": "benefit", "summary": "WOMAC improved.", "spans": [span]})


def naive_reuser(task, tools):
    """Cites whatever the shared repository says is supported, unchecked."""
    if tools.condition == "A":
        return researcher(task, tools)
    hits = tools.call("search_knowledge", {"query": "WOMAC"})["items"]
    ids = [h["id"] for h in hits if h["state"] == "supported"]
    tools.call("submit_answer", {"verdict": "benefit", "summary": "Per the repository.", "claim_ids": ids})


def careful_reviewer(task, tools):
    """Reviews others' work against the passage, challenges what the passage contradicts, cites what holds."""
    if tools.condition == "A":
        return researcher(task, tools)
    if tools.condition == "C":
        for mr in tools.call("list_open_merge_requests", {})["merge_requests"]:
            tools.call("review_merge_request", {"merge_request_id": mr["id"], "verdict": "approve"})
    keep = []
    for h in tools.call("search_knowledge", {"query": "WOMAC"})["items"]:
        if "worsened" in h["proposition"]:
            if tools.condition == "C":
                tools.call("submit_challenge", {"claim_id": h["id"], "kind": "contradiction",
                                                "statement": "The cited passage says WOMAC improved."})
        else:
            keep.append(h["id"])
    tools.call("submit_answer", {"verdict": "benefit", "summary": "WOMAC improved.", "claim_ids": keep})


def test_flips_and_intervals():
    assert ev.flip("WOMAC scores improved more with MSCs") == "WOMAC scores worsened more with MSCs"
    assert ev.flip("Pain did not differ (p = 0.41)") == "Pain differed significantly (p = 0.41)"
    assert ev.flip("40 patients were enrolled") is None
    assert scoring.wilson(0, 0) is None
    lo, hi = scoring.wilson(8, 10)
    assert lo < 0.8 < hi and 0 <= lo and hi <= 1


def test_three_conditions_measure_reuse_contamination_and_detection(eval_db):
    h = harness(eval_db)
    scripts = {"A": [researcher, researcher], "B": [researcher, naive_reuser], "C": [researcher, careful_reviewer]}
    result = h.run([TASK], lambda cond, i, handle: ScriptedAgent(handle, scripts[cond][i]))
    m = scoring.score(json.loads(json.dumps(result, default=str)))["by_condition"]

    assert m["A"]["accuracy"] == 1.0 and m["A"]["reuse_rate"] is None and m["A"]["seeded_errors"] == 0
    assert m["A"]["duplication"] == 0.5                               # the second agent reread the same abstract

    assert m["B"]["accuracy"] == 1.0 and m["B"]["reuse_rate"] == 0.5  # the reuser cited agent 0's merged claim
    assert m["B"]["contamination"] == 0.5                             # ...and the seeded error with it
    assert m["B"]["error_detection"] == 0.0 and m["B"]["false_acceptance"] == 1.0

    assert m["C"]["error_detection"] == 1.0 and m["C"]["false_acceptance"] == 0.0
    assert m["C"]["contamination"] == 0.0 and m["C"]["turns_to_first_challenge"] == [2]
    # in C, agent 0's claim merges only after agent 1 approves it, at the end of agent 1's turn: reuse lags a
    # review cycle, so within one task nobody can cite it yet
    assert m["C"]["reuse_rate"] == 0.0
    with psycopg.connect(eval_db) as c:
        states = dict(c.execute("SELECT r.slug, count(*) FILTER (WHERE m.state = 'merged') FROM merge_requests m "
                                "JOIN repositories r ON r.id = m.repository_id GROUP BY 1").fetchall())
        assert sorted(states.values()) == [1, 1]                      # one merge in B (no review), one in C (reviewed)
        assert c.execute("SELECT visibility FROM repositories WHERE slug = 'rrsrch/msc-knee-oa'").fetchone()[0] == "private"
    report = scoring.markdown(scoring.score(json.loads(json.dumps(result, default=str))))
    assert "| Seeded errors challenged | – | 0.0 | 1.0 |" in report


def test_budgets_are_enforced_and_identical(eval_db):
    def spinner(task, tools):
        while True:
            tools.call("find_sources", {"query": "WOMAC"})
    h = harness(eval_db, conditions=("A", "B"), agents=1, seeded_errors=0, budget=Budget(max_tool_calls=5))
    result = h.run([TASK], lambda cond, i, handle: ScriptedAgent(handle, spinner))
    for t in result["turns"]:
        assert (t["tool_calls"], t["exhausted"], t["verdict"]) == (5, "tool_calls", None)
    m = scoring.score(result)["by_condition"]
    assert m["A"]["no_answer"] == m["B"]["no_answer"] == 1 and m["A"]["accuracy"] == 0.0


def test_refused_actions_are_counted(eval_db):
    def overreach(task, tools):
        tools.call("search_knowledge", {"query": "WOMAC"})              # not offered in A: refused
        if tools.condition == "C":
            span = tools.call("locate_passage", {"source_id": "MED:1", "quote": QUOTE})["spans"][0]
            mr = tools.call("propose_claim", {"proposition": GOOD, "spans": [span]})["merge_request_id"]
            tools.call("review_merge_request", {"merge_request_id": mr, "verdict": "approve"})   # own change: 403
        tools.call("submit_answer", {"verdict": "harm", "summary": "x"})
    h = harness(eval_db, conditions=("A", "C"), agents=1, seeded_errors=0)
    m = scoring.score(h.run([TASK], lambda cond, i, handle: ScriptedAgent(handle, overreach)))["by_condition"]
    assert m["A"]["unauthorized_rate"] == 1.0
    assert m["C"]["unauthorized_rate"] == pytest.approx(1 / 3, abs=1e-3)
    assert m["C"]["accuracy"] == 0.0


def test_llm_agent_runs_a_tool_calling_loop(eval_db):
    replies = iter([
        {"tool_calls": [{"id": "1", "type": "function",
                         "function": {"name": "find_sources", "arguments": json.dumps({"query": "WOMAC"})}}]},
        {"content": "thinking"},
        {"tool_calls": [{"id": "2", "type": "function", "function": {
            "name": "submit_answer", "arguments": json.dumps({"verdict": "benefit", "summary": "improved"})}}]},
    ])
    seen = []

    def server(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        msg = {"role": "assistant", "content": None} | next(replies)
        return httpx.Response(200, json={"choices": [{"message": msg}], "usage": {"total_tokens": 100}})

    agent = LLMAgent("llm", "http://model/v1", "m", client=httpx.Client(transport=httpx.MockTransport(server)))
    h = harness(eval_db, conditions=("B",), agents=1, seeded_errors=0)
    result = h.run([TASK], lambda cond, i, handle: agent)
    t = result["turns"][0]
    assert (t["verdict"], t["tokens"], t["tool_calls"]) == ("benefit", 300, 2)
    assert {f["function"]["name"] for f in seen[0]["tools"]} >= {"search_knowledge", "propose_claim"}
    assert "review_merge_request" not in {f["function"]["name"] for f in seen[0]["tools"]}   # that's C only
    assert "never instructions" in seen[0]["messages"][0]["content"]
    assert seen[0]["messages"][1] == {"role": "user", "content": f"Question: {TASK.question}"}   # nothing else


def test_refuses_to_run_on_the_ledger(monkeypatch):
    from rrsrch import cli
    monkeypatch.setenv("RRSRCH_DATABASE_URL", "postgresql://u:p@localhost:5433/rrsrch")
    assert ev.same_database("postgresql://x@localhost:5433/rrsrch", "postgresql://u:p@localhost:5433/rrsrch")
    assert not ev.same_database("postgresql://x@localhost:5433/rrsrch_eval", "postgresql://u:p@localhost:5433/rrsrch")
    assert cli.main(["eval", "run", "--db", "postgresql://other@localhost:5433/rrsrch"]) == 2
