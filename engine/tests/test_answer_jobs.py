"""Answers as jobs: ask, get a ticket at once, check back for the stage and then the answer."""
import threading
import time

import psycopg
import pytest
from fastapi.testclient import TestClient

from rrsrch.ledger import db
from rrsrch.serve import api, jobs

pytestmark = pytest.mark.db


def wait_for(client, job_id, status, timeout=10, stage=None):
    end = time.time() + timeout
    while time.time() < end:
        got = client.get(f"/v1/answers/{job_id}").json()
        if got["status"] == status and (stage is None or got["stage"] == stage):
            return got
        time.sleep(0.05)
    raise AssertionError(f"job never reached {status}: {got}")


@pytest.fixture
def make(db_url):
    with psycopg.connect(db_url) as c:
        db.migrate(c)

    def build(answer, **kw):
        connect = lambda: psycopg.connect(db_url)  # noqa: E731
        runner = jobs.AnswerJobs(connect, lambda: object(), answer, **kw)
        return TestClient(api.create_app(connect=connect, jobs=runner)), runner
    return build


def test_a_question_returns_a_ticket_then_an_answer(make):
    gate = threading.Event()

    def slow_answer(conn, llm, question, progress):
        progress("finding claims and writing the answer")
        gate.wait(5)
        return {"ok": True, "question": question, "verdict": "benefit"}

    client, _ = make(slow_answer)
    r = client.post("/v1/answers", json={"question": "  Does MSC   help knee pain? "})
    assert r.status_code == 202
    job = r.json()
    assert job["status"] in ("queued", "running") and job["question"] == "Does MSC help knee pain?"
    running = wait_for(client, job["job_id"], "running", stage="finding claims and writing the answer")
    assert "answer" not in running

    again = client.post("/v1/answers", json={"question": "does msc help knee pain"}).json()
    assert again["job_id"] == job["job_id"] and again["reused"] is True        # no second run of the model

    gate.set()
    done = wait_for(client, job["job_id"], "done")
    assert done["answer"]["verdict"] == "benefit" and done["stage"] == "done"
    cached = client.post("/v1/answers", json={"question": "Does MSC help knee pain?"})
    assert cached.status_code == 200 and cached.json()["answer"]["verdict"] == "benefit"


def test_failures_are_recorded_not_raised(make):
    def broken(conn, llm, question, progress):
        raise RuntimeError("model timed out")
    client, _ = make(broken)
    job = client.post("/v1/answers", json={"question": "q?"}).json()
    failed = wait_for(client, job["job_id"], "failed")
    assert failed["error"] == "model timed out" and "answer" not in failed
    retry = client.post("/v1/answers", json={"question": "q?"}).json()
    assert retry["job_id"] != job["job_id"]                                 # a failure isn't cached


def test_the_waiting_line_is_bounded_and_bad_requests_refused(make):
    block = threading.Event()

    def stuck(conn, llm, question, progress):
        block.wait(5)
        return {"ok": True}
    client, _ = make(stuck, max_waiting=2, anonymous_waiting=2, per_client=50)   # the queue cap, not the visitor limit
    first = client.post("/v1/answers", json={"question": "first"}).json()
    wait_for(client, first["job_id"], "running")
    assert client.post("/v1/answers", json={"question": "second"}).status_code == 202
    assert client.post("/v1/answers", json={"question": "third"}).status_code == 202
    full = client.post("/v1/answers", json={"question": "fourth"})
    assert full.status_code == 429 and "waiting" in full.json()["error"]
    assert client.post("/v1/answers", json={}).status_code == 400
    assert client.get("/v1/answers/not-a-uuid").status_code == 404
    assert client.get("/v1/answers/00000000-0000-0000-0000-000000000000").status_code == 404
    block.set()


def test_after_a_restart_running_jobs_fail_and_waiting_ones_resume(make, db_url):
    with psycopg.connect(db_url) as c:
        lost = c.execute("INSERT INTO answer_jobs (question, question_key, status, started_at) "
                         "VALUES ('a', 'a', 'running', now()) RETURNING id").fetchone()[0]
        waiting = c.execute("INSERT INTO answer_jobs (question, question_key) VALUES ('b', 'b') RETURNING id").fetchone()[0]
    client, runner = make(lambda conn, llm, question, progress: {"ok": True, "question": question})
    assert runner.recover() == 1
    assert "restarted" in client.get(f"/v1/answers/{lost}").json()["error"]
    assert wait_for(client, waiting, "done")["answer"]["question"] == "b"
