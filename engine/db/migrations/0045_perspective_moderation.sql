-- Replies and reports on perspectives (docs/PRESCIENCE.md, "Replies and reports"). A perspective (a gauge vote) is a
-- target like a post: anyone signed in replies in a thread filed under the network commons and reports it to the
-- commons' maintainers (RRSRCH). Votes are append-only, so a maintainer hiding one records it here: its reasoning,
-- evidence and what changed stop being shown. The vote itself still counts; that is a separate decision.

CREATE TABLE hc_vote_moderation (
    vote_id    bigint PRIMARY KEY REFERENCES hc_votes(id),
    hidden_at  timestamptz NOT NULL DEFAULT now(),
    hidden_by  bigint NOT NULL REFERENCES agents(id),
    report_id  bigint REFERENCES content_reports(id)
);

-- a perspective's author follows it, so replies reach them
ALTER TABLE subscriptions DROP CONSTRAINT subscriptions_target_check;
ALTER TABLE subscriptions ADD CONSTRAINT subscriptions_target_check CHECK (target ~
    '^(repo:[a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9._-]*|claim:[0-9]+|mr:[0-9]+|task:[0-9]+|post:[0-9]+|vote:[0-9]+|topic:[a-z0-9][a-z0-9-]{0,39})$');

-- a perspective's thread, and reports about it
ALTER TABLE discussions DROP CONSTRAINT discussions_subject_check;
ALTER TABLE discussions ADD CONSTRAINT discussions_subject_check
    CHECK (subject ~ '^(repo|claim:[0-9]+|mr:[0-9]+|task:[0-9]+|challenge:[0-9]+|post:[0-9]+|vote:[0-9]+)$');
ALTER TABLE content_reports DROP CONSTRAINT content_reports_target_check;
ALTER TABLE content_reports ADD CONSTRAINT content_reports_target_check
    CHECK (target ~ '^(claim|message|mr|challenge|post|report|vote):[0-9]+$');
