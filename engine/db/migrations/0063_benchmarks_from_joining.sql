-- The first backfill of benchmark_snapshots stored a 0 for every agent on every past day, including days before the
-- agent joined, so the Sparks chart ran flat for weeks before anyone was active. benchmarks.snapshot() now skips an
-- agent for a day before it joined; drop the rows it should never have written.
DELETE FROM benchmark_snapshots s
USING agents a
WHERE a.id = s.agent_id AND s.day < (a.created_at AT TIME ZONE 'UTC')::date;
