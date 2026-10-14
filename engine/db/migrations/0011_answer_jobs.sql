-- Answers as jobs ("ask, then check back"). A written answer takes minutes on a local model, longer than
-- proxies in front of the engine will hold a request open (Cloudflare gives up at 100 s, Vercel at 300 s).
-- POST /v1/answers records a job and returns at once; GET /v1/answers/{id} reports its stage and, when done,
-- the answer. Jobs live here, not in memory, so a restart doesn't lose track of them.

CREATE TABLE answer_jobs (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    question      text NOT NULL,
    question_key  text NOT NULL,                  -- normalized, so repeats of a question share one job
    status        text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed')),
    stage         text,                           -- what it's doing now, for the reader
    result        jsonb,
    error         text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    started_at    timestamptz,
    finished_at   timestamptz,
    CHECK ((status = 'done') = (result IS NOT NULL))
);
CREATE INDEX answer_jobs_key_idx ON answer_jobs (question_key, created_at DESC);
CREATE INDEX answer_jobs_status_idx ON answer_jobs (status);
