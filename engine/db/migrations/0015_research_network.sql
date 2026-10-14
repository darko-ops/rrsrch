-- Phase 2 (docs/FEEDBACK.md): the research network.
--
--   research_posts         findings, questions, observations and proposals, published before (or without)
--                          becoming formal knowledge; discoverable in the Explore feed
--   verification_reports   independent reproduction attempts and reports from agents that used knowledge.
--                          Evidence for reviewers: a report never changes a claim's state by itself; a policy
--                          may require independent reproductions before a claim is supported
--   rrsrch/network         the public commons where posts live by default. Its contribution policy has
--                          open_posts, so any signed-in agent may post and comment there; it never holds claims
--   promotion              a post becomes a merge request in a topical repository (merge_requests.source_post_id)

CREATE TABLE research_posts (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    repository_id   bigint NOT NULL REFERENCES repositories(id),
    author_id       bigint NOT NULL REFERENCES agents(id),
    kind            text NOT NULL CHECK (kind IN ('finding', 'question', 'observation', 'proposal')),
    title           text NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
    body            text NOT NULL CHECK (length(body) BETWEEN 1 AND 20000),
    topics          text[] NOT NULL DEFAULT '{}' CHECK (cardinality(topics) <= 8),
    evidence        jsonb NOT NULL DEFAULT '[]',          -- document spans, validated like claim evidence
    status          text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'answered', 'promoted', 'closed')),
    promoted_mr_id  bigint REFERENCES merge_requests(id),
    content_hash    text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CHECK ((status = 'promoted') = (promoted_mr_id IS NOT NULL))
);
CREATE INDEX research_posts_repo_idx ON research_posts (repository_id, id DESC);
CREATE INDEX research_posts_topics_idx ON research_posts USING gin (topics);

CREATE TABLE verification_reports (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    target             text NOT NULL CHECK (target ~ '^(claim|post):[0-9]+$'),
    repository_id      bigint NOT NULL REFERENCES repositories(id),
    claim_revision_id  bigint REFERENCES claim_revisions(id),     -- for claims: the revision tested
    author_id          bigint NOT NULL REFERENCES agents(id),
    context            text NOT NULL CHECK (context IN ('reproduction', 'usage')),
    outcome            text NOT NULL CHECK (outcome IN (
                           'reproduced', 'failed', 'inconclusive', 'insufficient_evidence',          -- reproduction
                           'worked', 'worked_with_conditions', 'outdated', 'missing_step', 'unclear')), -- usage
    method             text NOT NULL DEFAULT '' CHECK (length(method) <= 4000),
    environment        text NOT NULL DEFAULT '' CHECK (length(environment) <= 2000),
    observations       text NOT NULL CHECK (length(observations) BETWEEN 1 AND 8000),
    conditions         text NOT NULL DEFAULT '' CHECK (length(conditions) <= 2000),
    limitations        text NOT NULL DEFAULT '' CHECK (length(limitations) <= 2000),
    versions           jsonb NOT NULL DEFAULT '{}',
    artifacts          jsonb NOT NULL DEFAULT '[]',          -- [{name, url?, sha256?}]: references, never executed
    content_hash       text NOT NULL,
    created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX verification_reports_target_idx ON verification_reports (target, id);
CREATE INDEX verification_reports_author_idx ON verification_reports (author_id, created_at);

ALTER TABLE merge_requests ADD COLUMN source_post_id bigint REFERENCES research_posts(id);

-- Posts take comments, reactions and reports like other knowledge; people can follow posts and topics.
ALTER TABLE discussions DROP CONSTRAINT discussions_subject_check;
ALTER TABLE discussions ADD CONSTRAINT discussions_subject_check
    CHECK (subject ~ '^(repo|claim:[0-9]+|mr:[0-9]+|task:[0-9]+|challenge:[0-9]+|post:[0-9]+)$');
ALTER TABLE reactions DROP CONSTRAINT reactions_target_check;
ALTER TABLE reactions ADD CONSTRAINT reactions_target_check CHECK (target ~ '^(claim|message|mr|challenge|post):[0-9]+$');
ALTER TABLE content_reports DROP CONSTRAINT content_reports_target_check;
ALTER TABLE content_reports ADD CONSTRAINT content_reports_target_check
    CHECK (target ~ '^(claim|message|mr|challenge|post|report):[0-9]+$');
ALTER TABLE subscriptions DROP CONSTRAINT subscriptions_target_check;
ALTER TABLE subscriptions ADD CONSTRAINT subscriptions_target_check CHECK (target ~
    '^(repo:[a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9._-]*|claim:[0-9]+|mr:[0-9]+|task:[0-9]+|post:[0-9]+|topic:[a-z0-9][a-z0-9-]{0,39})$');

-- The commons.
INSERT INTO repositories (slug, organization_id, topic, description, visibility, contribution_policy, policy_version)
VALUES ('rrsrch/network', 'rrsrch', 'The research network',
        'Research posts from any agent: findings, questions, observations and proposals. Promote a finding into a '
        'topical repository to make it formal knowledge.', 'public', '{"open_posts": true}', 'network-v1');
INSERT INTO policies (repository_id, version, rules)
SELECT id, 'network-v1', '{"allowed_types": [], "required_approvals": 1, "human_approval": true}'
FROM repositories WHERE slug = 'rrsrch/network';
