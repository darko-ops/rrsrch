"""Read endpoints the site dashboard needs: agents, keys, merge-request lists and the repository atlas."""
import psycopg
import pytest
from reviewing import object_to, report, reports  # noqa: F401
from test_knowledge_api import claim_of, merged_claim
from test_trust_db import PILOT, content, open_mr, world  # noqa: F401  (world is a fixture)

pytestmark = pytest.mark.db


def test_agents_are_listed_publicly(world):
    client, _, _ = world
    got = client.get("/v1/agents", params={"organization": "rrsrch"}).json()["items"]
    assert [a["handle"] for a in got] == ["rrsrch-reader", "bot", "admin"]
    assert "org_role" not in got[0]                                   # the public profile only
    assert [a["handle"] for a in client.get("/v1/agents", params={"organization": "lab"}).json()["items"]] == ["ext"]
    page = client.get("/v1/agents", params={"limit": 2}).json()
    assert len(page["items"]) == 2 and client.get("/v1/agents", params={"after": page["next"]}).json()["items"]


def test_keys_are_listed_to_their_agent_and_its_admins_never_with_secrets(world):
    client, h, _ = world
    mine = client.get("/v1/agents/bot/keys", headers=h["bot"]).json()["keys"]
    assert len(mine) == 1 and set(mine[0]) == {"id", "prefix", "scopes", "label", "created_at", "expires_at",
                                               "revoked_at", "last_used_at"}
    assert h["bot"]["Authorization"].split("_")[1] == mine[0]["prefix"]
    assert client.get("/v1/agents/bot/keys", headers=h["admin"]).status_code == 200      # rrsrch admin
    assert client.get("/v1/agents/bot/keys", headers=h["ext"]).status_code == 403        # another org's agent
    assert client.get("/v1/agents/bot/keys").status_code == 401
    assert client.get("/v1/agents/nobody/keys", headers=h["admin"]).status_code == 404


def test_merge_requests_are_listed_by_state(world):
    client, h, _ = world
    rev, merged = merged_claim(client, h)
    pending = open_mr(client, h["bot"], {"repository": PILOT, "content": content()})
    client.post("/v1/reviews", headers=h["ext"], json={"target": f"proposal:{pending}", "verdict": "request_changes"})
    open_ = client.get(f"/v1/repos/{PILOT}/merge-requests").json()["items"]
    assert [(m["id"], m["author"], m["approvals"], m["objections"], m["checks_passed"]) for m in open_] == \
        [(pending, "bot", 0, 1, True)]
    assert [m["id"] for m in client.get(f"/v1/repos/{PILOT}/merge-requests", params={"state": "merged"}).json()["items"]] \
        == [merged]
    assert client.get("/v1/repos/nope/none/merge-requests").status_code == 404


def test_atlas_maps_a_repository(world):
    client, h, url = world
    a = claim_of(url, merged_claim(client, h)[0])
    body = content("WOMAC improved more with MSCs than with hyaluronic acid at 12 months (p = 0.01).")
    body["derived_from"] = [a]
    mr = open_mr(client, h["bot"], {"repository": PILOT, "content": body})
    client.post("/v1/reviews", headers=h["ext"], json={"target": f"proposal:{mr}", "verdict": "approve"})
    b = claim_of(url, client.post(f"/v1/merge-requests/{mr}/merge", headers=h["admin"]).json()["revision_id"])
    with psycopg.connect(url) as c:
        c.execute("INSERT INTO trials (nct_id, has_results, snapshot_sha256) VALUES ('NCT01', false, 'x')")
        c.execute("INSERT INTO trial_links VALUES ('NCT01', 'MED:1', 'nct_in_abstract')")
        c.execute("INSERT INTO claim_agreements (claim_a_id, claim_b_id, verdict, rule, detail, evidence, rules) "
                  "VALUES (%s, %s, 'agrees', 'direction', 't', '{}', 'v1')", (min(a, b), max(a, b)))
    object_to(client, h["ext"], a, **{"kind": "scope", "statement": "n=40"})

    g = client.get(f"/v1/repos/{PILOT}/atlas").json()
    assert g["counts"] == {"claim": 2, "agent": 1, "source": 1, "trial": 1} and g["truncated"] is False
    edges = {(e["from"], e["rel"], e["to"]) for e in g["edges"]}
    assert {(f"claim:{a}", "supports", "source:MED:1"), ("source:MED:1", "reports", "trial:NCT01"),
            ("agent:bot", "authored", f"claim:{b}"), (f"claim:{b}", "derived_from", f"claim:{a}"),
            (f"claim:{min(a, b)}", "agrees", f"claim:{max(a, b)}")} <= edges
    claim_a = next(n for n in g["nodes"] if n["id"] == f"claim:{a}")
    assert claim_a["state"] == "contested" and claim_a["open_challenges"] == 1
    small = client.get(f"/v1/repos/{PILOT}/atlas", params={"limit": 1}).json()
    assert small["truncated"] is True and small["counts"]["claim"] == 1
    assert client.get("/v1/repos/nope/none/atlas").status_code == 404
