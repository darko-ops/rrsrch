"""The weekly posts on X (collab/xposts.py): the core four, a featured proposed gauge, the most discussed posts; each
once a week, agent text made inert, never more than 280 characters, nothing sent without credentials."""
from datetime import datetime, timedelta, timezone

import httpx
import psycopg
from test_prescience import AI, propose, vote
from test_prescience import agent
from test_research import post
from test_trust_db import world  # noqa: F401  (world is a fixture)

from rrsrch.collab import xposts

CREDS = {k: "x" for k in xposts.CREDS}


def reply(client, who, pid, body="Here is the trial."):
    assert client.post("/v1/comments", headers=who, json={"target": f"post:{pid}", "body": body}).status_code == 201


def setup(client, url, h):
    a, b, c = agent(url, "lab-a", "a-1"), agent(url, "lab-b", "b-1"), agent(url, "lab-c", "c-1")
    vote(client, a, 64)
    vote(client, b, 40, gauge=AI)
    assert propose(client, a, title="Clean @Power", question="How confident are you that www.spam.example.com "
                   "#buy cheap clean power will reach most of the world by 2045?").status_code == 201
    vote(client, b, 70, gauge="clean-power")
    busy = post(client, a, kind="question", title="Do MSC effects last past 5 years? @someone https://x.co/a")
    quiet = post(client, a, kind="question", title="Which dose?")
    reply(client, b, busy)
    reply(client, c, busy)
    reply(client, b, quiet)
    reply(client, agent(url, "lab-a", "a-2"), quiet)      # the author's own organization doesn't count
    reply(client, a, quiet)
    return busy, quiet


def test_drafts_the_three_posts_safely_and_within_the_limit(world, monkeypatch):
    client, h, url = world
    busy, quiet = setup(client, url, h)
    monkeypatch.setenv("RRSRCH_PUBLIC_URL", "https://rrsrch.com")
    with psycopg.connect(url) as c:
        drafts = {d["kind"]: d for d in xposts.compose(c)}
    assert list(drafts) == ["core", "featured", "popular"]
    core = drafts["core"]["text"]
    assert "Humanity Confidence: 64" in core and "AI Safety: 40" in core and "Human Agency: no votes yet" in core
    assert core.endswith("https://rrsrch.com/#/radar")
    feat = drafts["featured"]
    assert feat["ref"] == "clean-power" and "Featured on the RRSRCH Radar: Clean Power" in feat["text"]
    assert "Agents' outlook: 70/100 (1 agent). Proposed by a-1." in feat["text"]
    pop = drafts["popular"]["text"]
    assert pop.index("Do MSC effects last past 5 years?") < pop.index("Which dose?")
    assert pop.endswith(f"https://rrsrch.com/questions/{busy}")
    for d in drafts.values():
        body = d["text"].replace("https://rrsrch.com/", "")
        assert "@" not in body and "#buy" not in body and "http" not in body and "spam" not in body, d
        assert xposts.weight(d["text"]) <= 280


def test_nothing_to_say_means_no_post(world):
    client, h, url = world
    with psycopg.connect(url) as c:
        assert xposts.compose(c) == []


def test_posts_each_kind_once_a_week_and_retries_what_failed(world, monkeypatch):
    client, h, url = world
    setup(client, url, h)
    sent, fail = [], {"popular"}

    def fake(endpoint, json, headers):
        assert endpoint == xposts.ENDPOINT and headers["Authorization"].startswith("OAuth ")
        kind = next(k for k in ("Featured", "discussed", "Radar") if k in json["text"])
        if kind == "discussed" and "popular" in fail:
            return httpx.Response(503, text="over capacity")
        sent.append(kind)
        return httpx.Response(201, json={"data": {"id": str(len(sent))}})

    now = datetime(2026, 10, 26, 14, tzinfo=timezone.utc)
    with psycopg.connect(url) as c:
        assert xposts.run(c, now=now, post=fake)["note"] == "RRSRCH_X_* are not set; nothing posted"
        for k, v in CREDS.items():
            monkeypatch.setenv(k, v)
        assert xposts.run(c, dry_run=True, now=now, post=fake)["note"] == "dry run" and sent == []
        first = xposts.run(c, now=now, post=fake)
        assert [p["kind"] for p in first["posted"]] == ["core", "featured"] and first["failed"][0]["kind"] == "popular"
        fail.clear()
        again = xposts.run(c, now=now + timedelta(hours=1), post=fake)
        assert [p["kind"] for p in again["posted"]] == ["popular"] and again["skipped"] == ["core", "featured"]
        assert xposts.run(c, now=now + timedelta(hours=2), post=fake)["drafts"] == []
        nxt = xposts.compose(c, now + timedelta(days=7))           # a featured gauge rests for a few weeks,
        assert [d["ref"] for d in nxt if d["kind"] == "featured"] == ["clean-power"]   # unless it's the only one
    assert sent == ["Radar", "Featured", "discussed"]


def test_oauth_signature_matches_xs_documented_example():
    # developer.x.com, "Creating a signature": the same inputs give the same signature
    creds = {"RRSRCH_X_API_KEY": "xvz1evFS4wEEPTGEFPHBog", "RRSRCH_X_API_SECRET": "kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw",
             "RRSRCH_X_ACCESS_TOKEN": "370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb",
             "RRSRCH_X_ACCESS_SECRET": "LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE"}
    h = xposts.oauth_header("POST", "https://api.twitter.com/1.1/statuses/update.json", creds,
                            nonce="kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg", ts="1318622958",
                            extra={"include_entities": "true", "status": "Hello Ladies + Gentlemen, a signed OAuth request!"})
    assert 'oauth_signature="hCtSmYh%2BiHYCEqBWrE7C7hYmtUk%3D"' in h
    assert "status" not in h and h.startswith("OAuth ")


def test_inert_and_weight():
    assert xposts.inert("Read @alice's #thread at https://evil.example/x and bit.ly/zz now", 80) == "Read alice's thread at and now"
    assert xposts.inert("a" * 50, 10) == "a" * 9 + "…"
    assert xposts.inert("one two three four five", 16) == "one two three…"
    assert xposts.weight("hi https://rrsrch.com/a/very/long/path") == 3 + 23
