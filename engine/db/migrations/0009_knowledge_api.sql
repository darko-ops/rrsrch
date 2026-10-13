-- Milestone 4: the knowledge API (docs/SPEC-v2.md §18.1–18.2).
--
-- claims.search: full-text index over what a claim says, for GET /v1/search.
-- idempotency_keys: a write retried with the same Idempotency-Key returns the
-- first response instead of acting twice; reusing a key for a different
-- request is refused.

ALTER TABLE claims ADD COLUMN search tsvector
    GENERATED ALWAYS AS (to_tsvector('english', text)) STORED;
CREATE INDEX claims_search_idx ON claims USING gin (search);

CREATE TABLE idempotency_keys (
    agent_id      bigint NOT NULL REFERENCES agents(id),
    key           text NOT NULL CHECK (length(key) BETWEEN 1 AND 200),
    request_hash  text NOT NULL,                  -- method, path and canonical body
    status        int NOT NULL,
    response      jsonb NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_id, key)
);
