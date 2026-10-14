-- Milestone 2: identity and repository permissions (docs/SPEC-v2.md §14).
--
-- The authenticated principal is an agent: a deployment, service or person,
-- always owned by an organization (its operator). An agent proves who it is
-- with an API key; what it may do is the overlap of three things, decided by
-- rrsrch.identity.access:
--
--   the key's scopes      what this credential was issued for
--   the agent's role      in the repository (memberships), or as an org admin
--   the repository        public repositories can be read by anyone
--
-- Keys are short-lived and stored only as a hash: the secret is shown once,
-- at issue. Revoking an agent revokes every key it holds.

ALTER TABLE agents
    ADD COLUMN org_role    text NOT NULL DEFAULT 'member' CHECK (org_role IN ('member', 'admin')),
    ADD COLUMN model       text,                                -- model/provider, if the operator discloses it
    ADD COLUMN revoked_at  timestamptz,
    ADD CONSTRAINT agents_revoked_when CHECK ((status = 'revoked') = (revoked_at IS NOT NULL));

CREATE TABLE api_keys (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agent_id     bigint NOT NULL REFERENCES agents(id),
    prefix       text NOT NULL UNIQUE CHECK (prefix ~ '^[0-9a-f]{12}$'),   -- public half, used to look the key up
    secret_hash  text NOT NULL CHECK (secret_hash ~ '^[0-9a-f]{64}$'),     -- sha256 of the secret half
    scopes       text[] NOT NULL CHECK (cardinality(scopes) > 0 AND scopes <@ ARRAY[
                     'read', 'propose', 'review', 'maintain', 'administer', 'agents']::text[]),
    label        text NOT NULL DEFAULT '',
    created_at   timestamptz NOT NULL DEFAULT now(),
    expires_at   timestamptz NOT NULL,
    revoked_at   timestamptz,
    last_used_at timestamptz,
    CHECK (expires_at > created_at AND expires_at <= created_at + interval '90 days')
);
CREATE INDEX api_keys_agent_idx ON api_keys (agent_id);

CREATE TABLE memberships (
    repository_id  bigint NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    agent_id       bigint NOT NULL REFERENCES agents(id),
    role           text NOT NULL CHECK (role IN ('observer', 'contributor', 'reviewer', 'maintainer', 'owner')),
    granted_by     bigint REFERENCES agents(id),                -- null when granted by the operator (seed or CLI)
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (repository_id, agent_id)
);
CREATE INDEX memberships_agent_idx ON memberships (agent_id);

-- The reader contributes to the pilot; nothing else is granted by default.
INSERT INTO memberships (repository_id, agent_id, role)
SELECT r.id, a.id, 'contributor' FROM repositories r, agents a
WHERE r.slug = 'rrsrch/msc-knee-oa' AND a.handle = 'rrsrch-reader';
