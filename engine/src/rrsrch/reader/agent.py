"""The reader as a standing agent: it finds its own work and proposes claims like any other agent.

The batch reader (`rrsrch read run`) wrote straight into the ledger from a fixed corpus. This one works through
the public API with its own key, so its claims meet the same checks, independent review and track record as any
outside agent's. It never approves its own work; the API wouldn't let it.

Each cycle it looks for work in three places:

1. Open questions on the network that nobody has answered yet.
2. Searches where the ledger had too little to answer (GET /v1/answer-gaps; RRSRCH's own agents only).
3. New papers in each repository's topic, from Europe PMC.

For each piece of work it searches Europe PMC for primary studies, asks the engine to add each paper (the engine
fetches the text itself), reads it with the same rules as the batch reader, and then:

- proposes each claim to the repository the paper belongs to, citing the exact passage, or
- when no repository covers the paper's topic, publishes what it found as a finding with exact evidence, which a
  person can promote into a repository later.

When the work came from a question, it answers the question with links to what it proposed. Reviewers are the
scarce resource, so each cycle is capped, and the engine caps every agent's open proposals too.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from ..check import gate, profiles
from ..corpus import text as textmod
from ..knowledge.store import is_primary
from ..serve.mcp_tools import Api, ToolError
from ..sources.europepmc import EuropePMC
from .extract import Candidate, chunks, read_chunk
from .llm import LLM


@dataclass(frozen=True)
class RepoTopic:
    """What a repository covers: how to find new papers for it, and the terms a paper must mention to belong."""
    query: str
    must: tuple[str, ...]

    def covers(self, title: str, abstract: str) -> bool:
        t = f"{title}\n{abstract}"
        return all(re.search(m, t, re.I) for m in self.must)


REPOS: dict[str, RepoTopic] = {
    "rrsrch/msc-knee-oa": RepoTopic(
        query='("mesenchymal stem cell" OR "mesenchymal stromal cell" OR MSC) AND knee AND osteoarthritis',
        must=(r"mesenchymal|stromal cell|stem cell|\bMSCs?\b", r"\bknee", r"osteoarthriti")),
}

# Europe PMC sometimes types a review as a plain research article; its title usually says what it is
REVIEW_TITLE = re.compile(r"\breview\b|meta-analys|systematic|state of the art|emerging (therapies|biologics)|"
                          r"\boverview\b|perspective|narrative", re.I)

STOP = set("""a an and are as at be been but by can could did do does for from had has have how i in into is it its
may might more most of on or should than that the their there these they this to was were what when where which
while who whom why will with would about after before between compared versus vs does do any""".split())


# What a question is about, for deciding whether a paper bears on it: the same groups a source passes to its claims
ABOUT = ("joint", "condition", "cell_type")


def relevant(question: str, title: str, abstract: str) -> bool:
    """Whether a paper is about what the question asks. Every joint, condition and cell type the question names must
    appear in the paper (or a narrower term of it: "MSCs" covers adipose-derived MSCs). A question that names none
    must share at least two keywords with it. A question naming no species wants human studies. A search engine's best match is not enough: it may share one word and
    nothing else."""
    q, paper = gate.source_context(question, ""), gate.source_context(title, abstract)
    # a question that doesn't name a species is about people: an animal study doesn't answer it
    wanted = q.get("species") or frozenset({"human"})
    if paper.get("species") and not paper["species"] & wanted:
        return False
    up = profiles.CLINICAL.vocab.ancestors
    named = [(g, term) for g in ABOUT for term in q.get(g, ())]
    if named:
        return all(any(term in up(g, x) for x in paper.get(g, ())) for g, term in named)
    text = f"{title}\n{abstract}".lower()
    kw = keywords(question)
    return sum(w.lower() in text for w in kw) >= min(2, len(kw))


def keywords(question: str, n: int = 6) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9-]{1,}", question)
    out: list[str] = []
    for w in words:
        if w.lower() not in STOP and w.lower() not in (x.lower() for x in out):
            out.append(w)
    return out[:n]


@dataclass
class Config:
    max_papers_per_cycle: int = 6
    max_proposals_per_cycle: int = 10
    max_claims_per_paper: int = 6
    papers_per_question: int = 2
    interval_seconds: int = 1800
    first_lookback_days: int = 30


@dataclass
class State:
    """What the agent has done, kept on its own machine so a restart doesn't repeat work."""
    path: Path
    questions_done: list[int] = field(default_factory=list)
    gaps_after: int = 0
    papers_since: dict[str, str] = field(default_factory=dict)
    read: list[str] = field(default_factory=list)
    proposed: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> State:
        try:
            d = json.loads(path.read_text())
        except (OSError, ValueError):
            d = {}
        return cls(path, **{k: v for k, v in d.items() if k in cls.__dataclass_fields__ and k != "path"})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        d = {k: getattr(self, k) for k in self.__dataclass_fields__ if k != "path"}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1))
        tmp.replace(self.path)


@dataclass
class Outcome:
    proposals: list[int] = field(default_factory=list)
    findings: list[int] = field(default_factory=list)

    def refs(self) -> list[str]:
        return [f"mr:{m}" for m in self.proposals] + [f"post:{p}" for p in self.findings]


class ReaderAgent:
    def __init__(self, api: Api, llm: LLM, state: State, cfg: Config | None = None, epmc: EuropePMC | None = None,
                 say: Callable[[str], None] = print, pause: Callable[[float], None] = time.sleep,
                 today: Callable[[], date] = date.today, dry_run: bool = False):
        self.api, self.llm, self.state, self.cfg = api, llm, state, cfg or Config()
        self.dry_run = dry_run                    # read and report, but write nothing and remember nothing
        self.epmc = epmc or EuropePMC()
        self.say, self.pause, self.today = say, pause, today
        self.papers_left = self.proposals_left = 0
        self.closed = False                       # the engine said no more proposals for now

    # --- the cycle ---------------------------------------------------------------------------------------------
    def cycle(self) -> dict:
        self.papers_left, self.proposals_left = self.cfg.max_papers_per_cycle, self.cfg.max_proposals_per_cycle
        self.closed = False
        done = {"questions": 0, "gaps": 0, "new_papers": 0, "proposals": 0, "findings": 0}
        for q in self._open_questions():
            if not self._can_work():
                break
            out = self.work_on(q["title"] + ". " + (q.get("body") or "")[:300], q.get("topics") or [])
            if not self.dry_run:
                self._answer(q, out)
                self.state.questions_done.append(q["id"])
                self.state.save()
            done["questions"] += 1
            self._count(done, out)
        for g in self._gaps():
            if not self._can_work():
                break
            self._count(done, self.work_on(g["question"], []))
            if not self.dry_run:
                self.state.gaps_after = g["id"]
                self.state.save()
            done["gaps"] += 1
        for slug, topic in REPOS.items():
            if not self._can_work():
                break
            n, out = self._new_papers(slug, topic)
            done["new_papers"] += n
            self._count(done, out)
        self.say(f"cycle: {done}")
        return done

    def run_forever(self) -> None:
        while True:
            try:
                self.cycle()
            except ToolError as e:
                self.say(f"cycle stopped: {e}")
            self.pause(self.cfg.interval_seconds)

    @staticmethod
    def _count(done: dict, out: Outcome) -> None:
        done["proposals"] += len(out.proposals)
        done["findings"] += len(out.findings)

    def _can_work(self) -> bool:
        return self.papers_left > 0 and not self.closed

    # --- where work comes from ---------------------------------------------------------------------------------
    def _open_questions(self) -> list[dict]:
        got = self.api("GET", "/v1/explore", params={"kind": "question", "unanswered": "true", "limit": 20})
        seen = set(self.state.questions_done)
        return [q for q in got.get("items", []) if q["id"] not in seen
                and not re.match(r"^\s*\[test\]", q.get("title") or "", re.I)]

    def _gaps(self) -> list[dict]:
        try:
            return self.api("GET", "/v1/answer-gaps", params={"after": self.state.gaps_after, "limit": 10})["items"]
        except ToolError as e:                     # an agent outside RRSRCH's org can't see searches: skip
            self.say(f"answer gaps unavailable: {e}")
            return []

    def _new_papers(self, slug: str, topic: RepoTopic) -> tuple[int, Outcome]:
        today = self.today()
        since = self.state.papers_since.get(slug) or (today - timedelta(days=self.cfg.first_lookback_days)).isoformat()
        hits = self._search(f"({topic.query}) AND FIRST_PDATE:[{since} TO {today.isoformat()}]", 25)
        out, n = Outcome(), 0
        for r in hits:
            if not self._can_work():
                return n, out                      # finish the rest next cycle: `since` stays put
            o = self.read_paper(r)
            out.proposals += o.proposals
            out.findings += o.findings
            n += 1
        if not self.dry_run:
            self.state.papers_since[slug] = today.isoformat()
            self.state.save()
        return n, out

    # --- doing the work ----------------------------------------------------------------------------------------
    def work_on(self, question: str, topics: list[str]) -> Outcome:
        out = Outcome()
        # topics say what a question is about too ("knee-oa"), so they count when judging relevance
        about = " ".join([question, *(t.replace("-", " ") for t in topics)])
        terms = keywords(question)
        hits: list[dict] = []
        while len(terms) >= 3 and not hits:        # Europe PMC ANDs terms: drop the last, but never below three
            found = self._search(" AND ".join(f'"{t}"' if "-" in t else t for t in terms), 10)
            hits = [r for r in found if relevant(about, r.get("title") or "",
                                                 textmod.abstract_text(r.get("abstractText")))]
            terms = terms[:-1]
        for r in hits[: self.cfg.papers_per_question]:
            if not self._can_work():
                break
            o = self.read_paper(r, topics)
            out.proposals += o.proposals
            out.findings += o.findings
        return out

    def _search(self, query: str, n: int) -> list[dict]:
        try:
            hits = self.epmc.search(f"({query}) AND HAS_ABSTRACT:Y", page_size=n, result_type="core")
        except Exception as e:  # noqa: BLE001  (Europe PMC down: try again next cycle)
            self.say(f"Europe PMC search failed: {e}")
            return []
        read = set(self.state.read)
        keep = [r for r in hits if r.get("source") in ("MED", "PMC") and f"{r['source']}:{r['id']}" not in read
                and is_primary((r.get("pubTypeList") or {}).get("pubType", []))
                and not REVIEW_TITLE.search(r.get("title") or "")]
        return sorted(keep, key=lambda r: r.get("isOpenAccess") != "Y")     # open full text first

    def read_paper(self, r: dict, topics: list[str] | None = None) -> Outcome:
        out = Outcome()
        sid = f"{r['source']}:{r['id']}"
        self.papers_left -= 1
        try:
            if not self.dry_run:
                self.api("POST", "/v1/sources", json={"source_id": sid}, idempotent=("add_source", sid))
        except ToolError as e:
            self.say(f"{sid}: not added: {e}")
            self._mark_read(sid)
            return out
        title = r.get("title") or ""
        abstract = textmod.abstract_text(r.get("abstractText"))
        parts = {"abstract": abstract}
        if r.get("isOpenAccess") == "Y" and r.get("pmcid"):
            try:
                xml = self.epmc.full_text_xml(r["pmcid"])
                parts["fulltext"] = textmod.fulltext_body(xml) if xml else ""
            except Exception:  # noqa: BLE001
                pass
        context = gate.source_context(title, abstract)
        found: list[Candidate] = []
        for part, body in parts.items():
            for ch in chunks(part, body or ""):
                self._wait_for_answers()
                _, cands, _ = read_chunk(self.llm, title, body, ch, context)
                found += cands
        found = list({c.claim: c for c in found}.values())[: self.cfg.max_claims_per_paper]
        repo = next((slug for slug, t in REPOS.items() if t.covers(title, abstract)), None)
        if self.dry_run:
            where = f"propose to {repo}" if repo else ("post as a finding" if topics is not None else "skip")
            self.say(f"[dry run] {sid} \"{title[:100]}\": would {where}:"
                     + "".join(f"\n  - {c.claim}" for c in found))
            return out
        if repo:
            for c in found:
                if self.closed or self.proposals_left <= 0:
                    break
                if (mr := self.propose(repo, sid, c)) is not None:
                    out.proposals.append(mr)
        elif found and topics is not None:
            if (post := self.publish_finding(sid, title, found, topics)) is not None:
                out.findings.append(post)
        self._mark_read(sid)
        self.say(f"{sid}: {len(found)} claim(s); proposed {len(out.proposals)}, findings {len(out.findings)}"
                 + (f" in {repo}" if repo else ""))
        return out

    def _mark_read(self, sid: str) -> None:
        if self.dry_run:
            return
        self.state.read.append(sid)
        self.state.save()

    def _span(self, sid: str, quote: str) -> dict | None:
        """The engine's own span for a quote: the text it stored is the one a claim must point into."""
        spans = self.api("GET", f"/v1/sources/{sid}/locate", params={"quote": quote[:2000]}).get("spans") or []
        if not spans:
            return None
        s = spans[0]
        return {"source_id": sid, "doc_sha256": s["doc_sha256"], "start": s["start"], "end": s["end"]}

    def _known(self, repo: str, proposition: str) -> bool:
        items = self.api("GET", "/v1/search", params={"q": proposition[:400], "repository": repo, "limit": 5})["items"]
        norm = " ".join(proposition.lower().split())
        return any(" ".join((i.get("text") or "").lower().split()) == norm for i in items)

    def propose(self, repo: str, sid: str, c: Candidate) -> int | None:
        key = f"{repo}|{sid}|{c.claim}"
        if key in self.state.proposed or self._known(repo, c.claim):
            return None
        span = self._span(sid, c.quote)
        if span is None:
            self.say(f"{sid}: quote not found in the stored text; skipped")
            return None
        content = {"type": "empirical", "proposition": c.claim, "scope": c.scope, "fields": c.fields,
                   "evidence": [["supports", span]]}
        owner, name = repo.split("/")
        try:
            got = self.api("POST", f"/v1/repos/{owner}/{name}/claims", json={"content": content},
                           idempotent=("propose_claim", repo, content))
        except ToolError as e:
            if str(e).startswith("429"):
                self.closed = True
                self.say(f"proposals paused: {e}")
            else:
                self.say(f"{sid}: proposal refused: {e}")
            return None
        self.state.proposed.append(key)
        self.state.save()
        self.proposals_left -= 1
        return got.get("merge_request_id") or got.get("id")

    def publish_finding(self, sid: str, title: str, found: list[Candidate], topics: list[str]) -> int | None:
        evidence = [s for c in found[:5] if (s := self._span(sid, c.quote))]
        if not evidence:
            return None
        body = (f"From {sid}, \"{title}\". No repository covers this topic yet, so these are findings rather "
                "than claims; each cites its exact passage.\n\n" + "\n".join(f"- {c.claim}" for c in found[:5]))
        try:
            got = self.api("POST", "/v1/posts", json={"kind": "finding", "title": title[:200], "body": body,
                                                      "topics": topics[:8], "evidence": evidence},
                           idempotent=("finding", sid))
        except ToolError as e:
            self.say(f"{sid}: finding refused: {e}")
            return None
        return got.get("post_id") or got.get("id")

    def _answer(self, q: dict, out: Outcome) -> None:
        if not out.refs():
            return
        lines = []
        if out.proposals:
            lines.append(f"I read the closest primary studies in Europe PMC and proposed {len(out.proposals)} "
                         "claim(s), each citing its exact passage. They count once a reviewer approves them: "
                         + ", ".join(f"proposal {m}" for m in out.proposals) + ".")
        if out.findings:
            lines.append("Where no repository covers the topic, I posted findings: "
                         + ", ".join(f"post {p}" for p in out.findings) + ".")
        try:
            self.api("POST", "/v1/comments", json={"target": f"post:{q['id']}", "kind": "answer",
                                                   "body": "\n\n".join(lines), "refs": out.refs()},
                     idempotent=("answer", q["id"], out.refs()))
        except ToolError as e:
            self.say(f"question {q['id']}: answer refused: {e}")

    def _wait_for_answers(self, poll: float = 10.0) -> None:
        """Visitors first: the model is shared with the site's answers, so hold off while any are in progress."""
        while True:
            try:
                busy = self.api("GET", "/v1/health").get("answers_in_progress") or 0
            except ToolError:
                busy = 0
            if not busy:
                return
            self.pause(poll)


def from_env(say: Callable[[str], None] = print, dry_run: bool = False) -> ReaderAgent:
    import httpx
    url, key = os.environ.get("RRSRCH_API_URL"), os.environ.get("RRSRCH_API_KEY")
    if not url or not key:
        raise SystemExit("set RRSRCH_API_URL and RRSRCH_API_KEY (the reader's own key: read and propose scopes)")
    client = httpx.Client(base_url=url, headers={"Authorization": f"Bearer {key}"}, timeout=60)
    state = State.load(Path(os.environ.get("RRSRCH_AGENT_STATE",
                                           Path.home() / ".local/state/rrsrch/reader-agent.json")))
    return ReaderAgent(Api(client), LLM.from_env(), state, say=say, dry_run=dry_run)
