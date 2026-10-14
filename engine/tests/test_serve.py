"""The HTTP API, with the model and writer replaced by fakes (and, where nothing is stored, the database too)."""
import psycopg
import pytest
from fastapi.testclient import TestClient

from rrsrch.ledger import db
from rrsrch.serve import api, jobs


class FakeConn:
    def __init__(self, fail=False):
        self.fail = fail

    def __enter__(self):
        if self.fail:
            raise RuntimeError("connection refused")
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, *args):
        return self

    def fetchone(self):
        return (7,)


@pytest.fixture
def calls(monkeypatch):
    monkeypatch.setattr(api.db, "migrate", lambda conn: [])
    return []


def client(calls, fail_db=False, answer=None):
    def fake_answer(conn, llm, question):
        calls.append(question)
        return {"ok": True, "question": question}
    app = api.create_app(connect=lambda: FakeConn(fail_db), make_llm=lambda: object(),
                         answer=answer or fake_answer)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def answering(db_url):
    """A client whose answers go through the real job queue on a throwaway database, with a fake writer."""
    with psycopg.connect(db_url) as c:
        db.migrate(c)
    seen = []

    def build(answer=None):
        def fake(conn, llm, question, progress=lambda s: None):
            seen.append(question)
            return {"ok": True, "question": question}
        connect = lambda: psycopg.connect(db_url)  # noqa: E731
        runner = jobs.AnswerJobs(connect, lambda: object(), answer or fake)
        runner.poll = 0.05
        return TestClient(api.create_app(connect=connect, jobs=runner), raise_server_exceptions=False)
    build.seen = seen
    return build


@pytest.mark.db
def test_answers_a_question_with_whitespace_normalised(answering):
    c = answering()
    r = c.post("/v1/answer", json={"question": "  does MSC   help\nknee OA? "})
    assert r.status_code == 200 and r.json() == {"ok": True, "question": "does MSC help knee OA?"}
    assert c.post("/answer", json={"question": "legacy path"}).status_code == 200


@pytest.mark.parametrize("kwargs, error", [
    ({"json": {}}, "question required"),
    ({"json": {"question": "   "}}, "question required"),
    ({}, "question required"),
    ({"json": {"question": "x" * 801}}, "question too long"),
    ({"content": b"{not json", "headers": {"Content-Type": "application/json"}}, "body must be JSON"),
    ({"json": {"question": 42}}, "question must be a string"),
])
def test_bad_requests_get_the_error_shape_the_site_reads(calls, kwargs, error):
    r = client(calls).post("/v1/answer", **kwargs)
    assert (r.status_code, r.json()) == (400, {"ok": False, "error": error})
    assert calls == []


@pytest.mark.db
def test_writer_failures_are_500s_not_crashes(answering):
    def boom(conn, llm, q, progress=None):
        raise RuntimeError("model timed out")
    r = answering(boom).post("/v1/answer", json={"question": "q"})
    assert (r.status_code, r.json()) == (500, {"ok": False, "error": "model timed out"})


def test_health_reports_claims_or_503(calls, monkeypatch):
    monkeypatch.setenv("RRSRCH_READER_MODEL", "m")
    for path in ("/v1/health", "/health", "/"):
        assert client(calls).get(path).json() == {"ok": True, "claims": 7, "model": "m"}
    r = client(calls, fail_db=True).get("/v1/health")
    assert (r.status_code, r.json()) == (503, {"ok": False, "error": "connection refused"})


def test_unknown_paths_and_methods(calls):
    r = client(calls).get("/v2/nothing")
    assert (r.status_code, r.json()) == (404, {"ok": False, "error": "not found"})
    assert client(calls).get("/v1/answer").json() == {"ok": False, "error": "method not allowed"}


@pytest.mark.db
def test_cors_preflight_and_headers(answering):
    c = answering()
    r = c.options("/v1/answer", headers={"Origin": "https://rrsrch.com", "Access-Control-Request-Method": "POST",
                                         "Access-Control-Request-Headers": "Content-Type"})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "*"
    r = c.post("/v1/answer", json={"question": "q"}, headers={"Origin": "https://rrsrch.com"})
    assert r.headers["access-control-allow-origin"] == "*"


def test_request_bodies_must_declare_a_sane_length(calls):
    c = client(calls)
    r = c.post("/v1/answer", content=b'{"question": "q"}', headers={"Content-Type": "application/json",
                                                                  "Content-Length": "abc"})
    assert (r.status_code, r.json()) == (400, {"ok": False, "error": "invalid Content-Length"})

    def chunks():
        yield b'{"question": '
        yield b'"q"}'
    r = c.post("/v1/answer", content=chunks(), headers={"Content-Type": "application/json"})
    assert (r.status_code, r.json()["error"]) == (411, "send a Content-Length")
