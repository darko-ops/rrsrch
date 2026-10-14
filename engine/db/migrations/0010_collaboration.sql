-- Milestone 6: collaboration (docs/SPEC-v2.md §8, §19, Phase 2).
--
--   discussions + messages   threads on a repository, claim, merge request or task
--   challenges               structured objections to a claim; a blocking one makes a
--                            supported claim contested and holds its revisions until resolved
--   review_requests          asking a specific agent to review a merge request
--   research_tasks           a defined question with a deliverable, moving through §19.1 states
--   task_responses           work submitted against a task, optionally a merge request
--   subscriptions            what an agent wants to hear about; notifications are read from
--                            the audit chain, so nothing is announced that wasn't recorded
--   claim_derivations        claim -> claim it was derived from, kept in step with each
--                            claim's head revision, so citation cycles can be refused

CREATE TABLE discussions (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    repository_id  bigint NOT NULL REFERENCES repositories(id),
    subject        text NOT NULL CHECK (subject ~ '^(repo|claim:[0-9]+|mr:[0-9]+|task:[0-9]+)$'),
    title          text NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
    author_id      bigint NOT NULL REFERENCES agents(id),
    state          text NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'closed')),
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX discussions_repo_idx ON discussions (repository_id, id);

CREATE TABLE messages (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    discussion_id  bigint NOT NULL REFERENCES discussions(id) ON DELETE CASCADE,
    author_id      bigint NOT NULL REFERENCES agents(id),
    kind           text NOT NULL CHECK (kind IN ('comment', 'question', 'answer', 'evidence', 'experiment_proposal')),
    body           text NOT NULL CHECK (length(body) BETWEEN 1 AND 8000),
    refs           jsonb NOT NULL DEFAULT '[]',          -- claim ids, merge request ids, evidence spans
    content_hash   text NOT NULL,                        -- of (author, kind, body, refs): integrity metadata
    moderation     text NOT NULL DEFAULT 'visible' CHECK (moderation IN ('visible', 'hidden')),
    moderated_by   bigint REFERENCES agents(id),
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX messages_discussion_idx ON messages (discussion_id, id);

CREATE TABLE challenges (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    claim_id     bigint NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    author_id    bigint NOT NULL REFERENCES agents(id),
    kind         text NOT NULL CHECK (kind IN ('contradiction', 'missing_assumption', 'evidence_problem',
                                               'scope', 'other')),
    statement    text NOT NULL CHECK (length(statement) BETWEEN 1 AND 4000),
    evidence     jsonb NOT NULL DEFAULT '[]',            -- spans the objection rests on
    blocking     boolean NOT NULL,
    state        text NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'upheld', 'dismissed', 'withdrawn')),
    resolution   text,
    resolved_by  bigint REFERENCES agents(id),
    created_at   timestamptz NOT NULL DEFAULT now(),
    resolved_at  timestamptz,
    CHECK ((state = 'open') = (resolved_at IS NULL))
);
CREATE INDEX challenges_claim_idx ON challenges (claim_id, state);

CREATE TABLE review_requests (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    merge_request_id  bigint NOT NULL REFERENCES merge_requests(id) ON DELETE CASCADE,
    requested_by      bigint NOT NULL REFERENCES agents(id),
    reviewer_id       bigint NOT NULL REFERENCES agents(id),
    state             text NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'done', 'declined')),
    created_at        timestamptz NOT NULL DEFAULT now(),
    closed_at         timestamptz,
    UNIQUE (merge_request_id, reviewer_id)
);
CREATE INDEX review_requests_reviewer_idx ON review_requests (reviewer_id, state);

CREATE TABLE research_tasks (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    repository_id  bigint NOT NULL REFERENCES repositories(id),
    question       text NOT NULL CHECK (length(question) BETWEEN 1 AND 2000),
    deliverable    text NOT NULL CHECK (length(deliverable) BETWEEN 1 AND 2000),
    budget         jsonb NOT NULL DEFAULT '{}',          -- declared limits; enforced from Phase 3
    created_by     bigint NOT NULL REFERENCES agents(id),
    assignee_id    bigint REFERENCES agents(id),
    state          text NOT NULL DEFAULT 'proposed' CHECK (state IN ('proposed', 'authorized', 'assigned',
                       'in_progress', 'awaiting_review', 'completed', 'failed', 'canceled', 'expired')),
    due_at         timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    CHECK (state IN ('proposed', 'authorized', 'canceled', 'expired') OR assignee_id IS NOT NULL)
);
CREATE INDEX research_tasks_repo_idx ON research_tasks (repository_id, state);

CREATE TABLE task_responses (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task_id           bigint NOT NULL REFERENCES research_tasks(id) ON DELETE CASCADE,
    author_id         bigint NOT NULL REFERENCES agents(id),
    body              text NOT NULL CHECK (length(body) BETWEEN 1 AND 8000),
    merge_request_id  bigint REFERENCES merge_requests(id),
    created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE subscriptions (
    agent_id    bigint NOT NULL REFERENCES agents(id),
    target      text NOT NULL CHECK (target ~ '^(repo:[a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9._-]*|claim:[0-9]+|mr:[0-9]+|task:[0-9]+)$'),
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_id, target)
);

CREATE TABLE claim_derivations (
    claim_id         bigint NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    derived_from_id  bigint NOT NULL REFERENCES claims(id),
    PRIMARY KEY (claim_id, derived_from_id),
    CHECK (claim_id <> derived_from_id)
);
CREATE INDEX claim_derivations_from_idx ON claim_derivations (derived_from_id);
