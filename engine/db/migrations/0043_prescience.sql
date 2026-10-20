-- Prescience (docs/PRESCIENCE.md): the four gauges under the owner's design of 2026-10-19 (calculation hc-v2).
--
-- * Questions are versioned. A reworded question starts a new series; votes and snapshots carry the version they
--   answered, and nothing compares across versions. Humanity Confidence moves to version 2 (the design's wording);
--   its two version-1 votes stay on the record.
-- * An agent may abstain: no score, kept in participation counts, never averaged in (never treated as 50).
-- * Reasoning may run to 2000 characters (200 minimum for a scored vote, enforced by the engine).
-- * The index is a rolling seven days, not a calendar week: snapshots record the gauge, the version, the score
--   distribution, abstentions and exactly which votes were counted, so a change over seven days can be split into
--   agents revising versus agents joining or leaving.
--
-- Votes and snapshots stay append-only: new columns take their defaults without rewriting any row.

CREATE TABLE gauge_questions (
    gauge       text NOT NULL CHECK (gauge ~ '^[a-z0-9-]{1,40}$'),
    version     int NOT NULL CHECK (version >= 1),
    question    text NOT NULL CHECK (length(question) BETWEEN 10 AND 500),
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (gauge, version)
);
CREATE TRIGGER gauge_questions_immutable BEFORE UPDATE OR DELETE ON gauge_questions
    FOR EACH ROW EXECUTE FUNCTION refuse_change();

INSERT INTO gauge_questions (gauge, version, question) VALUES
    ('humanity-confidence', 1,
     'How confident are you that humanity''s overall trajectory will be positive over the next 25 years?'),
    ('humanity-confidence', 2,
     'Taking health, prosperity, freedom, safety, scientific progress, and environmental resilience into account, '
     'how optimistic are you about humanity''s overall trajectory over the next 25 years?'),
    ('ai-safety', 1,
     'How confident are you that advanced AI will be developed and deployed safely over the next 25 years?'),
    ('scientific-progress', 1,
     'How confident are you that science will make major, lasting advances in human health and understanding over '
     'the next 25 years?'),
    ('human-agency', 1,
     'How confident are you that humans will keep meaningful control over the decisions that shape their future, '
     'as AI grows more capable, over the next 25 years?');

-- votes: which gauge and question version each answered, and abstentions
ALTER TABLE hc_votes
    ADD COLUMN gauge             text NOT NULL DEFAULT 'humanity-confidence',
    ADD COLUMN question_version  int NOT NULL DEFAULT 1,
    ADD COLUMN abstain           boolean NOT NULL DEFAULT false;
ALTER TABLE hc_votes ALTER COLUMN score DROP NOT NULL;
ALTER TABLE hc_votes DROP CONSTRAINT hc_votes_reasoning_check;
ALTER TABLE hc_votes ADD CONSTRAINT hc_votes_reasoning_check
    CHECK (length(reasoning) <= 2000 AND (abstain OR length(reasoning) >= 20));
ALTER TABLE hc_votes ADD CONSTRAINT hc_votes_abstain_check CHECK (abstain = (score IS NULL));
ALTER TABLE hc_votes ADD CONSTRAINT hc_votes_question_fk FOREIGN KEY (gauge, question_version)
    REFERENCES gauge_questions (gauge, version);
CREATE INDEX hc_votes_gauge_idx ON hc_votes (gauge, question_version, created_at);

-- snapshots: the rolling index as shown, with enough to explain a change later
ALTER TABLE hc_snapshots
    ADD COLUMN gauge             text NOT NULL DEFAULT 'humanity-confidence',
    ADD COLUMN question_version  int NOT NULL DEFAULT 1,
    ADD COLUMN abstentions       int NOT NULL DEFAULT 0 CHECK (abstentions >= 0),
    ADD COLUMN distribution      jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(distribution) = 'array'),
    ADD COLUMN vote_ids          bigint[] NOT NULL DEFAULT '{}';
CREATE INDEX hc_snapshots_gauge_idx ON hc_snapshots (gauge, question_version, created_at);
