"""Run an experiment: the same tasks, agents and budgets under conditions A, B and C.

For each condition and repeat:
  - B and C get a fresh private repository in the `eval` organization; every
    other repository in the evaluation database is made private, so no
    knowledge leaks in from outside the run.
  - B and C get seeded errors: claims copied from real ones with their
    direction flipped, marked supported, as a contaminated memory would hold
    them. Whether agents cite them, catch them, or leave them standing is
    measured.
  - Agents take each task in turn (the starting agent rotates, so no agent is
    always first). After each turn a steward merges whatever the repository's
    policy now allows; it never reviews.

The steward stands in for the platform's maintainers, so the experiment
measures the agents, not a human in the loop. Because it merges between
turns, a contribution in C becomes reusable only after another agent has
reviewed it: reuse there lags one review cycle behind B, by design.
"""
from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

import psycopg
from fastapi.testclient import TestClient

from ..identity import store as ids
from ..knowledge import store as kstore
from ..ledger import db
from ..serve import api as api_mod
from .agent import Agent, Task
from .budget import Budget, Meter
from .tools import Toolbox

EVAL_ORG = "eval"
POLICIES = {
    "B": {"allowed_types": ["empirical"], "evidence_gate": True, "required_approvals": 0},
    "C": {"allowed_types": ["empirical"], "evidence_gate": True, "required_approvals": 1},
}
# turn a finding around: the first rule that matches is applied once
FLIPS = [(r"\bdid not differ\b", "differed significantly"), (r"\bno significant\b", "a significant"),
         (r"\bimproved\b", "worsened"), (r"\bimprovement\b", "worsening"), (r"\breduced\b", "increased"),
         (r"\bdecreased\b", "increased"), (r"\bincreased\b", "decreased"), (r"\bhigher\b", "lower"),
         (r"\blower\b", "higher"), (r"\bbetter\b", "worse"), (r"\bsignificant(ly)?\b", "no significant")]


@dataclass
class Config:
    conditions: tuple[str, ...] = ("A", "B", "C")
    agents: int = 3
    repeats: int = 1
    seeded_errors: int = 2
    budget: Budget = field(default_factory=Budget)
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])


@dataclass
class Turn:
    condition: str
    repeat: int
    task: str
    agent: str
    order: int                      # position within the task's round
    turn: int                       # global turn number within the condition run
    expected: str
    verdict: str | None
    spans: list[dict]
    claim_ids: list[int]
    tool_calls: int
    tokens: int
    exhausted: str | None
    calls: list[dict]


@dataclass
class Seed:
    condition: str
    repeat: int
    claim_id: int
    proposition: str
    seeded_at_turn: int = 0
    challenged_at_turn: int | None = None
    final_state: str | None = None


def flip(text: str) -> str | None:
    for pattern, repl in FLIPS:
        if re.search(pattern, text, flags=re.I):
            return re.sub(pattern, repl, text, count=1, flags=re.I)
    return None


class Harness:
    def __init__(self, connect: Callable[[], psycopg.Connection], cfg: Config):
        self.connect, self.cfg = connect, cfg
        self.app = api_mod.create_app(connect=connect)
        with connect() as c:
            db.migrate(c)
            c.execute("UPDATE repositories SET visibility = 'private' WHERE organization_id <> %s", (EVAL_ORG,))
            if not c.execute("SELECT 1 FROM organizations WHERE id = %s", (EVAL_ORG,)).fetchone():
                ids.create_organization(c, EVAL_ORG, "Evaluation harness")
            steward = ids.register_agent(c, EVAL_ORG, f"eval-{cfg.run_id}-steward", "service", org_role="admin")
            token, _, _ = ids.issue_key(c, steward["id"], {"read", "maintain", "administer"}, days=7)
        self.steward = self._client(token)

    def _client(self, token: str) -> TestClient:
        return TestClient(self.app, headers={"Authorization": f"Bearer {token}"})

    def _agents(self, condition: str, repeat: int, repo: str | None) -> list[TestClient]:
        clients = []
        with self.connect() as c:
            repo_row = ids.get_repo(c, repo) if repo else None
            for i in range(self.cfg.agents):
                a = ids.register_agent(c, EVAL_ORG, f"eval-{self.cfg.run_id}-{condition.lower()}{repeat}-{i}", "service")
                if repo_row:
                    ids.set_member(c, repo_row.id, a["id"], "reviewer", granted_by=None)
                token, _, _ = ids.issue_key(c, a["id"], {"read", "propose", "review"}, days=7)
                clients.append((a["handle"], self._client(token)))
        return clients

    def _repository(self, condition: str, repeat: int) -> str | None:
        if condition == "A":
            return None
        slug = f"{EVAL_ORG}/{self.cfg.run_id}-{condition.lower()}{repeat}"
        r = self.steward.post("/v1/repos", json={"slug": slug, "topic": "evaluation", "visibility": "private",
                                                 "policy": POLICIES[condition]})
        r.raise_for_status()
        return slug

    def _seed(self, condition: str, repeat: int, slug: str) -> list[Seed]:
        seeds = []
        with self.connect() as c:
            repo_id = ids.get_repo(c, slug).id
            steward_id = c.execute("SELECT id FROM agents WHERE handle = %s",
                                   (f"eval-{self.cfg.run_id}-steward",)).fetchone()[0]
            for doc_id, sha, start, end, text, scope, fields in c.execute(
                    "SELECT document_id, doc_sha256, span_start, span_end, text, scope, fields FROM claims "
                    "WHERE repository_id IN (SELECT id FROM repositories WHERE organization_id <> %s) "
                    "ORDER BY id", (EVAL_ORG,)).fetchall():
                wrong = flip(text)
                if wrong is None:
                    continue
                cid = c.execute(
                    "INSERT INTO claims (document_id, doc_sha256, span_start, span_end, text, fields, scope, extractor, "
                    "repository_id, type, state, agent_id) VALUES (%s, %s, %s, %s, %s, %s, %s, 'eval-seed', %s, "
                    "'empirical', 'supported', %s) RETURNING id",
                    (doc_id, sha, start, end, wrong, json.dumps(fields),
                     json.dumps(scope), repo_id, steward_id)).fetchone()[0]
                kstore.record_claim(c, cid)
                seeds.append(Seed(condition, repeat, cid, wrong))
                if len(seeds) == self.cfg.seeded_errors:
                    break
        return seeds

    def _merge_ready(self, slug: str) -> None:
        with self.connect() as c:
            open_ids = [r[0] for r in c.execute(
                "SELECT m.id FROM merge_requests m JOIN repositories r ON r.id = m.repository_id "
                "WHERE r.slug = %s AND m.state = 'open' ORDER BY m.id", (slug,))]
        for mr in open_ids:
            preview = self.steward.get(f"/v1/merge-requests/{mr}").json().get("merge_preview", {})
            if preview.get("allowed"):
                self.steward.post(f"/v1/merge-requests/{mr}/merge")

    def run(self, tasks: list[Task], make_agent: Callable[[str, int, str], Agent],
            progress: Callable[[str], None] = lambda _: None) -> dict:
        turns: list[Turn] = []
        seeds: list[Seed] = []
        for condition in self.cfg.conditions:
            for repeat in range(self.cfg.repeats):
                slug = self._repository(condition, repeat)
                clients = self._agents(condition, repeat, slug)
                run_seeds = self._seed(condition, repeat, slug) if slug and self.cfg.seeded_errors else []
                seeds += run_seeds
                turn = 0
                for t_index, task in enumerate(tasks):
                    n = len(clients)
                    for order in range(n):
                        i = (t_index + order) % n
                        handle, client = clients[i]
                        meter = Meter(self.cfg.budget)
                        tools = Toolbox(condition, client, self.connect, meter, slug)
                        make_agent(condition, i, handle).run(task, tools)
                        turn += 1
                        ans = tools.answer
                        turns.append(Turn(condition, repeat, task.id, handle, order, turn, task.expected,
                                          ans.verdict if ans else None, ans.spans if ans else [],
                                          ans.claim_ids if ans else [], len(meter.calls), meter.tokens,
                                          meter.exhausted, [asdict(x) for x in meter.calls]))
                        if slug:
                            self._merge_ready(slug)
                            self._note_challenges(run_seeds, turn)
                    progress(f"{condition}{repeat} {task.id}: "
                             f"{sum(t.verdict == t.expected for t in turns if t.task == task.id and t.condition == condition and t.repeat == repeat)}"
                             f"/{len(clients)} correct")
                with self.connect() as c:
                    for s in run_seeds:
                        s.final_state = c.execute("SELECT state FROM claims WHERE id = %s", (s.claim_id,)).fetchone()[0]
        with self.connect() as c:
            authors = dict(c.execute(
                "SELECT c.id, a.handle FROM claims c JOIN agents a ON a.id = c.agent_id JOIN repositories r "
                "ON r.id = c.repository_id WHERE r.organization_id = %s", (EVAL_ORG,)).fetchall())
            reviews = c.execute(
                "SELECT count(*), count(*) FILTER (WHERE v.reviewer_id <> m.author_id), "
                "count(*) FILTER (WHERE v.verdict = 'approve') FROM reviews v JOIN merge_requests m "
                "ON m.id = v.merge_request_id JOIN repositories r ON r.id = m.repository_id "
                "WHERE r.slug LIKE %s", (f"{EVAL_ORG}/{self.cfg.run_id}-%",)).fetchone()
        return {"run_id": self.cfg.run_id, "config": {**asdict(self.cfg), "budget": asdict(self.cfg.budget)},
                "turns": [asdict(t) for t in turns], "seeds": [asdict(s) for s in seeds],
                "claim_authors": {str(k): v for k, v in authors.items()},
                "reviews": {"total": reviews[0], "independent": reviews[1], "approvals": reviews[2]}}

    def _note_challenges(self, run_seeds: list[Seed], turn: int) -> None:
        pending = [s for s in run_seeds if s.challenged_at_turn is None]
        if not pending:
            return
        with self.connect() as c:
            hit = {r[0] for r in c.execute("SELECT DISTINCT claim_id FROM challenges WHERE claim_id = ANY(%s)",
                                           ([s.claim_id for s in pending],))}
        for s in pending:
            if s.claim_id in hit:
                s.challenged_at_turn = turn - s.seeded_at_turn


def tasks_from_benchmark(bench: dict, only: list[str] | None = None) -> list[Task]:
    return [Task(q["id"], " ".join(q["question"].split()), q["expected"]["verdict"]) for q in bench["questions"]
            if not only or q["id"] in only]


def same_database(a: str, b: str) -> bool:
    """Whether two Postgres URLs name the same database (host, port and database name)."""
    from urllib.parse import urlparse
    pa, pb = urlparse(a), urlparse(b)
    return (pa.hostname, pa.port or 5432, pa.path.strip("/")) == (pb.hostname, pb.port or 5432, pb.path.strip("/"))
