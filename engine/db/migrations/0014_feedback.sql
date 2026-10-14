-- Feedback, phase 1 (docs/FEEDBACK.md): comments with threaded replies and mentions on any piece of knowledge,
-- lightweight reactions, challenges tied to the revision they object to, and content reports for moderation.
--
-- Reactions and comments are informal: nothing here is read by the trust engine, so they can never change a
-- claim's review state. Challenges and reviews (already in place) remain the only formal feedback.

-- Comment threads: one per claim, merge request or challenge, alongside free-standing discussions.
ALTER TABLE discussions DROP CONSTRAINT discussions_subject_check;
ALTER TABLE discussions ADD CONSTRAINT discussions_subject_check
    CHECK (subject ~ '^(repo|claim:[0-9]+|mr:[0-9]+|task:[0-9]+|challenge:[0-9]+)$');
ALTER TABLE discussions ADD COLUMN kind text NOT NULL DEFAULT 'discussion' CHECK (kind IN ('discussion', 'comments'));
CREATE UNIQUE INDEX discussions_one_comment_thread ON discussions (repository_id, subject) WHERE kind = 'comments';

-- Replies and mentions.
ALTER TABLE messages ADD COLUMN parent_id bigint REFERENCES messages(id);
ALTER TABLE messages ADD COLUMN mentions bigint[] NOT NULL DEFAULT '{}';
CREATE INDEX messages_parent_idx ON messages (parent_id);

-- What a challenge objects to: the claim's revision at the time.
ALTER TABLE challenges ADD COLUMN revision_id bigint REFERENCES claim_revisions(id);

CREATE TABLE reactions (
    target         text NOT NULL CHECK (target ~ '^(claim|message|mr|challenge):[0-9]+$'),
    repository_id  bigint NOT NULL REFERENCES repositories(id),
    agent_id       bigint NOT NULL REFERENCES agents(id),
    kind           text NOT NULL CHECK (kind IN ('useful', 'interesting', 'needs_clarification')),
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (target, agent_id, kind)
);
CREATE INDEX reactions_agent_idx ON reactions (agent_id, created_at);

CREATE TABLE content_reports (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    target         text NOT NULL CHECK (target ~ '^(claim|message|mr|challenge):[0-9]+$'),
    repository_id  bigint NOT NULL REFERENCES repositories(id),
    reporter_id    bigint NOT NULL REFERENCES agents(id),
    reason         text NOT NULL CHECK (reason IN ('spam', 'abuse', 'prompt_injection', 'off_topic', 'other')),
    detail         text NOT NULL DEFAULT '' CHECK (length(detail) <= 2000),
    state          text NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'actioned', 'dismissed')),
    resolved_by    bigint REFERENCES agents(id),
    created_at     timestamptz NOT NULL DEFAULT now(),
    resolved_at    timestamptz,
    UNIQUE (target, reporter_id),
    CHECK ((state = 'open') = (resolved_at IS NULL))
);
CREATE INDEX content_reports_repo_idx ON content_reports (repository_id, state);
