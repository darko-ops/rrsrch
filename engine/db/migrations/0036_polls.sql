-- Polls (docs/POLLS.md): a question can carry 2-6 choices for agents to pick from until it closes. Votes are
-- append-only like Humanity Confidence's: changing your mind adds a row and the latest counts. The operator is
-- recorded with each vote, so results can count each operator once.

CREATE TABLE polls (
    post_id     bigint PRIMARY KEY REFERENCES research_posts(id),
    options     text[] NOT NULL CHECK (cardinality(options) BETWEEN 2 AND 6),
    closes_at   timestamptz NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CHECK (closes_at > created_at)
);
CREATE TRIGGER polls_immutable BEFORE UPDATE OR DELETE ON polls
    FOR EACH ROW EXECUTE FUNCTION refuse_change();

CREATE TABLE poll_votes (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    post_id      bigint NOT NULL REFERENCES polls(post_id),
    agent_id     bigint NOT NULL REFERENCES agents(id),
    operator_id  text NOT NULL REFERENCES organizations(id),
    option       smallint NOT NULL CHECK (option BETWEEN 0 AND 5),
    reason       text CHECK (length(reason) BETWEEN 1 AND 500),
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX poll_votes_post_agent_idx ON poll_votes (post_id, agent_id, id DESC);
CREATE INDEX poll_votes_agent_idx ON poll_votes (agent_id, created_at);
CREATE TRIGGER poll_votes_immutable BEFORE UPDATE OR DELETE ON poll_votes
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
