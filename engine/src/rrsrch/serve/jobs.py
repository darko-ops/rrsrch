"""Answers as background jobs: submit a question, get a ticket, check back.

One worker, because one model answers one question at a time; more would only
make every answer slower. The same question asked again while its job is
waiting or running, or within `fresh_for` seconds of finishing, gets that job
instead of a new one: the cache and the de-duplication are the same rule.
The queue is bounded, so a burst of questions is refused rather than piling
up hours of work.
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import psycopg

from ..ledger import db

COLS = ("id", "question", "status", "stage", "result", "error", "created_at", "started_at", "finished_at")


class QueueFull(Exception):
    pass


def question_key(question: str) -> str:
    return " ".join(question.lower().split()).rstrip("?.! ")


class AnswerJobs:
    def __init__(self, connect: Callable[[], psycopg.Connection], make_llm: Callable, answer: Callable, *,
                 fresh_for: int = 1800, max_waiting: int = 20, workers: int = 1):
        self.connect, self.make_llm, self.answer = connect, make_llm, answer
        self.fresh_for, self.max_waiting = fresh_for, max_waiting
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="answer")

    def _row(self, conn, job_id) -> dict | None:
        row = conn.execute(f"SELECT {', '.join(COLS)} FROM answer_jobs WHERE id = %s", (job_id,)).fetchone()
        return dict(zip(COLS, row)) if row else None

    def submit(self, question: str) -> tuple[dict, bool]:
        """(job, created). An existing waiting, running or fresh job for the same question is reused."""
        key = question_key(question)
        with self.connect() as conn:
            db.migrate(conn)
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"answer:{key}",))
            same = conn.execute(
                "SELECT id FROM answer_jobs WHERE question_key = %s AND (status IN ('queued', 'running') "
                "OR (status = 'done' AND finished_at > now() - make_interval(secs => %s))) "
                "ORDER BY created_at DESC LIMIT 1", (key, self.fresh_for)).fetchone()
            if same:
                return self._row(conn, same[0]), False
            waiting = conn.execute("SELECT count(*) FROM answer_jobs WHERE status = 'queued'").fetchone()[0]
            if waiting >= self.max_waiting:
                raise QueueFull(f"{waiting} questions are already waiting; try again in a few minutes")
            job_id = conn.execute("INSERT INTO answer_jobs (question, question_key, stage) VALUES (%s, %s, %s) "
                                  "RETURNING id", (question, key, "waiting to start")).fetchone()[0]
            job = self._row(conn, job_id)
        self.pool.submit(self._run, job_id)
        return job, True

    def get(self, job_id: str) -> dict | None:
        try:
            uuid.UUID(str(job_id))
        except ValueError:
            return None
        with self.connect() as conn:
            return self._row(conn, job_id)

    def _stage(self, job_id, stage: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE answer_jobs SET stage = %s WHERE id = %s", (stage, job_id))

    def _run(self, job_id) -> None:
        with self.connect() as conn:
            row = conn.execute("UPDATE answer_jobs SET status = 'running', started_at = now(), stage = 'starting' "
                               "WHERE id = %s AND status = 'queued' RETURNING question", (job_id,)).fetchone()
        if row is None:
            return
        try:
            llm = self.make_llm()
            with self.connect() as conn:
                result = self.answer(conn, llm, row[0], progress=lambda s: self._stage(job_id, s))
            with self.connect() as conn:
                conn.execute("UPDATE answer_jobs SET status = 'done', stage = 'done', result = %s, finished_at = now() "
                             "WHERE id = %s", (json.dumps(result, default=str), job_id))
        except Exception as e:  # noqa: BLE001  a failed answer is a recorded outcome, not a crash
            with self.connect() as conn:
                conn.execute("UPDATE answer_jobs SET status = 'failed', stage = 'failed', error = %s, "
                             "finished_at = now() WHERE id = %s", (str(e)[:400], job_id))

    def recover(self) -> int:
        """After a restart: a job that was running is lost (failed); waiting jobs are started again."""
        with self.connect() as conn:
            db.migrate(conn)
            conn.execute("UPDATE answer_jobs SET status = 'failed', stage = 'failed', finished_at = now(), "
                         "error = 'the engine restarted while answering; ask again' WHERE status = 'running'")
            waiting = [r[0] for r in conn.execute("SELECT id FROM answer_jobs WHERE status = 'queued' ORDER BY created_at")]
        for job_id in waiting:
            self.pool.submit(self._run, job_id)
        return len(waiting)
