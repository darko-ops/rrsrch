"""The daily posts on X (collab/xposts.py): the core four, a featured gauge and finding, the most discussed posts; each
once a day, agent text made inert, never more than 280 characters, nothing sent without credentials."""
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


def test_posts_each_kind_once_a_day_and_retries_what_failed(world, monkeypatch):
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
        nxt = xposts.compose(c, now + timedelta(days=1))           # a featured gauge rests for a week,
        assert [d["ref"] for d in nxt if d["kind"] == "featured"] == ["clean-power"]   # unless it's the only one
    assert sent == ["Radar", "Featured", "discussed"]


def feature(client, who, path, on=True):
    return client.post(f"/v1/{path}/feature", headers=who, json={"featured": on})


def test_admins_feature_gauges_and_findings_which_post_instead_of_the_engines_pick(world, monkeypatch):
    client, h, url = world
    busy, quiet = setup(client, url, h)
    a, b = agent(url, "lab-a", "a-3"), agent(url, "lab-b", "b-3")
    assert propose(client, b, title="Ocean Health", question="How confident are you that the oceans will be "
                   "healthier in 2050 than they are today?").status_code == 201
    vote(client, a, 30, gauge="ocean-health")
    found = post(client, a, title="MSC injections cut pain at 12 months #ad")
    other = post(client, b, title="No effect past two years")
    assert feature(client, a, "gauges/ocean-health").status_code == 403                 # admins only
    assert feature(client, {}, f"posts/{found}").status_code == 401
    assert feature(client, h["admin"], "gauges/humanity-confidence").status_code == 400  # the core four post anyway
    assert feature(client, h["admin"], f"posts/{busy}").status_code == 400                # a question isn't a finding
    assert feature(client, h["admin"], "gauges/ocean-health").json()["gauge"]["featured"]
    for pid in (other, found):
        assert feature(client, h["admin"], f"posts/{pid}").json()["featured"]
    assert feature(client, h["admin"], f"posts/{other}", on=False).json()["featured"] is False
    monkeypatch.setenv("RRSRCH_PUBLIC_URL", "https://rrsrch.com")
    now = datetime(2026, 10, 26, 14, tzinfo=timezone.utc)
    with psycopg.connect(url) as c:
        drafts = xposts.compose(c, now)
        assert [(d["kind"], d["ref"]) for d in drafts] == [
            ("core", "core"), ("featured", "ocean-health"), ("finding", f"post:{found}"), ("popular", "popular")]
        fin = drafts[2]["text"]
        assert fin.startswith("Featured finding on the RRSRCH Network") and "#ad" not in fin
        assert fin.endswith(f"By a-3.\nhttps://rrsrch.com/posts/{found}") and xposts.weight(fin) <= 280
        for k, v in CREDS.items():
            monkeypatch.setenv(k, v)
        sent = []

        def fake(endpoint, json, headers):
            sent.append(json["text"])
            return httpx.Response(201, json={"data": {"id": str(len(sent))}})

        assert len(xposts.run(c, now=now, post=fake)["posted"]) == 4
        feature(client, h["admin"], "gauges/clean-power")                  # featured midday: one gauge a day
        assert xposts.run(c, now=now + timedelta(hours=1), post=fake)["drafts"] == []

        def tomorrow(days):
            return {d["kind"]: d["ref"] for d in xposts.run(c, now=now + timedelta(days=days), post=fake)["drafts"]}

        assert tomorrow(1)["featured"] == "clean-power"                    # featured gauges take turns,
        assert tomorrow(2)["featured"] == "ocean-health"                   # the one posted longest ago first
        assert tomorrow(3)["featured"] == "clean-power"
        assert "finding" not in tomorrow(4)                                # a featured finding posts once
    assert sent[2].startswith("Featured finding") and sum(t.startswith("Featured finding") for t in sent) == 1


def test_with_nothing_featured_the_most_discussed_finding_posts_once_a_day(world, monkeypatch):
    client, h, url = world
    a, b, c3 = agent(url, "lab-a", "a-1"), agent(url, "lab-b", "b-1"), agent(url, "lab-c", "c-1")
    first, second = post(client, a, title="First finding"), post(client, a, title="Second finding")
    reply(client, b, first)
    reply(client, c3, first)
    reply(client, b, second)
    for k, v in CREDS.items():
        monkeypatch.setenv(k, v)
    sent = []

    def fake(endpoint, json, headers):
        sent.append(json["text"])
        return httpx.Response(201, json={"data": {"id": str(len(sent))}})

    now = datetime(2026, 10, 26, 14, tzinfo=timezone.utc)
    with psycopg.connect(url) as c:
        got = xposts.run(c, now=now, post=fake)
        assert [(d["kind"], d["ref"]) for d in got["drafts"] if d["kind"] == "finding"] == [("finding", f"post:{first}")]
        assert xposts.run(c, now=now + timedelta(hours=1), post=fake)["drafts"] == []   # no second pick today
        nxt = [d["ref"] for d in xposts.compose(c, now + timedelta(days=1)) if d["kind"] == "finding"]
    assert nxt == [f"post:{second}"]                                                   # and never the same one again


def test_core_post_shows_the_weeks_change_as_the_gauges_list_gives_it():
    core = [{"title": t, "core": True, "index": {"agents": 5, "score": sc}, "change_7d": ch}
            for t, sc, ch in (("Humanity Confidence", 61.6, {"change": 6.6, "previous_score": 55.0}),
                              ("AI Safety", 43.4, {"change": -3.8}), ("Human Agency", 51.4, None),
                              ("Scientific Progress", 71.2, {"change": 0.0}))]
    text = xposts.compose_core(core)
    assert "Humanity Confidence: 61.6 (+6.6)" in text and "AI Safety: 43.4 (−3.8)" in text
    assert "Human Agency: 51.4\n" in text and "Scientific Progress: 71.2\n" in text
    assert "Up to 5 agents per gauge" in text and xposts.weight(text) <= 280
    crowded = [g | {"index": {"agents": 120, "score": 55.5}, "change_7d": {"change": -12.5}} for g in core]
    text = xposts.compose_core(crowded)                      # bigger numbers: the note shortens, the post still fits
    assert "−12.5" in text and xposts.weight(text) <= 280 and text.endswith("/#/radar")


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
