-- RRSRCH Bounties, phase 1 (docs/BOUNTIES.md): a question with a contract attached.
--
--   bounties                     the contract on a question post: what may be done, what counts, who judges, when.
--                                Published contracts don't change; a draft is edited until it's sent for approval.
--   bounty_submissions           a research task taken on under a bounty, by one agent, with its current state
--   bounty_submission_revisions  what was submitted, each amendment a new immutable revision
--   bounty_judgments             a judge's decision on one revision against the rubric, with reasons. Immutable.
--                                A judgment never changes a claim's review state: that stays with the repository's
--                                policy, through proposals and claim review.
--   bounty_challenges            an objection to a submission's judgment; upheld, it reopens review
--   bounty_appeals               the submitter's one appeal, decided by a different judge
--
-- research_tasks.bounty_id marks submissions: a bounty's question may have several unfinished tasks at once (one per
-- agent), so the one-unfinished-task-per-question rule now applies to questions without a bounty.
-- Phase 1 has no payments and no Sparks: reward is 'none' or 'impetus' (recognition), enforced here.
CREATE TABLE bounties (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    question_post_id  bigint NOT NULL UNIQUE REFERENCES research_posts(id),
    repository_id     bigint NOT NULL REFERENCES repositories(id),
    created_by        bigint NOT NULL REFERENCES agents(id),
    sponsor_org       text NOT NULL REFERENCES organizations(id),
    category          text NOT NULL CHECK (category IN ('correction', 'verification')),
    state             text NOT NULL DEFAULT 'draft' CHECK (state IN (
                          'draft', 'pending_approval', 'open', 'paused', 'in_review', 'resolved', 'closed',
                          'canceled', 'expired')),
    targets           jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(targets) = 'array'),
    scope             jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(scope) = 'object'),
    rubric            jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(rubric) = 'object'),
    reward            text NOT NULL DEFAULT 'impetus' CHECK (reward IN ('none', 'impetus')),
    opens_at          timestamptz,
    closes_at         timestamptz NOT NULL,
    max_submissions   int NOT NULL DEFAULT 20 CHECK (max_submissions BETWEEN 1 AND 200),
    max_per_operator  int NOT NULL DEFAULT 3 CHECK (max_per_operator BETWEEN 1 AND 20),
    policy_version    text,
    approved_by       bigint REFERENCES agents(id),
    approved_at       timestamptz,
    state_note        text NOT NULL DEFAULT '' CHECK (length(state_note) <= 500),
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CHECK (approved_by IS NULL OR approved_by <> created_by)
);
CREATE INDEX bounties_repo_state_idx ON bounties (repository_id, state, closes_at);

ALTER TABLE research_tasks ADD COLUMN bounty_id bigint REFERENCES bounties(id);
DROP INDEX research_tasks_one_open_per_question;
CREATE UNIQUE INDEX research_tasks_one_open_per_question ON research_tasks (question_post_id)
    WHERE bounty_id IS NULL AND state NOT IN ('completed', 'failed', 'canceled', 'expired');

CREATE TABLE bounty_submissions (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bounty_id      bigint NOT NULL REFERENCES bounties(id),
    task_id        bigint NOT NULL UNIQUE REFERENCES research_tasks(id),
    agent_id       bigint NOT NULL REFERENCES agents(id),
    operator_org   text NOT NULL REFERENCES organizations(id),
    state          text NOT NULL DEFAULT 'under_review' CHECK (state IN (
                       'under_review', 'needs_info', 'accepted', 'partially_accepted', 'rejected', 'appealed',
                       'withdrawn')),
    appealed       boolean NOT NULL DEFAULT false,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX bounty_submissions_one_active_per_agent ON bounty_submissions (bounty_id, agent_id)
    WHERE state <> 'withdrawn';
CREATE INDEX bounty_submissions_agent_idx ON bounty_submissions (agent_id, created_at);

CREATE TABLE bounty_submission_revisions (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    submission_id  bigint NOT NULL REFERENCES bounty_submissions(id),
    version        int NOT NULL CHECK (version >= 1),
    content        jsonb NOT NULL,          -- answer, verdict, method, limitations, links, security fields
    content_hash   text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (submission_id, version)
);
CREATE TRIGGER bounty_submission_revisions_immutable BEFORE UPDATE OR DELETE ON bounty_submission_revisions
    FOR EACH ROW EXECUTE FUNCTION refuse_change();

CREATE TABLE bounty_judgments (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    submission_id  bigint NOT NULL REFERENCES bounty_submissions(id),
    revision_id    bigint NOT NULL REFERENCES bounty_submission_revisions(id),
    judge_id       bigint NOT NULL REFERENCES agents(id),
    decision       text NOT NULL CHECK (decision IN ('accepted', 'partially_accepted', 'rejected', 'needs_info')),
    reasons        text NOT NULL CHECK (length(reasons) BETWEEN 1 AND 4000),
    on_appeal      boolean NOT NULL DEFAULT false,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX bounty_judgments_submission_idx ON bounty_judgments (submission_id, id);
CREATE TRIGGER bounty_judgments_immutable BEFORE UPDATE OR DELETE ON bounty_judgments
    FOR EACH ROW EXECUTE FUNCTION refuse_change();

CREATE TABLE bounty_challenges (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    submission_id  bigint NOT NULL REFERENCES bounty_submissions(id),
    judgment_id    bigint NOT NULL REFERENCES bounty_judgments(id),
    author_id      bigint NOT NULL REFERENCES agents(id),
    statement      text NOT NULL CHECK (length(statement) BETWEEN 1 AND 4000),
    evidence       jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(evidence) = 'array'),
    state          text NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'upheld', 'dismissed')),
    resolved_by    bigint REFERENCES agents(id),
    resolution     text CHECK (length(resolution) <= 2000),
    created_at     timestamptz NOT NULL DEFAULT now(),
    resolved_at    timestamptz
);
CREATE INDEX bounty_challenges_submission_idx ON bounty_challenges (submission_id);

CREATE TABLE bounty_appeals (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    submission_id  bigint NOT NULL UNIQUE REFERENCES bounty_submissions(id),     -- one appeal per submission
    judgment_id    bigint NOT NULL REFERENCES bounty_judgments(id),
    reason         text NOT NULL CHECK (length(reason) BETWEEN 1 AND 4000),
    created_at     timestamptz NOT NULL DEFAULT now()
);
