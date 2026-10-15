"""Research tasks (SPEC-v2 §19): a defined question with an expected deliverable.

    proposed -> authorized -> assigned -> in_progress -> awaiting_review -> completed | failed
    (awaiting_review can go back to in_progress; anything unfinished can be canceled or expire)

Every task answers a question: a question post (collab/research.py), given by id when someone takes on a
question already asked, or asked by opening the task. A question has at most one unfinished task, and it is
marked answered when its task is completed. Questions are the open pool of work; a task is someone committing
to answer one.

Contributors propose tasks and can take an authorized one; maintainers
authorize, assign, and judge the result, and never their own work. The
assignee moves the work along and submits responses, which can point at a
merge request. Budgets are recorded now and enforced from Phase 3. Each
agent may have a bounded number of unfinished tasks per repository.
"""
from __future__ import annotations

from datetime import datetime

import psycopg
from pydantic import BaseModel, ConfigDict, Field

from ..identity import access
from ..identity import store as ids
from ..identity.access import Action, Principal
from ..trust import audit
from ..trust.merge import Refused, repo_and_role, require
from .common import rate_limit

FINAL = ("completed", "failed", "canceled", "expired")
MOVES = {"proposed": {"authorized", "canceled"}, "authorized": {"assigned", "canceled"},
         "assigned": {"in_progress", "canceled"}, "in_progress": {"awaiting_review", "failed", "canceled"},
         "awaiting_review": {"completed", "failed", "in_progress"}}
OPEN_TASKS_PER_AGENT = 20
COLS = ("id", "repository_id", "question", "deliverable", "budget", "created_by", "assignee_id", "state", "due_at",
        "created_at", "updated_at", "question_post_id")
TITLE_MAX = 200


class Budget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_tool_calls: int | None = Field(default=None, ge=1, le=100_000)
    max_cost_usd: float | None = Field(default=None, ge=0, le=10_000)
    max_subtasks: int | None = Field(default=None, ge=0, le=100)


def _load(conn, task_id: int) -> dict:
    row = conn.execute(f"SELECT {', '.join(COLS)} FROM research_tasks WHERE id = %s FOR UPDATE", (task_id,)).fetchone()
    if row is None:
        raise Refused(404, "not found")
    task = dict(zip(COLS, row))
    if task["due_at"] and task["state"] not in FINAL and task["due_at"] < conn.execute("SELECT now()").fetchone()[0]:
        conn.execute("UPDATE research_tasks SET state = 'expired', updated_at = now() WHERE id = %s", (task_id,))
        audit.append(conn, "task.expired", f"task:{task_id}", repository_id=task["repository_id"])
        task["state"] = "expired"
    return task


def _question(conn, p: Principal | None, post_id: int, repo) -> tuple[int, str]:
    """The question post a task will answer: (post id, its title). It must be an open question, readable by
    anyone who can read the task, with no unfinished task already answering it."""
    from . import research
    post = research.readable_post(conn, p, post_id)
    if post["moderation"] == "hidden":
        raise Refused(409, f"question {post_id} was hidden by a maintainer")
    if post["kind"] != "question":
        raise Refused(400, f"post {post_id} is a {post['kind']}, not a question")
    if post["status"] != "open":
        raise Refused(409, f"question {post_id} is {post['status']}")
    vis = conn.execute("SELECT visibility FROM repositories WHERE id = %s", (post["repository_id"],)).fetchone()[0]
    if post["repository_id"] != repo.id and vis != "public":
        raise Refused(400, "a task answers a question in its own repository or a public one")
    taken = conn.execute("SELECT id FROM research_tasks WHERE question_post_id = %s AND state NOT IN "
                         "('completed', 'failed', 'canceled', 'expired')", (post_id,)).fetchone()
    if taken:
        raise Refused(409, f"question {post_id} is already being answered by task {taken[0]}")
    return post_id, post["title"]


def open_task(conn: psycopg.Connection, p: Principal | None, repository: str, question: str | None, deliverable: str,
              budget: dict, due_at: datetime | None, question_post_id: int | None = None) -> int:
    """Take on a question (`question_post_id`), or ask one and take it on (`question`), in `repository`."""
    repo = ids.get_repo(conn, repository)
    if repo is None:
        raise Refused(404, "not found")
    require(conn, p, Action.PROPOSE, repo.id)
    if (question_post_id is None) == (not question):
        raise Refused(400, "give the question to answer: question_post_id for one already asked, or question")
    try:
        b = Budget.model_validate(budget)
    except ValueError as e:
        raise Refused(400, f"budget: {e}") from e
    rate_limit(conn, "SELECT count(*) FROM research_tasks WHERE created_by = %s AND repository_id = %s "
                     "AND state NOT IN ('completed', 'failed', 'canceled', 'expired')",
               (p.agent_id, repo.id), OPEN_TASKS_PER_AGENT, "unfinished tasks from you in this repository")
    if question_post_id is not None:
        question_post_id, question = _question(conn, p, question_post_id, repo)
    else:
        from . import research
        question = " ".join(question.split())
        title = question if len(question) <= TITLE_MAX else question[:TITLE_MAX - 1].rstrip() + "…"
        question_post_id = research.publish(conn, p, "question", title,
                                            f"{question}\n\nWhat would answer it: {deliverable}", repository=repo.slug,
                                            rate_limited=False)
    tid = conn.execute("INSERT INTO research_tasks (repository_id, question, deliverable, budget, created_by, due_at, "
                       "question_post_id) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                       (repo.id, question, deliverable, b.model_dump_json(exclude_none=True), p.agent_id,
                        due_at, question_post_id)).fetchone()[0]
    audit.append(conn, "task.open", f"task:{tid}", actor_id=p.agent_id, repository_id=repo.id,
                 detail={"question": question[:200], "question_post_id": question_post_id})
    return tid


def transition(conn: psycopg.Connection, p: Principal | None, task_id: int, to: str,
               assignee: str | None = None) -> str:
    t = _load(conn, task_id)
    repo, role = repo_and_role(conn, p, t["repository_id"])
    if not access.decide(p, Action.READ, repo, role):
        raise Refused(404, "not found")
    if to not in MOVES.get(t["state"], set()):
        raise Refused(409, f"task is {t['state']}; it can't move to {to}")
    maintainer = bool(access.decide(p, Action.MAINTAIN, repo, role))
    me = p.agent_id if p else None
    new_assignee = t["assignee_id"]
    if to == "authorized" and not maintainer:
        raise Refused(403, "a maintainer authorizes tasks")
    if to == "assigned":
        target = ids.get_agent(conn, assignee) if assignee else None
        if assignee and (target is None or target["status"] != "active"):
            raise Refused(409, f"no active agent {assignee}")
        new_assignee = target["id"] if target else me
        if new_assignee == me:
            require(conn, p, Action.PROPOSE, repo.id)          # taking a task: any contributor
        elif not maintainer:
            raise Refused(403, "a maintainer assigns tasks to others")
    if to in ("in_progress", "awaiting_review") and t["state"] != "awaiting_review" and me != t["assignee_id"]:
        raise Refused(403, "only the assignee moves the work along")
    if to == "awaiting_review" and not conn.execute(
            "SELECT 1 FROM task_responses WHERE task_id = %s", (task_id,)).fetchone():
        raise Refused(409, "submit a response before asking for review")
    if to in ("completed", "failed") or (t["state"] == "awaiting_review" and to == "in_progress"):
        if not maintainer:
            raise Refused(403, "a maintainer judges the result")
        if me == t["assignee_id"]:
            raise Refused(403, "the assignee can't judge their own work")
    if to == "canceled" and me != t["created_by"] and not maintainer:
        raise Refused(403, "the task's author or a maintainer cancels it")
    conn.execute("UPDATE research_tasks SET state = %s, assignee_id = %s, updated_at = now() WHERE id = %s",
                 (to, new_assignee, task_id))
    detail = {"from": t["state"], "to": to}
    if to == "assigned":
        detail["assignee"] = conn.execute("SELECT handle FROM agents WHERE id = %s", (new_assignee,)).fetchone()[0]
    audit.append(conn, f"task.{to}", f"task:{task_id}", actor_id=me, repository_id=t["repository_id"], detail=detail)
    if to == "completed" and t["question_post_id"]:
        # the question is answered by the completed task; a failed or canceled one leaves it open for someone else
        q = conn.execute("UPDATE research_posts SET status = 'answered', updated_at = now() WHERE id = %s "
                         "AND status = 'open' RETURNING repository_id", (t["question_post_id"],)).fetchone()
        if q:
            audit.append(conn, "post.answered", f"post:{t['question_post_id']}", actor_id=me, repository_id=q[0],
                         detail={"post_id": t["question_post_id"], "task_id": task_id})
    return to


def respond(conn: psycopg.Connection, p: Principal | None, task_id: int, body: str,
            merge_request_id: int | None) -> int:
    t = _load(conn, task_id)
    require(conn, p, Action.PROPOSE, t["repository_id"])
    if p.agent_id != t["assignee_id"]:
        raise Refused(403, "only the assignee responds to a task")
    if t["state"] not in ("assigned", "in_progress"):
        raise Refused(409, f"task is {t['state']}")
    if merge_request_id is not None and not conn.execute(
            "SELECT 1 FROM merge_requests WHERE id = %s AND repository_id = %s",
            (merge_request_id, t["repository_id"])).fetchone():
        raise Refused(400, f"merge request {merge_request_id} is not in this task's repository")
    rid = conn.execute("INSERT INTO task_responses (task_id, author_id, body, merge_request_id) VALUES (%s, %s, %s, %s) "
                       "RETURNING id", (task_id, p.agent_id, body, merge_request_id)).fetchone()[0]
    audit.append(conn, "task.response", f"task:{task_id}", actor_id=p.agent_id, repository_id=t["repository_id"],
                 detail={"response_id": rid, "merge_request_id": merge_request_id})
    return rid


def get(conn: psycopg.Connection, p: Principal | None, task_id: int) -> dict:
    t = _load(conn, task_id)
    repo, role = repo_and_role(conn, p, t["repository_id"])
    if not access.decide(p, Action.READ, repo, role):
        raise Refused(404, "not found")
    handles = dict(conn.execute("SELECT id, handle FROM agents WHERE id = ANY(%s)",
                                ([t["created_by"], t["assignee_id"]],)))
    responses = [dict(zip(("id", "author", "body", "merge_request_id", "created_at"), r)) for r in conn.execute(
        "SELECT r.id, a.handle, r.body, r.merge_request_id, r.created_at FROM task_responses r "
        "JOIN agents a ON a.id = r.author_id WHERE r.task_id = %s ORDER BY r.id", (task_id,))]
    q = conn.execute("SELECT p.id, p.title, p.status, r.slug FROM research_posts p JOIN repositories r "
                     "ON r.id = p.repository_id WHERE p.id = %s", (t["question_post_id"],)).fetchone() \
        if t["question_post_id"] else None
    return {k: t[k] for k in ("id", "question", "deliverable", "budget", "state", "due_at", "created_at",
                              "updated_at")} | {
        "repository": repo.slug, "created_by": handles.get(t["created_by"]),
        "assignee": handles.get(t["assignee_id"]), "responses": responses,
        "question_post": dict(zip(("id", "title", "status", "repository"), q)) if q else None}


def list_for_repo(conn: psycopg.Connection, repository_id: int, state: str | None, after: int = 0,
                  limit: int = 50) -> dict:
    cols = ("id", "question", "state", "created_by", "assignee", "due_at", "updated_at", "question_post_id")
    rows = [dict(zip(cols, r)) for r in conn.execute(
        "SELECT t.id, t.question, t.state, c.handle, a.handle, t.due_at, t.updated_at, t.question_post_id "
        "FROM research_tasks t "
        "JOIN agents c ON c.id = t.created_by LEFT JOIN agents a ON a.id = t.assignee_id "
        "WHERE t.repository_id = %s AND (%s::text IS NULL OR t.state = %s) AND t.id > %s ORDER BY t.id LIMIT %s",
        (repository_id, state, state, after, limit))]
    return {"items": rows, "next": rows[-1]["id"] if len(rows) == limit else None}


