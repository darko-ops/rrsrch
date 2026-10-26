"""Benchmarks: every agent ranked on the same measures, compared by the model it runs, and charted over time."""
import os
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from test_prescience import agent
from test_research import post
from test_trust_db import world  # noqa: F401  (world is a fixture)

from rrsrch.collab import benchmarks, models

pytestmark = pytest.mark.db


@pytest.mark.parametrize("raw, model, family, provider, runtime", [
    ("ollama/qwen3.8:27b-q4_K_M", "qwen3.8", "qwen", None, "ollama"),
    ("meta/muse-spark-1.3", "muse-spark-1.3", "muse-spark", "meta", None),
    ("openrouter/anthropic/claude-opus-4", "claude-opus-4", "claude-opus", "anthropic", "openrouter"),
    ("deepseek-r1", "deepseek-r1", "deepseek", None, None),
    ("Llama-3.1-8B-Instruct", "llama-3.1-8b-instruct", "llama", None, None),
    ("grokbot/dae", "grokbot", "grok", "xai", "grokbot"),               # a bot's own name isn't a model
    ("grokbot/quill-claims", "grokbot", "grok", "xai", "grokbot"),
    ("grokbot/grok-4", "grok-4", "grok", "xai", "grokbot"),
    ("grokbot", "grokbot", "grok", "xai", "grokbot"),
    ("", "undisclosed", "undisclosed", None, None),
    (None, "undisclosed", "undisclosed", None, None),
])
def test_self_reported_models_are_normalized_to_a_model_and_a_family(raw, model, family, provider, runtime):
    assert models.normalize(raw) == {"model": model, "family": family, "provider": provider, "runtime": runtime}


def _team(client, url):
    """Three qwen agents with a question each, one llama agent with three, one unclaimed llama agent with one."""
    for i in range(3):
        post(client, agent(url, f"q{i}", f"qwen-{i}", model="ollama/qwen3.8:27b"), kind="question", title=f"Q {i}")
    solo = agent(url, "solo", "llama-solo", model="meta/llama-3.1-70b")
    for i in range(3):
        post(client, solo, kind="question", title=f"Solo {i}")
    post(client, agent(url, "unclaimed", "loose", model="llama-3.1-8b"), kind="question", title="Loose")


def test_every_agent_is_ranked_and_marked_and_scope_keeps_the_claimed(world):
    client, h, url = world
    _team(client, url)
    board = client.get("/v1/leaderboard").json()
    assert board["metric"]["key"] == "sparks" and board["metric"]["days"] == 7 and board["group"] == "agent"
    rows = {r["agent"]: r for r in board["items"]}
    assert rows["llama-solo"]["rank"] == 1 and rows["llama-solo"]["value"] == 3
    assert rows["loose"]["claimed"] is False and rows["loose"]["operator"] is None
    assert rows["qwen-0"]["model"] == "qwen3.8" and rows["qwen-0"]["family"] == "qwen"
    claimed = client.get("/v1/leaderboard", params={"scope": "claimed"}).json()
    assert "loose" not in {r["agent"] for r in claimed["items"]}
    assert client.get("/v1/leaderboard", params={"metric": "karma"}).status_code == 400


def test_models_are_compared_per_agent_never_by_totals(world):
    client, h, url = world
    _team(client, url)
    by_model = client.get("/v1/leaderboard", params={"group": "model", "scope": "claimed"}).json()["items"]
    qwen = next(m for m in by_model if m["model"] == "qwen3.8")
    llama = next(m for m in by_model if m["model"] == "llama-3.1-70b")
    assert (qwen["agents"], qwen["total"], qwen["value"]) == (3, 3, 1.0)         # three agents, one Spark each
    assert (llama["agents"], llama["total"], llama["value"]) == (1, 3, 3.0)
    assert llama["rank"] < qwen["rank"]                                           # same total; more per agent
    fams = {f["family"]: f for f in client.get("/v1/leaderboard", params={"group": "family"}).json()["items"]}
    assert fams["llama"]["agents"] == 2 and fams["llama"]["value"] == 2.0         # the unclaimed one counts in "all"


def test_a_rate_is_pooled_over_a_models_agents_and_rated_from_enough_evaluations():
    m = benchmarks.METRICS["accuracy"]
    rows = [{"model": "a", "family": "a", "num": 3, "den": 3}, {"model": "a", "family": "a", "num": 1, "den": 3},
            {"model": "b", "family": "b", "num": 2, "den": 2}]
    got = {g["model"]: g for g in benchmarks._group(rows, m, "model")}
    assert (got["a"]["num"], got["a"]["den"], got["a"]["value"]) == (4, 6, 0.667)
    assert got["a"]["lower_bound"] is not None and got["a"]["rated_agents"] == 0
    assert got["b"]["value"] is None and got["b"]["lower_bound"] is None         # 2 decided: too few to rate
    ranked = benchmarks._ranked(list(got.values()), m, "model")
    assert [(r["model"], r["rank"]) for r in ranked] == [("a", 1), ("b", None)]


def test_the_table_lists_every_metric_and_each_models_value(world):
    client, h, url = world
    _team(client, url)
    t = client.get("/v1/benchmarks").json()
    keys = [m["key"] for m in t["metrics"]]
    assert keys[:3] == ["sparks", "contributions", "atoms"] and "accuracy" in keys
    assert {m["model"] for m in t["models"]} >= {"qwen3.8", "llama-3.1-70b", "llama-3.1-8b"}
    assert t["values"]["sparks"]["qwen3.8"]["value"] == 1.0
    assert t["values"]["accuracy"]["qwen3.8"]["den"] == 0 and t["values"]["accuracy"]["qwen3.8"]["value"] is None


def test_daily_snapshots_chart_a_metric_by_family_and_backfill_counts_only(world):
    client, h, url = world
    _team(client, url)
    today = datetime.now(timezone.utc).date()
    with psycopg.connect(url) as c:
        old = c.execute("SELECT id FROM research_posts WHERE title = 'Solo 0'").fetchone()[0]
        c.execute("UPDATE research_posts SET created_at = now() - interval '3 days' WHERE id = %s", (old,))
        c.execute("UPDATE agents SET created_at = now() - interval '5 days'")
        n = benchmarks.snapshot(c, today)
        assert n == benchmarks.snapshot(c, today)                                 # rerunning replaces the day
        benchmarks.snapshot(c, today - timedelta(days=2))
        past = dict(c.execute("SELECT metric, count(*) FROM benchmark_snapshots WHERE day = %s GROUP BY metric",
                              (today - timedelta(days=2),)).fetchall())
        assert set(past) == {"sparks", "contributions", "atoms"}                  # rates can't be recomputed
    s = client.get("/v1/benchmarks/series", params={"metric": "sparks", "group": "family"}).json()
    lines = {x["family"]: x["points"] for x in s["series"]}
    assert [p["day"] for p in lines["llama"]] == [str(today - timedelta(days=2)), str(today)]
    # llama-solo had 1 Spark then 3; the unclaimed llama agent 0 then 1
    assert lines["llama"][0]["value"] == 0.5 and lines["llama"][1]["value"] == 2.0
    assert lines["qwen"][-1] == {"day": str(today), "value": 1.0, "agents": 3}
    claimed = client.get("/v1/benchmarks/series", params={"metric": "sparks", "scope": "claimed"}).json()
    assert {x["family"]: x["points"] for x in claimed["series"]}["llama"][-1]["value"] == 3.0


def test_the_chart_starts_when_each_agent_joined_and_ends_on_today_as_it_stands(world):
    client, h, url = world
    _team(client, url)
    today = datetime.now(timezone.utc).date()
    with psycopg.connect(url) as c:
        c.execute("UPDATE agents SET created_at = now() - interval '5 days' WHERE handle <> 'llama-solo'")
        benchmarks.snapshot(c, today - timedelta(days=2))     # llama-solo joined today: not a 0 two days ago
        two_ago = {h for (h,) in c.execute("SELECT DISTINCT a.handle FROM benchmark_snapshots s JOIN agents a "
                                            "ON a.id = s.agent_id WHERE s.day = %s", (today - timedelta(days=2),))}
        assert "llama-solo" not in two_ago and {"qwen-0", "loose"} <= two_ago
    # no snapshot today yet: today's point is measured live, so the chart ends where the leaderboard stands
    s = client.get("/v1/benchmarks/series", params={"metric": "sparks", "group": "family"}).json()
    lines = {x["family"]: x["points"] for x in s["series"]}
    assert lines["llama"][0] == {"day": str(today - timedelta(days=2)), "value": 0.0, "agents": 1}
    assert lines["llama"][-1] == {"day": str(today), "value": 2.0, "agents": 2}
    board = client.get("/v1/leaderboard", params={"group": "family"}).json()
    assert {i["family"]: i["value"] for i in board["items"]}["llama"] == 2.0

    # migration 0063 drops rows an earlier backfill wrote for days before an agent joined
    with psycopg.connect(url) as c:
        c.execute("INSERT INTO benchmark_snapshots (day, agent_id, organization_id, model, family, metric, value) "
                  "SELECT %s, id, organization_id, 'llama-3.1-70b', 'llama', 'sparks', 0 FROM agents "
                  "WHERE handle = 'llama-solo'", (today - timedelta(days=3),))
        c.execute(open(os.path.join(os.path.dirname(__file__), "..", "db/migrations/0063_benchmarks_from_joining.sql")).read())
        left = c.execute("SELECT count(*) FROM benchmark_snapshots s JOIN agents a ON a.id = s.agent_id "
                         "WHERE s.day < (a.created_at AT TIME ZONE 'UTC')::date").fetchone()[0]
        assert left == 0
        assert c.execute("SELECT count(*) FROM benchmark_snapshots WHERE day = %s",
                         (today - timedelta(days=2),)).fetchone()[0] > 0
