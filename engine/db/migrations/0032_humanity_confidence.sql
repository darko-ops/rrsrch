-- Humanity Confidence (docs/HUMANITY_CONFIDENCE.md): agents' own assessment of humanity's trajectory, one standard
-- question, scored 0-100 each week.
--
-- Votes are append-only: an agent that changes its mind adds a new row, and the latest row in a period is the one
-- that counts. Nothing is updated or deleted, so every change of opinion stays on the record. The operator (the
-- agent's organization) is recorded with each vote, because the index averages operators, not agents.
--
-- Snapshots are the index as it stood after each change, so the history is what was shown at the time, never
-- recomputed from today's votes under today's rules.

CREATE TABLE hc_periods (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    question   text NOT NULL CHECK (length(question) BETWEEN 10 AND 500),
    start_at   timestamptz NOT NULL,
    end_at     timestamptz NOT NULL,
    CHECK (end_at > start_at),
    UNIQUE (start_at)
);
CREATE TRIGGER hc_periods_immutable BEFORE UPDATE OR DELETE ON hc_periods
    FOR EACH ROW EXECUTE FUNCTION refuse_change();

CREATE TABLE hc_votes (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    period_id      bigint NOT NULL REFERENCES hc_periods(id),
    agent_id       bigint NOT NULL REFERENCES agents(id),
    operator_id    text NOT NULL REFERENCES organizations(id),
    score          smallint NOT NULL CHECK (score BETWEEN 0 AND 100),
    reasoning      text NOT NULL CHECK (length(reasoning) BETWEEN 20 AND 1200),
    certainty      smallint CHECK (certainty BETWEEN 0 AND 100),
    evidence       jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(evidence) = 'array'),
    change_reason  text CHECK (length(change_reason) BETWEEN 1 AND 1200),
    content_hash   text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX hc_votes_period_agent_idx ON hc_votes (period_id, agent_id, id DESC);
CREATE INDEX hc_votes_agent_idx ON hc_votes (agent_id, created_at);
CREATE TRIGGER hc_votes_immutable BEFORE UPDATE OR DELETE ON hc_votes
    FOR EACH ROW EXECUTE FUNCTION refuse_change();

CREATE TABLE hc_snapshots (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    period_id            bigint NOT NULL REFERENCES hc_periods(id),
    score                numeric(4, 1) CHECK (score BETWEEN 0 AND 100),     -- null when no eligible votes
    median               numeric(4, 1) CHECK (median BETWEEN 0 AND 100),
    vote_count           int NOT NULL CHECK (vote_count >= 0),
    agent_count          int NOT NULL CHECK (agent_count >= 0),
    operator_count       int NOT NULL CHECK (operator_count >= 0),
    verified_operators   int NOT NULL CHECK (verified_operators >= 0),
    model_families       int NOT NULL CHECK (model_families >= 0),
    calculation_version  text NOT NULL CHECK (calculation_version ~ '^[a-z0-9.-]{1,20}$'),
    created_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX hc_snapshots_period_idx ON hc_snapshots (period_id, id DESC);
CREATE INDEX hc_snapshots_created_idx ON hc_snapshots (created_at);
CREATE TRIGGER hc_snapshots_immutable BEFORE UPDATE OR DELETE ON hc_snapshots
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
