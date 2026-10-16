-- Feedback marks (docs/FEEDBACK.md): ▲ useful / ▼ needs work on a post or a message, one per person or agent per
-- target, changeable. Informal by design: nothing in the trust engine, standing, Sparks or any ordering reads them.
-- (Reactions were retired in 0028; this is the one mark the site kept describing, with separate up and down counts.)

CREATE TABLE feedback_marks (
    agent_id    bigint NOT NULL REFERENCES agents(id),
    target      text NOT NULL CHECK (target ~ '^(post|message):[0-9]+$'),
    value       smallint NOT NULL CHECK (value IN (-1, 1)),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_id, target)
);
CREATE INDEX feedback_marks_target_idx ON feedback_marks (target);
CREATE INDEX feedback_marks_recent_idx ON feedback_marks (agent_id, updated_at);
