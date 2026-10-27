"""Research Missions (docs/MISSIONS.md): a defined objective in a topic that gathers questions, findings and claims."""
import psycopg
import pytest
from test_prescience import agent
from test_research import post
from test_trust_db import content, open_mr, world  # noqa: F401  (world is a fixture)

from rrsrch.collab import missions

pytestmark = pytest.mark.db

MISSION = {"title": "Do senolytic therapies produce reproducible benefits in mammals?",
           "objective": "Evaluate controlled studies and whether reported benefits replicate across labs.",
           "topic": "medicine", "scope": "2018-2026; controlled studies; two operators review.",
           "success_criteria": ["A documented literature search", "An independently reviewed report"],
           "deliverable": "Evidence synthesis v1"}


def propose(client, who, **extra):
    return client.post("/v1/missions", headers=who, json=MISSION | extra)


def test_a_claimed_agent_proposes_a_mission_with_criteria_and_its_duplicates_are_refused(world):
    client, h, url = world
    lab = agent(url, "lab", "lab-bot")
    r = propose(client, lab)
    assert r.status_code == 201, r.json()
    m = r.json()["mission"]
    assert m["status"] == "open" and not m["featured"] and m["proposed_by"] == "lab-bot" and m["topic"] == "medicine"
    assert m["success_criteria"] == MISSION["success_criteria"] and r.json()["progress"]["questions"] == 0
    dup = propose(client, h["bot"], title="  do senolytic   therapies produce reproducible benefits in MAMMALS? ")
    assert dup.status_code == 409 and f"mission {m['id']}" in dup.json()["error"]
    assert propose(client, h["bot"], title="Another mission entirely", success_criteria=[]).status_code == 400
    assert propose(client, h["bot"], title="Another mission entirely", topic="astrology").status_code == 400
    assert propose(client, agent(url, "unclaimed", "drifter"), title="Unclaimed agents can't").status_code == 403
    assert propose(client, {}, title="Nobody signed in").status_code == 401
    for i in range(2):
        assert propose(client, lab, title=f"Lab mission number {i}").status_code == 201
    assert propose(client, lab, title="One too many this week").status_code == 429


def test_work_joins_by_its_author_or_the_proposer_and_shows_with_bounties_and_progress(world):
    client, h, url = world
    lab, other = agent(url, "lab", "lab-bot"), agent(url, "other", "other-bot")
    mid = propose(client, lab).json()["mission"]["id"]
    # an author posts straight into the mission
    q = post(client, other, title="Which controlled mammalian studies exist?", kind="question", mission=mid)
    f = post(client, other, title="Three replications found in mice")
    # someone else's work: only the proposer adds it
    assert client.post(f"/v1/missions/{mid}/items", headers=h["bot"], json={"target": f"post:{f}"}).status_code == 403
    assert client.post(f"/v1/missions/{mid}/items", headers=lab, json={"target": f"post:{f}"}).status_code == 201
    again = client.post(f"/v1/missions/{mid}/items", headers=lab, json={"target": f"post:{f}"})
    assert again.status_code == 200 and again.json()["added"] is False
    assert client.post(f"/v1/missions/{mid}/items", headers=lab, json={"target": "post:999999"}).status_code == 404
    assert client.post(f"/v1/missions/{mid}/items", headers=lab, json={"target": "repo:x"}).status_code == 400
    # a claim joins through the agent that contributed it
    mr = open_mr(client, h["bot"], {"repository": "rrsrch/msc-knee-oa", "content": content()})
    client.post("/v1/reviews", headers=h["ext"], json={"target": f"proposal:{mr}", "verdict": "approve",
                                                       "findings": "span matches"})
    assert client.post(f"/v1/merge-requests/{mr}/merge", headers=h["admin"]).status_code == 200
    with psycopg.connect(url) as c:
        claim = c.execute("SELECT max(id) FROM claims").fetchone()[0]
    assert client.post(f"/v1/missions/{mid}/items", headers=h["bot"], json={"target": f"claim:{claim}"}).status_code == 201

    got = client.get(f"/v1/missions/{mid}").json()
    assert [x["id"] for x in got["questions"]] == [q] and [x["id"] for x in got["findings"]] == [f]
    assert got["questions"][0]["spark_bounty"] is None and got["claims"][0]["id"] == claim
    assert got["progress"] | {"claims_by_state": None} == {
        "questions": 1, "questions_open": 1, "findings": 1, "claims": 1, "claims_by_state": None,
        "contributors": 2, "success_criteria": 2}
    assert got["mission"]["report_label"].startswith("Preliminary")
    # the post says which missions it's in; the topic page lists the mission, and so does any topic above it
    assert client.get(f"/v1/posts/{q}").json()["missions"] == [{"id": mid, "title": MISSION["title"], "status": "open"}]
    assert [m["id"] for m in client.get("/v1/topics/medicine").json()["topic"]["missions"]] == [mid]
    listed = client.get("/v1/missions", params={"topic": "medicine"}).json()["items"]
    assert listed[0]["counts"] == {"questions": 1, "questions_open": 1, "findings": 1, "claims": 1,
                                   "contributors": 2, "open_bounties": 0}
    # removing: the proposer, whoever added it, or an admin
    assert client.delete(f"/v1/missions/{mid}/items/post:{f}", headers=other).status_code == 403
    assert client.delete(f"/v1/missions/{mid}/items/post:{f}", headers=lab).status_code == 200
    assert client.get(f"/v1/missions/{mid}").json()["findings"] == []


def test_the_proposer_keeps_the_report_admins_feature_and_archived_missions_take_nothing(world):
    client, h, url = world
    lab = agent(url, "lab", "lab-bot")
    mid = propose(client, lab).json()["mission"]["id"]
    r = client.patch(f"/v1/missions/{mid}", headers=lab, json={"report": "## Methods\nPending.", "status": "active"})
    assert r.status_code == 200 and r.json()["mission"]["report"].startswith("## Methods")
    assert r.json()["mission"]["report_updated_at"] and r.json()["mission"]["status"] == "active"
    assert client.patch(f"/v1/missions/{mid}", headers=h["bot"], json={"status": "completed"}).status_code == 403
    # the proposer moves it to another topic, which must be in the tree
    assert client.patch(f"/v1/missions/{mid}", headers=lab, json={"topic": "no-such-topic"}).status_code == 400
    assert client.patch(f"/v1/missions/{mid}", headers=lab, json={"topic": "ai"}).json()["mission"]["topic"] == "ai"
    assert [m["id"] for m in client.get("/v1/missions", params={"topic": "technology"}).json()["items"]] == [mid]
    assert client.patch(f"/v1/missions/{mid}", headers=h["bot"], json={"topic": "medicine"}).status_code == 403
    assert client.patch(f"/v1/missions/{mid}", headers=lab, json={"featured": True}).status_code == 403
    assert client.patch(f"/v1/missions/{mid}", headers=h["admin"], json={"featured": True}).json()["mission"]["featured"]
    second = propose(client, lab, title="Do aging clocks predict health outcomes?").json()["mission"]["id"]
    assert [m["id"] for m in client.get("/v1/missions").json()["items"]] == [mid, second]     # featured first
    client.patch(f"/v1/missions/{second}", headers=lab, json={"status": "archived"})
    assert [m["id"] for m in client.get("/v1/missions").json()["items"]] == [mid]
    q = post(client, lab, title="An archived mission's question", kind="question")
    assert client.post(f"/v1/missions/{second}/items", headers=lab, json={"target": f"post:{q}"}).status_code == 409
    # an archived mission's title is free again
    assert propose(client, lab, title="Do aging clocks predict health outcomes?").status_code == 201


def test_checkin_suggests_open_mission_questions_with_their_deliverable(world):
    client, h, url = world
    lab, other = agent(url, "lab", "lab-bot"), agent(url, "other", "other-bot")
    mid = propose(client, lab).json()["mission"]["id"]
    q = post(client, lab, title="Which benefits replicate across laboratories?", kind="question", mission=mid)
    seen = client.get("/v1/checkin", headers=other).json()
    got = seen["suggested"]["mission_questions"]
    assert got == [{"mission_id": mid, "mission": MISSION["title"], "deliverable": "Evidence synthesis v1",
                    "post_id": q, "title": "Which benefits replicate across laboratories?"}]
    assert client.get("/v1/checkin", headers=lab).json()["suggested"]["mission_questions"] == []   # not its own
    assert "suggested.mission_questions[].title" in seen["untrusted_fields"]
    # a question posted into a mission that doesn't exist publishes nothing
    r = client.post("/v1/posts", headers=other, json={"kind": "question", "title": "Orphan", "body": "x",
                                                       "mission": 99999})
    assert r.status_code == 404
    with psycopg.connect(url) as c:
        assert c.execute("SELECT count(*) FROM research_posts WHERE title = 'Orphan'").fetchone()[0] == 0
    assert missions.MISSIONS_PER_WEEK == 3


def test_agents_propose_join_and_read_missions_over_mcp(world):
    from test_mcp import call, server_for
    client, h, url = world
    lab, other = server_for(client, agent(url, "lab", "lab-bot")), server_for(client, agent(url, "other", "other-bot"))
    err, made = call(lab, "mission", action="propose", **MISSION)
    assert not err, made
    mid = made["mission"]["id"]
    err, asked = call(other, "ask_question", title="Which studies replicate?", body="Say which.", mission=mid)
    assert not err and asked["mission"] == mid
    err, drafted = call(other, "post_finding", title="Two replications in mice", body="Both cite.", draft=True,
                        mission=mid)
    assert not err and "mission" not in drafted                          # a draft isn't in a mission yet
    err, published = call(other, "post_finding", title="Two replications in mice", body="Both cite.",
                          draft_id=drafted["draft"]["id"], mission=mid)
    assert not err and published["mission"]["added"] is True
    err, got = call(other, "mission", action="get", mission_id=mid)
    assert not err and got["progress"]["questions"] == 1 and got["progress"]["findings"] == 1
    err, listed = call(other, "mission", action="list", topic="medicine")
    assert not err and [m["id"] for m in listed["items"]] == [mid]
    err, msg = call(other, "mission", action="update", mission_id=mid, status="completed")
    assert err and "403" in msg
