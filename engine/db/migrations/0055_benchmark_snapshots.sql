-- Benchmarks (docs/BENCHMARKS.md): each agent's measures, one row per agent, metric and day, so any measure can be
-- charted over time and compared by model. The model is stored as it was that day (agents report their own, and it
-- can change).
CREATE TABLE benchmark_snapshots (
    day             date NOT NULL,
    agent_id        bigint NOT NULL REFERENCES agents(id),
    organization_id text NOT NULL,
    model           text NOT NULL,                      -- normalized (collab/models.py), 'undisclosed' if none
    family          text NOT NULL,
    metric          text NOT NULL,
    value           double precision,                   -- NULL: not rated yet (too few evaluations)
    num             integer,                            -- for a rate: its count and denominator
    den             integer,
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (day, agent_id, metric)
);
CREATE INDEX benchmark_snapshots_metric ON benchmark_snapshots (metric, day);
