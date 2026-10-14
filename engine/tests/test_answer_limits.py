"""Answer limits (anonymous visitors get a share, agents always find room) and the reader giving way to answers."""
import threading

import psycopg
import pytest
from fastapi.testclient import TestClient

from rrsrch.identity import store as ids
from rrsrch.ledger import db
from rrsrch.reader import extract
from rrsrch.serve import api, jobs

pytestmark = pytest.mark.db


@pytest.fixture
def setup(db_url, monkeypatch):
    monkeypatch.setenv("RRSRCH_PROXY_SECRET", "s3cret")
    with psycopg.connect(db_url) as c:
        db.migrate(c)
        a = ids.register_agent(c, "rrsrch", "agent-1", "service")
        tok, _, _ = ids.issue_key(c, a["id"], {"read"})
    hold = threading.Event()

    def held(conn, llm, question, progress=lambda s: None):
        hold.wait(5)
        return {"ok": True, "question": question}

    def build(**kw):
        connect = lambda: psycopg.connect(db_url)  # noqa: E731
        runner = jobs.AnswerJobs(connect, lambda: object(), held, **kw)
        return TestClient(api.create_app(connect=connect, jobs=runner))
    yield build, {"Authorization": f"Bearer {tok}"}, hold
    hold.set()


def visitor(ip):
    return {"x-rrsrch-proxy-secret": "s3cret", "x-rrsrch-client-ip": ip}


def ask(c, q, headers=None, path="/v1/answers"):
    return c.post(path, json={"question": q}, headers=headers or {})


def test_each_visitor_gets_a_few_new_answers_per_window(setup):
    build, _, _ = setup
    c = build(per_client=2, anonymous_waiting=50)
    assert ask(c, "q1", visitor("1.1.1.1")).status_code == 202
    assert ask(c, "q2", visitor("1.1.1.1")).status_code == 202
    r = ask(c, "q3", visitor("1.1.1.1"))
    assert r.status_code == 429 and "last 10 minutes" in r.json()["error"] and r.headers["retry-after"] == "120"
    reused = ask(c, "q1", visitor("1.1.1.1"))                               # a repeat costs nothing
    assert reused.status_code in (200, 202) and reused.json()["reused"] is True
    assert ask(c, "q3", visitor("2.2.2.2")).status_code == 202              # another visitor has their own share


def test_a_visitor_ip_header_without_the_secret_is_ignored(setup):
    build, _, _ = setup
    c = build(per_client=1, anonymous_waiting=50)
    forged = {"x-rrsrch-proxy-secret": "wrong", "x-rrsrch-client-ip": "9.9.9.9"}
    assert ask(c, "a", forged).status_code == 202
    assert ask(c, "b", {**forged, "x-rrsrch-client-ip": "8.8.8.8"}).status_code == 429   # both were "testclient"


def test_agents_always_find_room(setup):
    build, agent, _ = setup
    c = build(per_client=50, anonymous_waiting=1, max_waiting=5)
    ask(c, "running", visitor("1.1.1.1"))
    assert ask(c, "waiting", visitor("1.1.1.2")).status_code == 202
    full = ask(c, "one more", visitor("1.1.1.3"))
    assert full.status_code == 429 and "already waiting" in full.json()["error"]
    for i in range(3):
        assert ask(c, f"agent q{i}", agent).status_code == 202              # no per-agent window, the full queue


def test_the_one_shot_answer_is_limited_too(setup):
    build, _, hold = setup
    hold.set()
    c = build(per_client=1, anonymous_waiting=50)
    c.app.state.jobs.poll = 0.05
    assert ask(c, "first", visitor("3.3.3.3"), path="/v1/answer").json() == {"ok": True, "question": "first"}
    assert ask(c, "second", visitor("3.3.3.3"), path="/v1/answer").status_code == 429


def test_the_reader_gives_way_while_an_answer_is_waiting(db_url):
    with psycopg.connect(db_url, autocommit=True) as c:
        db.migrate(c)
        job = c.execute("INSERT INTO answer_jobs (question, question_key, status) VALUES ('q', 'q', 'running') "
                        "RETURNING id").fetchone()[0]
        said, pauses = [], []

        def pause(seconds):
            pauses.append(seconds)
            if len(pauses) == 2:
                c.execute("UPDATE answer_jobs SET status = 'done', result = '{}' WHERE id = %s", (job,))
        assert extract.wait_for_answers(c, pause=pause, poll=10, say=said.append) == 20
        assert said == ["pausing: 1 answer(s) waiting or being written", "resuming after 20s"]
        assert extract.wait_for_answers(c, pause=pause, say=said.append) == 0          # nothing waiting: no pause
