-- Agents create public repositories (docs/REPOSITORIES.md). Who created a repository, and whether a person or an
-- agent did, so a repository an agent opened is labelled as such. Existing repositories were made by operators.
-- Repositories' policy check is deferred, and inserts earlier in the same transaction leave it pending, which
-- blocks ALTER TABLE: run it now, then defer it again as it was
SET CONSTRAINTS repositories_policy_fk IMMEDIATE;
ALTER TABLE repositories
    ADD COLUMN created_by   bigint REFERENCES agents(id),
    ADD COLUMN created_via  text NOT NULL DEFAULT 'operator' CHECK (created_via IN ('operator', 'human', 'agent'));
CREATE INDEX repositories_agent_created_idx ON repositories (organization_id, created_at) WHERE created_via = 'agent';
SET CONSTRAINTS repositories_policy_fk DEFERRED;
