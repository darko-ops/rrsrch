-- A person changes their handle (identity/onboarding.change_handle). An old handle stays theirs: nobody else can
-- take it, and links and lookups by it still find them.
CREATE TABLE handle_history (
    handle      text PRIMARY KEY CHECK (handle ~ '^[a-z0-9][a-z0-9-]{0,62}$'),
    agent_id    bigint NOT NULL REFERENCES agents(id),
    retired_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX handle_history_agent ON handle_history (agent_id);

ALTER TABLE agents ADD COLUMN handle_changed_at timestamptz;
