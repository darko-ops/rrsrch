import hashlib
import json
import uuid

import pytest

from rrsrch.reader import extract, spans
from rrsrch.reader.llm import LLM, parse_json_object


def test_quotes_are_found_through_typography_only():
    text = "Results\nVAS pain fell from 6.1 to 3.2 – a “marked” change   at 12 months."
    s = spans.locate('VAS pain fell from 6.1 to 3.2 - a "marked" change at 12 months.', text)
    assert s is not None and text[s[0]:s[1]].startswith("VAS pain") and text[s[0]:s[1]].endswith("months.")
    assert spans.locate("VAS pain fell from 6.1 to 3.3 - a", text) is None          # a changed digit
    assert spans.locate("vas pain fell from 6.1 to 3.2", text) is None               # changed case
    assert spans.locate("VAS pain", text) is None                                    # too short to pin


def test_model_timeout_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("RRSRCH_LLM_URL", "http://model/v1/")
    monkeypatch.setenv("RRSRCH_READER_MODEL", "m")
    monkeypatch.delenv("RRSRCH_LLM_TIMEOUT", raising=False)
    assert LLM.from_env() == LLM("http://model/v1", "m", 300.0)
    monkeypatch.setenv("RRSRCH_LLM_TIMEOUT", " 900 ")
    assert LLM.from_env().timeout == 900.0
    for bad in ("0", "-5", "soon", "inf", "nan"):
        monkeypatch.setenv("RRSRCH_LLM_TIMEOUT", bad)
        with pytest.raises(RuntimeError, match="RRSRCH_LLM_TIMEOUT"):
            LLM.from_env()


def test_quotes_must_be_inside_the_chunk_that_was_read():
    text = "Introduction: MSCs repaired cartilage in rats. Results: WOMAC improved at 12 months."
    start = text.index("Results")
    assert spans.locate("MSCs repaired cartilage in rats.", text, start) is None
    assert spans.locate("WOMAC improved at 12 months.", text, start) is not None


def test_replies_parse_with_or_without_a_code_fence():
    assert parse_json_object('```json\n{"claims": []}\n```') == {"claims": []}
    assert parse_json_object('Here you go: {"claims": [1]} trailing') == {"claims": [1]}
    with pytest.raises(ValueError):
        parse_json_object("no json here")


def test_fulltext_chunks_skip_introduction_and_discussion():
    text = "\n\n".join(["Introduction", "Rats did well in prior work.", "Methods", "We enrolled 40 patients.",
                      "Results", "WOMAC improved at 12 months.", "Discussion", "Others found the same."])
    got = [c.text for c in extract.chunks("fulltext", text)]
    assert got == ["We enrolled 40 patients.\n\nResults\n\nWOMAC improved at 12 months."]
    c = extract.chunks("fulltext", text)[0]
    assert text[c.start:c.end] == c.text                      # chunks are exact slices


# ── the whole reader against Postgres, with a scripted model ──

psycopg = pytest.importorskip("psycopg")
from rrsrch.ledger import db  # noqa: E402

ABSTRACT = ("Methods\nForty patients with knee osteoarthritis received bone marrow MSCs or hyaluronic acid.\n"
            "Results\nAt 12 months, WOMAC scores improved more with MSCs than with hyaluronic acid (p = 0.01), "
            "while VAS pain did not differ (p = 0.41).")


class ScriptedLLM:
    model = "scripted"

    def __init__(self, claims):
        self.claims = claims

    def json_chat(self, system, user):
        assert "Forty patients" in user
        return {"claims": self.claims}


@pytest.fixture
def conn():
    import os
    url = os.environ.get("RRSRCH_DATABASE_URL", db.DEFAULT_URL)
    try:
        admin = psycopg.connect(url, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("Postgres not running (docker compose up -d)")
    name = f"rrsrch_test_{uuid.uuid4().hex[:8]}"
    admin.execute(f"CREATE DATABASE {name}")
    c = psycopg.connect(url.rsplit("/", 1)[0] + f"/{name}")
    db.migrate(c)
    c.execute("INSERT INTO sources (id, title, has_full_text, snapshot_sha256) VALUES "
              "('MED:1', 'Bone marrow MSCs versus hyaluronic acid for knee osteoarthritis', false, 'x')")
    c.execute("INSERT INTO documents (source_id, part, text, sha256) VALUES ('MED:1', 'abstract', %s, %s)",
              (ABSTRACT, hashlib.sha256(ABSTRACT.encode()).hexdigest()))
    c.commit()
    try:
        yield c
    finally:
        c.close()
        admin.execute(f"DROP DATABASE {name}")
        admin.close()


@pytest.mark.db
def test_reader_keeps_checked_claims_and_records_every_rejection(conn):
    quote = ("At 12 months, WOMAC scores improved more with MSCs than with hyaluronic acid (p = 0.01), "
             "while VAS pain did not differ (p = 0.41).")
    llm = ScriptedLLM([
        {"quote": quote, "claim": "At 12 months, WOMAC improved more with MSCs than hyaluronic acid (p = 0.01)."},
        {"quote": quote, "claim": "At 12 months, VAS pain did not differ between MSCs and hyaluronic acid (p = 0.41)."},
        {"quote": quote, "claim": "MSCs reduced VAS pain more than hyaluronic acid."},                  # direction flip
        {"quote": quote, "claim": "At 24 months, WOMAC improved more with MSCs (p = 0.01)."},            # invented number
        {"quote": "At 12 months, KOOS improved with MSCs (p = 0.01).", "claim": "KOOS improved (p = 0.01)."},  # not in text
        {"quote": quote, "claim": "The study was interesting."},                                          # nothing to check
    ])
    rep = extract.read_corpus(conn, llm, progress=lambda *_: None)
    assert rep.claims == 2
    assert rep.rejected == {"gate:direction": 1, "gate:numbers": 1, "quote_not_found": 1,
                            "nothing_checkable": 1}
    rows = conn.execute("SELECT text, span_start, span_end, scope, self_check FROM claims ORDER BY id").fetchall()
    for text, a, b, scope, check in rows:
        assert ABSTRACT[a:b] == quote
        assert scope == {"species": ["human"], "joint": ["knee"], "condition": ["osteoarthritis"]}
        assert check["passed"] is True
    # each kept claim is recorded: a hashed first revision, one shared passage, a passing run
    assert conn.execute("SELECT count(*), bool_and(v.passed) FROM claim_revisions r "
                        "JOIN verification_runs v ON v.claim_revision_id = r.id").fetchone() == (2, True)
    assert conn.execute("SELECT count(*) FROM evidence").fetchone()[0] == 1
    # rerunning reads nothing new
    rep2 = extract.read_corpus(conn, llm, progress=lambda *_: None)
    assert (rep2.chunks_read, rep2.chunks_skipped, rep2.claims) == (0, 1, 0)


@pytest.mark.db
def test_a_crashed_run_keeps_every_chunk_it_finished(conn, monkeypatch):
    from rrsrch import cli
    from rrsrch.reader import llm as llm_mod
    conn.execute("INSERT INTO sources (id, title, has_full_text, snapshot_sha256) VALUES "
                 "('MED:2', 'Bone marrow MSCs versus hyaluronic acid for knee osteoarthritis', false, 'x')")
    conn.execute("INSERT INTO documents (source_id, part, text, sha256) VALUES ('MED:2', 'abstract', %s, %s)",
                 (ABSTRACT, hashlib.sha256(ABSTRACT.encode()).hexdigest()))
    conn.commit()
    quote = ("At 12 months, WOMAC scores improved more with MSCs than with hyaluronic acid (p = 0.01), "
             "while VAS pain did not differ (p = 0.41).")

    class DiesOnSecondSource(ScriptedLLM):
        calls = 0

        def json_chat(self, system, user):
            DiesOnSecondSource.calls += 1
            if DiesOnSecondSource.calls > 1:
                raise RuntimeError("model server went away")
            return super().json_chat(system, user)

    monkeypatch.setattr(llm_mod.LLM, "from_env", classmethod(lambda cls: DiesOnSecondSource([
        {"quote": quote, "claim": "At 12 months, WOMAC improved more with MSCs than hyaluronic acid (p = 0.01)."}])))
    info = conn.info
    monkeypatch.setenv("RRSRCH_DATABASE_URL",
                       f"postgresql://{info.user}:{info.password}@{info.host}:{info.port}/{info.dbname}")
    with pytest.raises(RuntimeError, match="went away"):
        cli.main(["read", "run"])
    conn.rollback()
    # the first source's chunk was committed when it finished, so a rerun starts after it
    assert conn.execute("SELECT count(*) FROM claims").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM read_chunks").fetchone()[0] == 1
