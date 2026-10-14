-- Milestone 1: the canonical knowledge schema (docs/SPEC-v2.md §7, §17).
--
-- The ledger so far is one implicit collection of claims. This makes the
-- structure explicit so claims from more than one contributor and more than
-- one topic can live side by side:
--
--   organizations -> agents         who contributed (a deployment, not a model)
--   organizations -> repositories   the collection a claim belongs to
--   claims                          gain a type, a review state and a repository
--   claim_revisions                 immutable, hash-chained content of each claim
--   evidence + evidence_links       the passages a claim rests on, and how
--   verification_runs               which checks a revision passed, under which policy
--
-- Existing claims move into the pilot repository rrsrch/msc-knee-oa. Their
-- revisions, evidence and verification runs need the canonical hash, which is
-- computed in Python (rrsrch.knowledge.store.sync), not here.

CREATE TABLE organizations (
    id            text PRIMARY KEY CHECK (id ~ '^[a-z0-9][a-z0-9-]{0,38}$'),
    name          text NOT NULL,
    verification  text NOT NULL DEFAULT 'unverified' CHECK (verification IN ('unverified', 'verified')),
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- An authenticated contributor: a deployment or service, owned by an organization.
CREATE TABLE agents (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    handle           text NOT NULL UNIQUE CHECK (handle ~ '^[a-z0-9][a-z0-9-]{0,62}$'),
    organization_id  text NOT NULL REFERENCES organizations(id),
    kind             text NOT NULL CHECK (kind IN ('service', 'model', 'human')),
    capabilities     text[] NOT NULL DEFAULT '{}',
    status           text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'revoked')),
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE repositories (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug                 text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]{0,38}/[a-z0-9][a-z0-9._-]{0,99}$'),
    organization_id      text NOT NULL REFERENCES organizations(id),
    topic                text NOT NULL,
    description          text NOT NULL DEFAULT '',
    visibility           text NOT NULL CHECK (visibility IN ('public', 'private')),
    contribution_policy  jsonb NOT NULL DEFAULT '{}',
    evidence_policy      jsonb NOT NULL DEFAULT '{}',
    policy_version       text NOT NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    CHECK (split_part(slug, '/', 1) = organization_id)
);

INSERT INTO organizations (id, name, verification) VALUES ('rrsrch', 'RRSRCH', 'verified');
INSERT INTO agents (handle, organization_id, kind, capabilities)
    VALUES ('rrsrch-reader', 'rrsrch', 'service', '{extract_claims}');
INSERT INTO repositories (slug, organization_id, topic, description, visibility,
                          contribution_policy, evidence_policy, policy_version)
VALUES ('rrsrch/msc-knee-oa', 'rrsrch',
        'Mesenchymal stromal cell therapy for knee osteoarthritis',
        'Claims from the included studies of eight meta-analyses, each anchored to an exact passage.',
        'public',
        '{"contributors": ["rrsrch-reader"]}',
        '{"span_anchored": true, "primary_sources_only": true, "gate": "self_check"}',
        'msc-v1');

ALTER TABLE claims
    ADD COLUMN repository_id bigint REFERENCES repositories(id),
    ADD COLUMN type          text CHECK (type IN ('factual', 'empirical', 'interpretive',
                                                  'hypothesis', 'procedural', 'predictive')),
    ADD COLUMN state         text CHECK (state IN ('draft', 'submitted', 'structurally_valid',
                                                   'under_review', 'supported', 'contested',
                                                   'rejected', 'stale', 'superseded', 'retracted')),
    ADD COLUMN agent_id      bigint REFERENCES agents(id);

-- Reader claims are findings measured in studies, and passed the reader's
-- rules against their own passage. No review policy has run on them yet, so
-- they are structurally valid, not supported.
UPDATE claims SET repository_id = (SELECT id FROM repositories WHERE slug = 'rrsrch/msc-knee-oa'),
                  type = 'empirical',
                  state = 'structurally_valid',
                  agent_id = (SELECT id FROM agents WHERE handle = 'rrsrch-reader');

ALTER TABLE claims
    ALTER COLUMN repository_id SET NOT NULL,
    ALTER COLUMN type SET NOT NULL,
    ALTER COLUMN state SET NOT NULL,
    ALTER COLUMN agent_id SET NOT NULL;
CREATE INDEX claims_repository_state_idx ON claims (repository_id, state);

-- One row per version of a claim's content. `content` is the canonical form
-- that `content_hash` was computed over (rrsrch.knowledge.canonical); the
-- parent's hash is part of the content, so revisions form a chain.
CREATE TABLE claim_revisions (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    claim_id      bigint NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    version       int NOT NULL CHECK (version >= 1),
    parent_id     bigint REFERENCES claim_revisions(id),
    content       jsonb NOT NULL,
    content_hash  text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    agent_id      bigint NOT NULL REFERENCES agents(id),
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (claim_id, version),
    CHECK ((version = 1) = (parent_id IS NULL))
);

-- Accepted history is never rewritten. Deleting the claim itself still
-- cascades, so a throwaway ledger can be cleared.
CREATE FUNCTION claim_revisions_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'claim_revisions are immutable (revision %)', OLD.id;
END $$;
CREATE TRIGGER claim_revisions_no_update BEFORE UPDATE ON claim_revisions
    FOR EACH ROW EXECUTE FUNCTION claim_revisions_immutable();

-- A bounded piece of a source a claim can rest on. For now always an exact
-- span of a hashed document; other kinds (experiment artifacts, datasets)
-- come later.
CREATE TABLE evidence (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind          text NOT NULL CHECK (kind IN ('document_span')),
    source_id     text NOT NULL REFERENCES sources(id),
    document_id   bigint NOT NULL REFERENCES documents(id),
    doc_sha256    text NOT NULL,
    span_start    int NOT NULL CHECK (span_start >= 0),
    span_end      int NOT NULL CHECK (span_end > span_start),
    excerpt       text NOT NULL,
    is_primary    boolean NOT NULL,               -- false for reviews and other derivative sources
    license       text,
    retrieved_at  timestamptz,                    -- when the snapshot was taken, when known
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, doc_sha256, span_start, span_end)
);

-- How a claim relates to a piece of evidence. A link says what a contributor
-- asserted; whether the evidence bears it out is a verification run's job.
CREATE TABLE evidence_links (
    claim_id     bigint NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    evidence_id  bigint NOT NULL REFERENCES evidence(id),
    relation     text NOT NULL CHECK (relation IN ('supports', 'contradicts', 'context')),
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (claim_id, evidence_id, relation)
);
CREATE INDEX evidence_links_evidence_idx ON evidence_links (evidence_id);

-- The checks one revision went through, under one policy version. Each check
-- names its kind (structural, integrity, provenance, source, empirical,
-- factual) so passing one is never read as passing another.
CREATE TABLE verification_runs (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    claim_revision_id  bigint NOT NULL REFERENCES claim_revisions(id) ON DELETE CASCADE,
    policy_version     text NOT NULL,
    checks             jsonb NOT NULL,
    passed             boolean NOT NULL,
    created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX verification_runs_revision_idx ON verification_runs (claim_revision_id);
