"""The Agents page's activity: an agent's work per day, and an organization's latest events, both only in
repositories the viewer can read."""
import psycopg
import pytest
from test_trust_db import PILOT, content, open_mr, world  # noqa: F401  (world is a fixture)

pytestmark = pytest.mark.db


def test_an_agents_days_show_how_much_it_did_and_how_it_stands(world):
    client, h, url = world
    mr = open_mr(client, h["bot"], {"repository": PILOT, "content": content()})
    open_mr(client, h["bot"], {"repository": PILOT, "content": content("At 12 months, WOMAC was better with MSCs.")})
    client.post("/v1/reviews", headers=h["ext"], json={"target": f"proposal:{mr}", "verdict": "approve"})
    days = client.get("/v1/agents/bot/activity", params={"days": 3}).json()["days"]
    assert len(days) == 3 and days[0]["count"] == 0 and days[0]["outcome"] is None
    assert (days[-1]["count"], days[-1]["outcome"]) == (2, "waiting")                    # today: two open proposals
    ext_today = client.get("/v1/agents/ext/activity", params={"days": 1}).json()["days"][-1]
    assert (ext_today["count"], ext_today["outcome"]) == (1, "active")                  # a review: work, no claim state
    with psycopg.connect(url) as c:
        c.execute("UPDATE merge_requests SET state = 'rejected', decided_at = now() WHERE id = %s", (mr,))
    assert client.get("/v1/agents/bot/activity", params={"days": 1}).json()["days"][-1]["outcome"] == "rejected"
    assert client.get("/v1/agents/nobody/activity").status_code == 404


def test_an_organizations_latest_events_say_who_did_what(world):
    client, h, url = world
    mr = open_mr(client, h["bot"], {"repository": PILOT, "content": content()})
    client.post("/v1/posts", headers=h["bot"], json={"kind": "question", "title": "Do MSC gains last 5 years?",
                                                       "body": "Long-term knee outcomes.", "topics": ["knee-oa"]})
    client.post("/v1/reviews", headers=h["ext"], json={"target": f"proposal:{mr}", "verdict": "approve"})
    items = client.get("/v1/organizations/rrsrch/activity").json()["items"]
    assert [(i["handle"], i["verb"]) for i in items] == [("bot", "asked"), ("bot", "proposed")]   # lab's review isn't rrsrch's
    assert items[0]["target"].startswith("post:") and items[1]["title"].startswith("At 12 months")
    lab = client.get("/v1/organizations/lab/activity").json()["items"]
    assert [(i["handle"], i["verb"], i["title"]) for i in lab] == [("ext", "approved", f"proposal {mr}")]
    assert client.get("/v1/organizations/nope/activity").status_code == 404


def test_private_work_stays_out_of_activity(world):
    client, h, url = world
    new = {"slug": "rrsrch/notes", "topic": "notes", "visibility": "private",
           "policy": {"required_approvals": 0, "evidence_gate": False}}
    assert client.post("/v1/repos", headers=h["admin"], json=new).status_code == 201
    with psycopg.connect(url) as c:
        c.execute("INSERT INTO research_posts (repository_id, author_id, kind, title, body, content_hash) "
                  "SELECT r.id, a.id, 'finding', 'secret', 'b', 'x' FROM repositories r, agents a "
                  "WHERE r.slug = 'rrsrch/notes' AND a.handle = 'admin'")
    assert client.get("/v1/organizations/rrsrch/activity").json()["items"] == []                    # anonymous
    assert client.get("/v1/agents/admin/activity", params={"days": 1}).json()["days"][-1]["count"] == 0
    mine = client.get("/v1/organizations/rrsrch/activity", headers=h["admin"]).json()["items"]
    assert [i["title"] for i in mine] == ["secret"]                                                 # its own admin
