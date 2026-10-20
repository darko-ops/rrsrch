"""The tree of knowledge: topics and sub-topics that collections (repositories) and posts are filed under."""
import psycopg
from test_agent_network import signup
from test_research import post
from test_trust_db import PILOT, world  # noqa: F401  (world is a fixture)

from rrsrch.collab import topics
from rrsrch.identity import store as ids
from rrsrch.trust import audit


def lab_admin(url):
    with psycopg.connect(url) as c:
        a = ids.register_agent(c, "lab", "lab-admin", "human", org_role="admin")
        tok, _, _ = ids.issue_key(c, a["id"], {"read", "propose", "agents", "administer"})
    return {"Authorization": f"Bearer {tok}"}


def test_the_tree_files_collections_under_topics_and_totals_take_in_everything_below(world):
    client, h, url = world
    tree = client.get("/v1/topics").json()["items"]
    by = {t["slug"]: t for t in tree}
    order = [t["slug"] for t in tree]
    assert order.index("medicine") < order.index("musculoskeletal") < order.index("knee-oa")   # parents first
    assert by["knee-oa"]["parent"] == "musculoskeletal" and by["medicine"]["parent"] is None
    assert by["knee-oa"]["own"]["collections"] == 1                   # the pilot sits under knee osteoarthritis
    assert by["medicine"]["own"]["collections"] == 0 and by["medicine"]["total"]["collections"] == 1
    assert by["technology"]["total"]["collections"] == 0
    post(client, h["bot"], topics=["msc"])
    by = {t["slug"]: t for t in client.get("/v1/topics").json()["items"]}
    assert by["msc"]["own"]["posts"] == 1 and by["medicine"]["total"]["posts"] == 1 and by["medicine"]["own"]["posts"] == 0

    knee = client.get("/v1/topics/knee-oa").json()["topic"]
    assert [x["slug"] for x in knee["path"]] == ["medicine", "musculoskeletal", "knee-oa"]
    assert [x["slug"] for x in knee["collections"]] == [PILOT] and knee["children"] == []
    med = client.get("/v1/topics/medicine").json()["topic"]
    assert {"musculoskeletal", "regenerative-medicine"} <= {x["slug"] for x in med["children"]}
    assert client.get("/v1/topics/nowhere").status_code == 404
    # collections by topic, anywhere below it; the repository says where it sits
    assert [r["slug"] for r in client.get("/v1/repos", params={"topic": "medicine"}).json()["items"]] == [PILOT]
    assert client.get("/v1/repos", params={"topic": "technology"}).json()["items"] == []
    assert client.get(f"/v1/repos/{PILOT}").json()["repository"]["topic_slug"] == "knee-oa"


def test_anyone_signed_in_adds_topics_and_only_rrsrch_renames_or_moves_them(world, monkeypatch):
    client, h, url = world
    lab = lab_admin(url)
    new = lambda who, **b: client.post("/v1/topics", headers=who, json=b)  # noqa: E731
    r = new(lab, title="Hip  osteoarthritis", parent="musculoskeletal")
    assert r.status_code == 201, r.json()
    hip = r.json()["topic"]
    assert hip["slug"] == "hip-osteoarthritis" and hip["title"] == "Hip osteoarthritis" and hip["created_by"] == "lab-admin"
    assert [x["slug"] for x in hip["path"]] == ["medicine", "musculoskeletal", "hip-osteoarthritis"]
    assert new(lab, title="Hip osteoarthritis", parent="musculoskeletal").status_code == 409     # one slug, tree-wide
    assert new(lab, title="Biology").status_code == 201                                  # top-level too
    assert new(h["ext"], title="Shoulder", parent="musculoskeletal").status_code == 201   # a member, not an admin
    scout = {"Authorization": f"Bearer {signup(client, 'scout').json()['key']}"}           # an unclaimed agent
    assert new(scout, title="Wrist", parent="musculoskeletal").status_code == 201
    monkeypatch.setattr(topics, "TOPICS_PER_DAY_UNCLAIMED", 1)                           # a few a day, then no more
    assert new(scout, title="Ankle", parent="musculoskeletal").status_code == 429
    assert new(lab, title="Shoulder", parent="nowhere").status_code == 404
    assert new({}, title="Shoulder", parent="musculoskeletal").status_code == 401
    assert new(h["admin"], title="Biology", slug="biology").status_code == 409            # taken above
    # deep enough for any field, and no deeper
    parent = "hip-osteoarthritis"
    for i in range(4):                                   # hip is 2 below medicine; 6 is the most
        r = new(lab, title=f"Level {i}", parent=parent)
        assert r.status_code == 201, r.json()
        parent = r.json()["topic"]["slug"]
    assert new(lab, title="Too deep", parent=parent).status_code == 400

    change = lambda who, slug, **b: client.patch(f"/v1/topics/{slug}", headers=who, json=b)  # noqa: E731
    assert change(lab, "hip-osteoarthritis", title="Hip OA").status_code == 403           # renaming is RRSRCH's
    r = change(h["admin"], "hip-osteoarthritis", title="Hip OA", parent="medicine")
    assert r.status_code == 200 and [x["slug"] for x in r.json()["topic"]["path"]] == ["medicine", "hip-osteoarthritis"]
    assert r.json()["topic"]["slug"] == "hip-osteoarthritis"                               # links keep working
    assert change(h["admin"], "medicine", parent="hip-osteoarthritis").status_code == 400  # not under itself
    assert change(h["admin"], "biology", parent="medicine").status_code == 200
    assert change(h["admin"], "biology", top_level=True).json()["topic"]["path"] == [{"slug": "biology", "title": "Biology"}]


def test_posts_are_filed_under_topics_and_a_topic_takes_in_everything_below_it(world):
    client, h, url = world
    r = client.post("/v1/posts", headers=h["bot"], json={"kind": "question", "title": "Q", "body": "b",
                                                         "topics": ["not-a-topic"]})
    assert r.status_code == 400 and "not in the topic tree: not-a-topic" in r.json()["error"]
    knee = post(client, h["bot"], kind="question", title="Knee question", topics=["knee-oa"])
    chips = post(client, h["bot"], title="Chip finding", topics=["semiconductors"])
    ids_ = lambda **q: [i["id"] for i in client.get("/v1/explore", headers=h["ext"], params=q).json()["items"]]  # noqa: E731
    assert ids_(topic="medicine") == [knee] and ids_(topic="technology") == [chips] and ids_(topic="knee-oa") == [knee]
    # following a topic follows everything under it: in Explore, and as open questions at check-in
    assert client.post("/v1/subscriptions", headers=h["ext"], json={"target": "topic:medicine"}).status_code in (200, 201)
    assert ids_(following="true") == [knee]
    asked = client.get("/v1/checkin", headers=h["ext"]).json()["open_questions"]
    assert [q["post_id"] for q in asked] == [knee]


def test_a_collection_is_filed_under_a_topic_when_created_or_moved(world):
    client, h, url = world
    lab = lab_admin(url)
    body = {"slug": "lab/hip", "topic": "Hip replacement outcomes", "visibility": "private"}
    assert client.post("/v1/repos", headers=lab, json=body | {"topic_slug": "nowhere"}).status_code == 400
    r = client.post("/v1/repos", headers=lab, json=body | {"topic_slug": "musculoskeletal"})
    assert r.status_code == 201, r.json()
    assert r.json()["repository"]["topic_slug"] == "musculoskeletal"
    r = client.patch("/v1/repos/lab/hip", headers=lab, json={"topic_slug": "knee-oa"})
    assert r.status_code == 200 and r.json()["repository"]["topic_slug"] == "knee-oa"
    # counts follow what the caller can read: the private collection counts for its owners, not for everyone
    mine = {t["slug"]: t for t in client.get("/v1/topics", headers=lab).json()["items"]}
    anyone = {t["slug"]: t for t in client.get("/v1/topics").json()["items"]}
    assert mine["knee-oa"]["own"]["collections"] == 2 and anyone["knee-oa"]["own"]["collections"] == 1


def test_a_deleted_collection_is_gone_everywhere_and_its_history_stays(world):
    client, h, url = world
    lab = lab_admin(url)
    assert client.post("/v1/repos", headers=lab, json={"slug": "lab/sandbox", "topic": "Sandbox", "visibility": "private",
                                                       "topic_slug": "knee-oa"}).status_code == 201
    gone = lambda who=lab, confirm="lab/sandbox": client.delete("/v1/repos/lab/sandbox", headers=who,  # noqa: E731
                                                                params={"confirm": confirm})
    assert gone(h["ext"]).status_code == 404                     # can't see it, can't delete it
    assert gone(confirm="sandbox").status_code == 400            # name it in full
    assert gone().status_code == 200
    assert client.get("/v1/repos/lab/sandbox", headers=lab).status_code == 404
    assert "lab/sandbox" not in [r["slug"] for r in client.get("/v1/repos", headers=lab).json()["items"]]
    knee = {t["slug"]: t for t in client.get("/v1/topics", headers=lab).json()["items"]}["knee-oa"]
    assert knee["own"]["collections"] == 1                       # only the pilot counts now
    assert client.patch("/v1/repos/lab/sandbox", headers=lab, json={"description": "x"}).status_code == 404
    assert gone().status_code == 404                             # already gone
    r = client.post("/v1/repos", headers=lab, json={"slug": "lab/sandbox", "topic": "Again", "visibility": "private"})
    assert r.status_code == 409 and "deleted" in r.json()["error"]
    with psycopg.connect(url) as c:
        assert c.execute("SELECT count(*) FROM audit_events WHERE target = 'repo:lab/sandbox'").fetchone()[0] >= 2
        assert audit.verify(c) == []                             # the chain still holds
