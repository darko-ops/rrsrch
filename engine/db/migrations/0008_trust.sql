-- Milestone 3: the trust engine (docs/SPEC-v2.md §10, §17).
--
--   policies         a repository's acceptance rules, versioned and never edited:
--                    a new rule set is a new version
--   merge_requests   proposed claim content waiting to be accepted
--   reviews          one verdict per reviewer per merge request
--   audit_events     append-only, hash-chained record of every decision
--
-- Whether a change may merge is decided by rrsrch.trust.pipeline from these
-- rows alone; a model may propose content, never decide its acceptance.

CREATE FUNCTION refuse_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% rows are immutable', TG_TABLE_NAME;
END $$;

CREATE TABLE policies (
    repository_id  bigint NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    version        text NOT NULL CHECK (version ~ '^[A-Za-z0-9._-]{1,40}$'),
    rules          jsonb NOT NULL,
    created_by     bigint REFERENCES agents(id),        -- null when set by the operator
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (repository_id, version)
);
CREATE TRIGGER policies_immutable BEFORE UPDATE ON policies
    FOR EACH ROW EXECUTE FUNCTION refuse_change();

-- The pilot: only empirical claims, resting on primary studies, whose wording
-- passes the citation gate against their own passages, approved by a human.
INSERT INTO policies (repository_id, version, rules)
SELECT id, 'msc-v1', '{
    "allowed_types": ["empirical"],
    "min_sources": 1,
    "primary_evidence_only": true,
    "evidence_gate": true,
    "required_approvals": 1,
    "approvals_from_other_orgs_only": false,
    "human_approval": true
}' FROM repositories WHERE slug = 'rrsrch/msc-knee-oa';

-- Every repository names a policy version that exists. Deferred, so a
-- repository and its first policy can be created in one transaction.
ALTER TABLE repositories ADD CONSTRAINT repositories_policy_fk
    FOREIGN KEY (id, policy_version) REFERENCES policies (repository_id, version)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE merge_requests (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    repository_id       bigint NOT NULL REFERENCES repositories(id),
    claim_id            bigint REFERENCES claims(id),             -- null: proposes a new claim
    base_revision_id    bigint REFERENCES claim_revisions(id),    -- the head the change was written against
    content             jsonb NOT NULL,                           -- ClaimContent, canonical form
    content_hash        text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    author_id           bigint NOT NULL REFERENCES agents(id),
    policy_version      text NOT NULL,                            -- in force when it was opened
    state               text NOT NULL DEFAULT 'open'
                        CHECK (state IN ('open', 'merged', 'rejected', 'withdrawn')),
    created_at          timestamptz NOT NULL DEFAULT now(),
    decided_at          timestamptz,
    decided_by          bigint REFERENCES agents(id),
    merged_revision_id  bigint REFERENCES claim_revisions(id),
    CHECK ((claim_id IS NULL) = (base_revision_id IS NULL)),
    CHECK ((state = 'open') = (decided_at IS NULL)),
    CHECK ((state = 'merged') = (merged_revision_id IS NOT NULL))
);
CREATE INDEX merge_requests_repo_state_idx ON merge_requests (repository_id, state);

CREATE TABLE reviews (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    merge_request_id  bigint NOT NULL REFERENCES merge_requests(id) ON DELETE CASCADE,
    reviewer_id       bigint NOT NULL REFERENCES agents(id),
    verdict           text NOT NULL CHECK (verdict IN ('approve', 'request_changes', 'reject')),
    findings          text NOT NULL DEFAULT '',
    created_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (merge_request_id, reviewer_id)
);

-- A verification run is about a stored revision or about a proposal.
ALTER TABLE verification_runs
    ALTER COLUMN claim_revision_id DROP NOT NULL,
    ADD COLUMN merge_request_id bigint REFERENCES merge_requests(id) ON DELETE CASCADE,
    ADD CONSTRAINT verification_runs_one_target CHECK (num_nonnulls(claim_revision_id, merge_request_id) = 1);
CREATE INDEX verification_runs_mr_idx ON verification_runs (merge_request_id);

-- hash = sha256 of the canonical event including prev_hash; see rrsrch.trust.audit
CREATE TABLE audit_events (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at              timestamptz NOT NULL DEFAULT now(),
    actor_id        bigint REFERENCES agents(id),                 -- null: the operator, from the CLI
    action          text NOT NULL,
    target          text NOT NULL,                                -- e.g. repo:rrsrch/msc-knee-oa, agent:x, mr:12
    repository_id   bigint REFERENCES repositories(id),
    detail          jsonb NOT NULL DEFAULT '{}',
    policy_version  text,
    prev_hash       text CHECK (prev_hash ~ '^[0-9a-f]{64}$'),
    hash            text NOT NULL UNIQUE CHECK (hash ~ '^[0-9a-f]{64}$')
);
CREATE INDEX audit_events_repo_idx ON audit_events (repository_id, id);
CREATE TRIGGER audit_events_no_update BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
