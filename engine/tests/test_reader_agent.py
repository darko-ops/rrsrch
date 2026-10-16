"""The reader as a standing agent: adding papers, proposal limits, answer gaps, and a full cycle over the real API."""
import psycopg
import pytest
from test_trust_db import PILOT, QUOTE, TEXT, content, open_mr, world  # noqa: F401  (world is a fixture)

from rrsrch.knowledge import ingest
from rrsrch.reader import agent as agent_mod
from rrsrch.serve.mcp_tools import Api
from rrsrch.trust import merge

pytestmark = pytest.mark.db

CLAIM = "At 12 months, WOMAC improved more with MSCs than hyaluronic acid (p = 0.01)."


def record(pmid="2", title="Mesenchymal stem cells for knee osteoarthritis: a randomised trial", oa="N"):
    return {"source": "MED", "id": pmid, "pmid": pmid, "title": title, "pubYear": "2026",
            "abstractText": f"<h4>Results</h4>{TEXT}", "isOpenAccess": oa,
            "pubTypeList": {"pubType": ["Randomized Controlled Trial"]}}


class FakeEPMC:
    def __init__(self, records):
        self.records = {f"{r['source']}:{r['id']}": r for r in records}
        self.searches = []

    def record(self, source_id):
        return self.records.get(source_id)

    def search(self, query, page_size=25, result_type="lite"):
        self.searches.append(query)
        if query.startswith('DOI:'):
            return []
        return list(self.records.values())[:page_size]

    def full_text_xml(self, pmcid):
        return None


class FakeLLM:
    model = "fake"

    def json_chat(self, system, user):
        return {"claims": [{"quote": QUOTE, "claim": CLAIM}]}


def use_epmc(monkeypatch, *records):
    fake = FakeEPMC(records)
    monkeypatch.setattr(ingest, "EuropePMC", lambda: fake)
    return fake


def test_agents_add_papers_the_engine_fetches_itself(world, monkeypatch):
    client, h, url = world
    use_epmc(monkeypatch, record())
    assert client.post("/v1/sources", json={"source_id": "MED:2"}).status_code == 401
    assert client.post("/v1/sources", headers=h["bot"], json={"source_id": "MED:2; DROP"}).status_code == 400
    assert client.post("/v1/sources", headers=h["bot"], json={}).status_code == 400
    assert client.post("/v1/sources", headers=h["bot"], json={"source_id": "MED:404"}).status_code == 404

    r = client.post("/v1/sources", headers=h["bot"], json={"source_id": "MED:2"})
    assert r.status_code == 201 and r.json()["added"] is True
    assert {d["part"] for d in r.json()["source"]["documents"]} == {"title", "abstract"}
    again = client.post("/v1/sources", headers=h["bot"], json={"source_id": "MED:2"})
    assert again.status_code == 200 and again.json()["added"] is False

    # the stored text is citable: locate the quote, and a proposal citing it opens
    span = client.get("/v1/sources/MED:2/locate", params={"quote": QUOTE}).json()["spans"][0]
    c = content() | {"evidence": [["supports", {k: span[k] for k in ("source_id", "doc_sha256", "start", "end")}]]}
    assert open_mr(client, h["bot"], {"repository": PILOT, "content": c})
    with psycopg.connect(url) as conn:
        assert conn.execute("SELECT count(*) FROM audit_events WHERE action = 'source.add'").fetchone()[0] == 1


def test_one_agent_cannot_bury_the_reviewers(world, monkeypatch):
    client, h, url = world
    monkeypatch.setattr(merge, "PROPOSALS_PER_DAY", 2)
    for i in range(2):
        open_mr(client, h["bot"], {"repository": PILOT, "content": content(f"{CLAIM} ({i})")})
    r = client.post("/v1/merge-requests", headers=h["bot"], json={"repository": PILOT, "content": content()})
    assert r.status_code == 429 and "last day" in r.json()["error"]

    monkeypatch.setattr(merge, "PROPOSALS_PER_DAY", 100)
    monkeypatch.setattr(merge, "OPEN_PROPOSALS_MAX", 2)
    r = client.post("/v1/merge-requests", headers=h["bot"], json={"repository": PILOT, "content": content()})
    assert r.status_code == 429 and "waiting for review" in r.json()["error"]


def test_answer_gaps_are_searches_the_ledger_could_not_answer(world):
    client, h, url = world
    with psycopg.connect(url) as conn:
        for q, shown, bench in [("Do MSCs help ankle OA?", [], None), ("do mscs help ankle oa?", [1], None),
                                ("Do MSCs reduce knee pain?", [1, 2, 3], None), ("bench q", [], "b1")]:
            conn.execute("INSERT INTO reports (question, bench_id, writer, claims_shown) VALUES (%s, %s, 'w', %s)",
                         (q, bench, shown))
    assert client.get("/v1/answer-gaps").status_code == 403
    assert client.get("/v1/answer-gaps", headers=h["ext"]).status_code == 403          # not RRSRCH's own agent
    items = client.get("/v1/answer-gaps", headers=h["bot"]).json()["items"]
    assert [(i["question"].lower(), i["asked"]) for i in items] == [("do mscs help ankle oa?", 2)]
    assert client.get("/v1/answer-gaps", headers=h["bot"], params={"after": items[0]["id"]}).json()["items"] == []


def make_agent(client, h, tmp_path, fake, **cfg):
    client.headers.update(h["bot"])
    state = agent_mod.State.load(tmp_path / "state.json")
    return agent_mod.ReaderAgent(Api(client), FakeLLM(), state, agent_mod.Config(**cfg), epmc=fake,
                                 say=lambda s: None, pause=lambda s: None)


def test_a_cycle_answers_a_question_with_reviewed_proposals(world, monkeypatch, tmp_path):
    client, h, url = world
    fake = use_epmc(monkeypatch, record())
    q = client.post("/v1/posts", headers=h["ext"], json={"kind": "question", "title": "Do MSCs beat hyaluronic acid?",
                                                         "body": "For knee osteoarthritis, at 12 months.",
                                                         "topics": ["knee-oa"]})
    assert q.status_code == 201, q.json()
    qid = q.json()["post_id"]

    a = make_agent(client, h, tmp_path, fake)
    done = a.cycle()
    assert done["questions"] == 1 and done["proposals"] == 1

    with psycopg.connect(url) as conn:
        author, state, ev = conn.execute(
            "SELECT a.handle, m.state, m.content->'evidence' FROM merge_requests m JOIN agents a ON a.id = m.author_id"
        ).fetchone()
        assert (author, state) == ("bot", "open") and ev[0][1]["source_id"] == "MED:2"
        answer = conn.execute("SELECT m.kind, m.refs FROM messages m JOIN agents a ON a.id = m.author_id "
                              "WHERE a.handle = 'bot'").fetchone()
    assert answer[0] == "answer" and answer[1][0].startswith("mr:")

    # the agent can't approve its own proposal
    mr = int(answer[1][0].split(":")[1])
    assert client.post("/v1/reviews", json={"target": f"proposal:{mr}", "verdict": "approve"}).status_code == 403

    # a restart doesn't repeat work: the question is done and the paper read
    again = make_agent(client, h, tmp_path, fake).cycle()
    assert again["proposals"] == 0 and again["questions"] == 0


def test_papers_outside_every_repository_become_findings(world, monkeypatch, tmp_path):
    client, h, url = world
    fake = use_epmc(monkeypatch, record(pmid="3", title="Platelet-rich plasma for tennis elbow"))
    q = client.post("/v1/posts", headers=h["ext"], json={"kind": "question", "title": "Does PRP help tennis elbow?",
                                                         "body": "Pain at 6 months.", "topics": ["elbow"]}).json()["post_id"]
    done = make_agent(client, h, tmp_path, fake).cycle()
    assert done["proposals"] == 0 and done["findings"] == 1
    with psycopg.connect(url) as conn:
        kind, topics, evidence = conn.execute(
            "SELECT kind, topics, evidence FROM research_posts WHERE kind = 'finding'").fetchone()
        refs = conn.execute("SELECT m.refs FROM messages m JOIN agents a ON a.id = m.author_id "
                            "WHERE a.handle = 'bot'").fetchone()[0]
    assert (kind, topics) == ("finding", ["elbow"]) and evidence[0]["source_id"] == "MED:3"
    assert refs[0].startswith("post:")


def test_the_agent_stops_proposing_when_the_engine_says_enough(world, monkeypatch, tmp_path):
    client, h, url = world
    monkeypatch.setattr(merge, "PROPOSALS_PER_DAY", 0)
    fake = use_epmc(monkeypatch, record(), record(pmid="4"))
    a = make_agent(client, h, tmp_path, fake)
    done = a.cycle()
    assert done["proposals"] == 0 and a.closed is True
    assert done["new_papers"] == 1            # it stopped there; the second paper waits for the next cycle
    assert a.state.read == ["MED:2"] and "rrsrch/msc-knee-oa" not in a.state.papers_since


MRI_Q = "Do clinical gains from MSC injections show up on MRI? knee oa msc imaging"
VOCAL = ("An open phase I/IIa study evaluating safety, patient-reported outcomes and voice function after surgery, local "
         "administration of mesenchymal stromal cells and voice training in patients with vocal fold scarring",
         "Eight patients with vocal fold scarring received autologous bone marrow MSCs. Voice Handicap Index scores "
         "decreased by 25.9 points at 12 months.")
KNEE = ("Intra-articular mesenchymal stem cells for knee osteoarthritis: cartilage on MRI at 12 months",
        "In 60 patients with knee osteoarthritis, MSC injection improved WOMAC and MRI cartilage volume at 12 months.")


def test_a_paper_must_be_about_what_the_question_asks():
    # the first live cycle read a vocal fold study for a knee question; it shares "MSC" and nothing that matters
    assert agent_mod.relevant(MRI_Q, *VOCAL) is False
    assert agent_mod.relevant(MRI_Q, *KNEE) is True
    assert agent_mod.relevant("Does PRP help tennis elbow pain?", *KNEE) is False


def test_reviews_typed_as_research_articles_are_skipped():
    titles = ["Emerging Biologics in Lumbar Disc Degeneration: PRP, Stem Cell Therapy, and Pharmacotherapy",
              "Mesenchymal stem cells for knee osteoarthritis: a systematic review", "A narrative review of MSCs"]
    assert all(agent_mod.REVIEW_TITLE.search(t) for t in titles)
    assert not agent_mod.REVIEW_TITLE.search(KNEE[0])


def test_a_dry_run_reads_but_writes_nothing(world, monkeypatch, tmp_path):
    client, h, url = world
    fake = use_epmc(monkeypatch, record())
    client.post("/v1/posts", headers=h["ext"], json={"kind": "question", "title": "Do MSCs beat hyaluronic acid?",
                                                     "body": "For knee osteoarthritis, at 12 months.", "topics": ["knee-oa"]})
    said = []
    a = make_agent(client, h, tmp_path, fake)
    a.dry_run, a.say = True, said.append
    a.cycle()
    assert any("would propose to rrsrch/msc-knee-oa" in s and CLAIM in s for s in said)
    with psycopg.connect(url) as conn:
        assert conn.execute("SELECT count(*) FROM merge_requests").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM sources WHERE id = 'MED:2'").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
    assert not (tmp_path / "state.json").exists()


def test_a_question_that_names_no_species_wants_human_studies():
    # the dry run would have answered a pain question with a rat study
    rat = ("Mesenchymal stromal cells alleviate neuropathic pain in association with M2 macrophage polarization",
           "Male Sprague Dawley rats with sciatic nerve injury received MSCs; pain thresholds partially recovered.")
    assert agent_mod.relevant("Do MSC injections reduce pain?", *rat) is False
    assert agent_mod.relevant("Do MSCs reduce neuropathic pain in rats?", *rat) is True
    assert agent_mod.relevant(MRI_Q, *KNEE) is True                  # human studies, and those naming none, still pass
    # the second dry run: the abstract named patients and rats, so the paper's species read as unknown
    both = (rat[0], "Neuropathic pain affects many patients. In rats with chronic constriction injury, MSCs partially "
                    "restored withdrawal thresholds.")
    assert agent_mod.relevant("Do MSC injections reduce pain?", *both) is False
    assert agent_mod.relevant("Do MSCs reduce neuropathic pain in rats?", *both) is True


def test_editorials_and_commentary_are_not_read_as_studies():
    # the second dry run would have proposed claims from an editorial arguing for insurance coverage
    editorial = ("Bridging the Gap Between Regulatory Approval and Patient Access: The Case for Insurance Coverage of "
                 "Approved Allogeneic Stem Cell Therapy in Knee Osteoarthritis.")
    assert agent_mod.is_study(["Editorial"], editorial) is False
    assert agent_mod.is_study(["Journal Article"], editorial) is False              # mistyped, but the title says so
    assert agent_mod.is_study(["Letter", "Comment"], "MSCs for knee OA") is False
    assert agent_mod.is_study(["Journal Article"], "A viewpoint on cell therapy regulation") is False
    assert agent_mod.is_study(["Review", "Journal Article"], KNEE[0]) is False
    assert agent_mod.is_study(["Randomized Controlled Trial", "Journal Article"], KNEE[0]) is True
    assert agent_mod.is_study([], KNEE[0]) is True
