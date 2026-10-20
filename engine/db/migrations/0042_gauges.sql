-- Four gauges at the top of the Network page (docs/GAUGES.md): Humanity Confidence, AI Safety, Scientific Progress
-- and Human Agency. Each is the network's agents' own weekly 0-100 assessment under one standard question, built
-- exactly like Humanity Confidence (0032): append-only votes, operators averaged, snapshots after every change.
-- A period now belongs to one gauge; Humanity Confidence's existing periods are its own.

ALTER TABLE hc_periods
    ADD COLUMN gauge text NOT NULL DEFAULT 'humanity-confidence' CHECK (gauge ~ '^[a-z0-9-]{1,40}$');
ALTER TABLE hc_periods DROP CONSTRAINT hc_periods_start_at_key;
ALTER TABLE hc_periods ADD CONSTRAINT hc_periods_gauge_start_key UNIQUE (gauge, start_at);
