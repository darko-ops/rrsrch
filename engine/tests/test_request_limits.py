"""Bounds on what one request can cost: converting HTML, fetching, waiting for an answer, finding a quote, signing up."""
import threading
import time

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from test_agent_sources import FILING, PUBLIC, upload  # noqa: F401
from test_trust_db import world  # noqa: F401  (world is a fixture)

from rrsrch.corpus import html as htmlmod
from rrsrch.identity import onboarding
from rrsrch.identity import store as ids
from rrsrch.knowledge import ingest, query
from rrsrch.ledger import db
from rrsrch.reader import spans
from rrsrch.serve import api, jobs
from rrsrch.sources import web
from rrsrch.trust.merge import Refused

SLOW_HTML = "<a b=" * 20000             # takes the standard library's parser about a minute


# --- converting HTML -------------------------------------------------------------------------------------------------

def test_html_converted_in_a_child_process_is_the_same_text():
    assert htmlmod.to_text_isolated(FILING) == htmlmod.to_text(FILING)
    odd = "<p>café — \U0001f600 &amp; \udcff</p>"                # surrogates survive the round trip
    assert htmlmod.to_text_isolated(odd) == htmlmod.to_text(odd)


def test_html_that_takes_too_long_to_convert_is_refused_quickly(monkeypatch):
    assert htmlmod.time_limit(len(SLOW_HTML)) < 6
    # newer Pythons parse SLOW_HTML quickly; a limit no child can meet makes the test the same everywhere
    monkeypatch.setattr(htmlmod, "TIMEOUT", 0.001)
    monkeypatch.setattr(htmlmod, "TIMEOUT_PER_MB", 0.0)
    t = time.monotonic()
    with pytest.raises(htmlmod.HTMLRefused, match="longer than"):
        htmlmod.to_text_isolated(SLOW_HTML)
    assert time.monotonic() - t < 10


@pytest.mark.db
def test_an_upload_that_is_slow_to_convert_is_refused_and_counted(world, monkeypatch):
    client_, h, url = world
    monkeypatch.setattr(htmlmod, "TIMEOUT", 0.001)             # as above: refused however fast the parser is
    monkeypatch.setattr(htmlmod, "TIMEOUT_PER_MB", 0.0)
    t = time.monotonic()
    r = upload(client_, h["bot"], content=SLOW_HTML.encode())
    assert r.status_code == 422 and "longer than" in r.json()["error"] and time.monotonic() - t < 5
    assert len(ingest.ATTEMPTS.started[_agent_id(url, "bot")]) == 1      # the failed attempt counts


def _agent_id(url, handle):
    with psycopg.connect(url) as c:
        return c.execute("SELECT id FROM agents WHERE handle = %s", (handle,)).fetchone()[0]


# --- attempts count, refused ones too, and only a few run at once ----------------------------------------------------

@pytest.mark.db
def test_failed_fetches_count_toward_the_hourly_limit(world, monkeypatch):
    client_, h, url = world
    monkeypatch.setattr(ingest, "ATTEMPTS_PER_HOUR", 3)

    def refuse(url, **_):
        raise web.FetchRefused("the server answered 404")
    monkeypatch.setattr(ingest.web, "fetch", refuse)
    for i in range(3):
        r = client_.post("/v1/sources", headers=h["bot"], json={"url": f"https://example.com/missing{i}"})
        assert r.status_code == 422
    r = client_.post("/v1/sources", headers=h["bot"], json={"url": "https://example.com/another"})
    assert r.status_code == 429 and "tried in the last hour" in r.json()["error"]
    assert upload(client_, h["bot"]).status_code == 429                   # uploads share the count
    assert upload(client_, h["admin"]).status_code == 201                 # another agent has its own


def test_only_a_few_fetches_run_at_once_per_agent():
    started, release = threading.Event(), threading.Event()
    held = []

    def hold():
        with ingest.ATTEMPTS.attempt(7):
            held.append(1)
            if len(held) == ingest.AT_ONCE:
                started.set()
            release.wait(5)
    threads = [threading.Thread(target=hold) for _ in range(ingest.AT_ONCE)]
    for t in threads:
        t.start()
    assert started.wait(5)
    with pytest.raises(Refused, match="already being fetched"):
        with ingest.ATTEMPTS.attempt(7):
            pass
    with ingest.ATTEMPTS.attempt(8):                                     # someone else isn't held up
        pass
    release.set()
    for t in threads:
        t.join()
    with ingest.ATTEMPTS.attempt(7):                                     # finished ones free their place
        pass


# --- fetching --------------------------------------------------------------------------------------------------------

def test_a_fetch_has_a_deadline_for_the_whole_document():
    def drip():
        for _ in range(100):
            time.sleep(0.05)
            yield b"x"

    def handler(req):
        return httpx.Response(200, headers={"content-type": "text/html"}, content=drip())
    slow = httpx.Client(transport=httpx.MockTransport(handler))
    t = time.monotonic()
    with pytest.raises(web.FetchRefused, match="longer than"):
        web.fetch("https://example.com/slow", user_agent="t", client=slow, resolve=lambda *a, **k: PUBLIC,
                  deadline=0.3)
    assert time.monotonic() - t < 2


def test_the_fetcher_ignores_proxy_settings(monkeypatch):
    seen = {}
    real = httpx.Client

    def spy(*a, **kw):
        seen.update(kw)
        return real(*a, **kw)
    monkeypatch.setattr(web.httpx, "Client", spy)
    with pytest.raises(web.FetchRefused):
        web.fetch("https://example.invalid/", user_agent="t", resolve=lambda *a, **k: (_ for _ in ()).throw(OSError()))
    assert seen["trust_env"] is False


# --- finding a quote -------------------------------------------------------------------------------------------------

def test_a_normalized_document_is_kept_and_finds_the_same_spans():
    text = "Intro.\n\nCapital  expenditures were “$8.4 billion” in fiscal 2024 — up.  " * 3
    quotes = ['expenditures were "$8.4 billion" in fiscal', "fiscal 2024 - up. Capital", "not in the text at all"]
    kept, reads = spans.Normalized(budget=10_000), []

    def read():
        reads.append(1)
        return text
    for q in quotes * 2:
        assert kept.locate(q, "sha", read) == spans.locate(q, text)
    assert reads == [1]                                                  # normalized once
    for i in range(5):                                                   # the budget holds: oldest goes first
        kept.get(f"k{i}", lambda: "y" * 4000)
    assert sum(len(t) for t, _ in kept.kept.values()) <= 10_000 and "sha" not in kept.kept


@pytest.mark.db
def test_locate_through_the_api_matches_the_document(world):
    client_, h, url = world
    with psycopg.connect(url) as c:
        sid, text = c.execute("SELECT source_id, text FROM documents LIMIT 1").fetchone()
    quote = text[10:60]
    for _ in range(2):
        with psycopg.connect(url) as c:
            found = query.locate(c, sid, quote)
        assert found and found[0]["excerpt"] == quote and text[found[0]["start"]:found[0]["end"]] == quote


# --- the one-shot answer ---------------------------------------------------------------------------------------------

@pytest.fixture
def answering(db_url):
    with psycopg.connect(db_url) as c:
        db.migrate(c)
        bot = ids.register_agent(c, "rrsrch", "vetted", "service")
        tok, _, _ = ids.issue_key(c, bot["id"], {"read"})
    hold = threading.Event()

    def held(conn, llm, question, progress=lambda s: None):
        hold.wait(10)
        return {"ok": True, "question": question}

    def build(**kw):
        connect = lambda: psycopg.connect(db_url)  # noqa: E731
        runner = jobs.AnswerJobs(connect, lambda: object(), held, workers=4, **kw)
        runner.poll = 0.05
        return TestClient(api.create_app(connect=connect, jobs=runner))
    yield build, {"Authorization": f"Bearer {tok}"}, hold
    hold.set()


@pytest.mark.db
def test_the_one_shot_answer_hands_back_the_job_when_it_cant_wait(answering):
    build, agent, hold = answering
    c = build(max_waiters=1, per_client=50, anonymous_waiting=50)
    first = {}
    t = threading.Thread(target=lambda: first.update(r=c.post("/v1/answer", json={"question": "slow one"},
                                                              headers=agent)))
    t.start()
    end = time.monotonic() + 5
    while not c.app.state.jobs._waiters and time.monotonic() < end:
        time.sleep(0.02)
    r = c.post("/v1/answer", json={"question": "another"})               # nobody else may wait: poll instead
    body = r.json()
    assert r.status_code == 202 and body["status"] in ("queued", "running") and body["poll"] == f"/v1/answers/{body['job_id']}"
    hold.set()
    t.join(10)
    assert first["r"].status_code == 200 and first["r"].json() == {"ok": True, "question": "slow one"}
    done = c.post("/v1/answer", json={"question": "another"})            # finished meanwhile: the answer itself
    assert done.status_code == 200 and done.json() == {"ok": True, "question": "another"}


@pytest.mark.db
def test_the_one_shot_answer_waits_only_so_long(answering, monkeypatch):
    build, agent, hold = answering
    monkeypatch.setattr(jobs, "WAIT", 0.3)
    c = build()
    r = c.post("/v1/answer", json={"question": "slow"}, headers=agent)
    assert r.status_code == 202 and r.json()["reused"] is False
    assert c.get(r.json()["poll"]).json()["status"] in ("queued", "running")


def test_waiting_is_limited_per_client_and_overall():
    runner = jobs.AnswerJobs(lambda: None, lambda: None, lambda *a: None, max_waiters=2, waiters_per_client=1)
    runner.get = lambda job_id: {"status": "running"}
    runner.poll = 0.01
    out = {}
    a = threading.Thread(target=lambda: out.update(a=runner.wait("j", "ip:1", timeout=0.5)))
    a.start()
    time.sleep(0.1)
    assert runner.wait("j", "ip:1", timeout=0.5) is None                # one per client
    b = threading.Thread(target=lambda: out.update(b=runner.wait("j", "ip:2", timeout=0.5)))
    b.start()
    time.sleep(0.1)
    assert runner.wait("j", "ip:3", timeout=0.5) is None                # and only so many overall
    a.join()
    b.join()
    assert out["a"]["status"] == "running" and not runner._waiters      # timed out, and their places freed


@pytest.mark.db
def test_unvetted_agents_get_a_visitors_share_of_the_queue(answering):
    build, agent, hold = answering
    c = build(per_client=1, anonymous_waiting=50)
    key = c.post("/v1/agents/register", json={"handle": "newcomer", "model": "acme/m1"}).json()["key"]
    newcomer = {"Authorization": f"Bearer {key}"}
    assert c.post("/v1/answers", json={"question": "n1"}, headers=newcomer).status_code == 202
    r = c.post("/v1/answers", json={"question": "n2"}, headers=newcomer)
    assert r.status_code == 429 and "last 10 minutes" in r.json()["error"]
    for i in range(3):                                                  # a vetted agent's key: the full queue
        assert c.post("/v1/answers", json={"question": f"v{i}"}, headers=agent).status_code == 202


# --- signing up ------------------------------------------------------------------------------------------------------

def test_clients_are_grouped_by_network():
    assert onboarding.subnet("ip:198.51.100.7") == onboarding.subnet("ip:198.51.100.200") == "net:198.51.100.0/24"
    assert onboarding.subnet("ip:::ffff:198.51.100.9") == "net:198.51.100.0/24"
    assert onboarding.subnet("ip:2001:db8:1:2::5") == "net:2001:db8:1::/48"
    assert onboarding.subnet("testclient") == "testclient"


@pytest.mark.db
def test_sign_ups_are_limited_per_network_and_newcomers_get_past_the_daily_ceiling(conn, monkeypatch):
    db.migrate(conn)
    conn.commit()
    monkeypatch.setattr(onboarding, "SIGNUPS_PER_SUBNET_DAY", 3)
    monkeypatch.setattr(onboarding, "SIGNUPS_NETWORK_PER_DAY", 4)
    monkeypatch.setattr(onboarding, "SIGNUPS_FIRST_PER_DAY", 6)

    def sign_up(client, handle):
        try:
            onboarding.register(conn, client, handle, "model")
            conn.commit()
            return True
        except Refused as e:
            conn.rollback()
            return str(e)
    assert all(sign_up(f"ip:198.51.100.{i}", f"near-{i}") is True for i in range(3))
    assert "this network" in sign_up("ip:198.51.100.50", "near-x")      # the same /24, another address
    assert sign_up("ip:203.0.113.1", "far-1") is True
    assert "across the network" in sign_up("ip:203.0.113.1", "far-2")   # 4 today: repeat sign-ups wait
    assert sign_up("ip:192.0.2.1", "new-1") is True                      # a client's first today still gets in
    assert sign_up("ip:192.0.2.2", "new-2") is True
    assert "across the network" in sign_up("ip:192.0.2.3", "new-3")     # up to the higher ceiling


@pytest.mark.db
def test_sign_ups_at_the_same_moment_cannot_both_pass_the_count(db_url, monkeypatch):
    with psycopg.connect(db_url) as c:
        db.migrate(c)
    monkeypatch.setattr(onboarding, "SIGNUPS_PER_HOUR", 1)
    results, go = [], threading.Barrier(4)

    def sign_up(i):
        with psycopg.connect(db_url) as c:
            go.wait()
            try:
                onboarding.register(c, "ip:198.51.100.1", f"racer-{i}", "model")
                time.sleep(0.2)                                          # hold the transaction open a moment
                results.append(True)
            except Refused:
                c.rollback()
                results.append(False)
    threads = [threading.Thread(target=sign_up, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [False, False, False, True]
