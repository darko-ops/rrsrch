-- Knowledge Health (docs/SOUNDINGS.md): how well the network keeps its knowledge, measured from the ledger, not
-- voted. A snapshot is stored at most hourly when the measure is read, so the trend is what was measured at the
-- time, never recomputed under later rules. Snapshots are append-only.

CREATE TABLE kh_snapshots (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    score                numeric(4, 1) CHECK (score BETWEEN 0 AND 100),        -- null when there are no live claims
    live_claims          int NOT NULL CHECK (live_claims >= 0),
    checked_claims       int NOT NULL CHECK (checked_claims >= 0 AND checked_claims <= live_claims),
    measures             jsonb NOT NULL CHECK (jsonb_typeof(measures) = 'object'),
    calculation_version  text NOT NULL CHECK (calculation_version ~ '^[a-z0-9.-]{1,20}$'),
    created_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX kh_snapshots_created_idx ON kh_snapshots (created_at);
CREATE TRIGGER kh_snapshots_immutable BEFORE UPDATE OR DELETE ON kh_snapshots
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
