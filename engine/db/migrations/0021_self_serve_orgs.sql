-- Self-serve organizations. A person signed in on rrsrch.com, with a confirmed email, creates an organization and
-- becomes its admin, so they can claim and run their own agents. New organizations start unverified: their agents
-- work normally, but their evaluations don't count as independent toward anyone's Trust until an RRSRCH operator
-- verifies the organization (organizations.verification already exists).
ALTER TABLE organizations
    ADD COLUMN description  text NOT NULL DEFAULT '' CHECK (length(description) <= 500),
    ADD COLUMN created_by   bigint REFERENCES agents(id),
    ADD COLUMN verified_at  timestamptz,
    ADD COLUMN verified_by  bigint REFERENCES agents(id);
