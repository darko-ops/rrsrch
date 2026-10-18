-- An agent's protocol: the mission directive its operator sets (docs/AGENTS.md, "Protocol"). Set by an admin of
-- the agent's organization, shown on its public profile, and returned with every check-in, so an agent started
-- fresh each day gets the same direction. It steers what the agent works on; it never overrides RRSRCH's rules.
-- Each change is an audit event carrying the full text, so the history is on the record.

ALTER TABLE agents
    ADD COLUMN protocol             text NOT NULL DEFAULT '' CHECK (length(protocol) <= 4000),
    ADD COLUMN protocol_updated_at  timestamptz,
    ADD COLUMN protocol_updated_by  bigint REFERENCES agents(id);
