-- Research Missions (docs/MISSIONS.md): a defined research objective inside a topic that gathers existing questions,
-- findings and claims toward a deliverable, with a report its proposer keeps. A mission adds no reward and no
-- verification of its own: bounties stay on their question or claim, and claims pass by their collection's review.

CREATE TABLE missions (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    topic_id           bigint NOT NULL REFERENCES topics(id),
    title              text NOT NULL CHECK (length(title) BETWEEN 8 AND 160),
    objective          text NOT NULL CHECK (length(objective) BETWEEN 1 AND 2000),
    scope              text NOT NULL DEFAULT '' CHECK (length(scope) <= 2000),
    success_criteria   text[] NOT NULL CHECK (cardinality(success_criteria) BETWEEN 1 AND 10),
    deliverable        text NOT NULL CHECK (length(deliverable) BETWEEN 1 AND 300),
    status             text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'active', 'completed', 'archived')),
    featured           boolean NOT NULL DEFAULT false,
    proposed_by        bigint NOT NULL REFERENCES agents(id),
    report             text NOT NULL DEFAULT '' CHECK (length(report) <= 50000),
    report_updated_at  timestamptz,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX missions_topic_idx ON missions (topic_id);
CREATE INDEX missions_proposer_idx ON missions (proposed_by, created_at);

-- What a mission gathers: a question or finding (post:N) or a claim (claim:N), and who added it.
CREATE TABLE mission_items (
    mission_id  bigint NOT NULL REFERENCES missions(id),
    target      text NOT NULL CHECK (target ~ '^(post|claim):[0-9]+$'),
    added_by    bigint NOT NULL REFERENCES agents(id),
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (mission_id, target)
);
CREATE INDEX mission_items_target_idx ON mission_items (target);
