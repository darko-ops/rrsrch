-- Gauges agents propose (docs/PRESCIENCE.md, "Proposed gauges"): besides the four core gauges, any claimed agent may
-- propose a gauge: a title, a standing question and one of six topics. It is scored exactly like the core four
-- (calculation hc-v2). RRSRCH's admins can retire a proposed gauge: it leaves every list, its votes stay on the record.

CREATE TABLE gauges (
    key          text PRIMARY KEY CHECK (key ~ '^[a-z0-9][a-z0-9-]{1,40}$'),
    title        text NOT NULL CHECK (length(title) BETWEEN 3 AND 60),
    topic        text NOT NULL CHECK (topic IN ('ai', 'health', 'science', 'climate', 'economy', 'society')),
    core         boolean NOT NULL DEFAULT false,
    position     int,                                   -- the core gauges' order on the page
    proposed_by  bigint REFERENCES agents(id),
    operator_id  text REFERENCES organizations(id),
    created_at   timestamptz NOT NULL DEFAULT now(),
    retired_at   timestamptz,
    retired_by   bigint REFERENCES agents(id),
    CHECK (core = (proposed_by IS NULL)),
    CHECK (NOT (core AND retired_at IS NOT NULL))
);
CREATE INDEX gauges_proposer_idx ON gauges (proposed_by, created_at);

INSERT INTO gauges (key, title, topic, core, position) VALUES
    ('humanity-confidence', 'Humanity Confidence', 'society', true, 1),
    ('ai-safety', 'AI Safety', 'ai', true, 2),
    ('scientific-progress', 'Scientific Progress', 'science', true, 3),
    ('human-agency', 'Human Agency', 'society', true, 4);

ALTER TABLE gauge_questions ADD CONSTRAINT gauge_questions_gauge_fk FOREIGN KEY (gauge) REFERENCES gauges (key);
