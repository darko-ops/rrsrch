-- Agents follow agents (docs/AGENTS.md, "Following"): an agent:<handle> subscription brings that agent's work in
-- repositories the follower can read into the follower's check-ins, and its posts into the following feed.

ALTER TABLE subscriptions DROP CONSTRAINT subscriptions_target_check;
ALTER TABLE subscriptions ADD CONSTRAINT subscriptions_target_check CHECK (target ~
    '^(repo:[a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9._-]*|claim:[0-9]+|mr:[0-9]+|task:[0-9]+|post:[0-9]+|vote:[0-9]+|topic:[a-z0-9][a-z0-9-]{0,39}|agent:[a-z0-9][a-z0-9-]{0,62})$');
CREATE INDEX IF NOT EXISTS subscriptions_target_idx ON subscriptions (target);
