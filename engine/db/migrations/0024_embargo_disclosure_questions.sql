-- Findings that wait for disclosure, the record of that disclosure, and tasks tied to the questions they answer.
--
--   claim_embargoes     a claim in a private repository held back until a date, while the people affected are told.
--                       While one is active the repository can't be made public (knowledge/repos.py). One active
--                       embargo per claim; a maintainer extends or lifts it, and every change is audited.
--   disclosure_events   who was told what, when, and what they answered: notices, replies, a maintainer's
--                       confirmation or dispute, fixes and advisories, corrections submitted upstream and their
--                       fate. Append-only: a mistaken entry is corrected by a later one that supersedes it. These are
--                       evidence recorded next to the claim's own evidence; they never change its review state.
--   research_tasks.question_post_id
--                       the question a task answers. New tasks always have one (collab/tasks.py); there were none
--                       before this migration in production, so nothing is backfilled. One unfinished task per
--                       question.
CREATE TABLE claim_embargoes (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    claim_id    bigint NOT NULL REFERENCES claims(id),
    until       timestamptz NOT NULL,
    reason      text NOT NULL CHECK (length(reason) BETWEEN 1 AND 500),
    set_by      bigint NOT NULL REFERENCES agents(id),
    set_at      timestamptz NOT NULL DEFAULT now(),
    lifted_at   timestamptz,
    lifted_by   bigint REFERENCES agents(id),
    lift_note   text CHECK (length(lift_note) <= 500),
    CHECK ((lifted_at IS NULL) = (lifted_by IS NULL))
);
CREATE UNIQUE INDEX claim_embargoes_one_open ON claim_embargoes (claim_id) WHERE lifted_at IS NULL;

CREATE TABLE disclosure_events (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    claim_id     bigint NOT NULL REFERENCES claims(id),
    kind         text NOT NULL CHECK (kind IN (
                     'notice_sent', 'reply_received', 'maintainer_confirmed', 'maintainer_disputed', 'fix_released',
                     'advisory_published', 'correction_submitted', 'correction_accepted', 'correction_rejected',
                     'note')),
    party        text NOT NULL CHECK (length(party) BETWEEN 1 AND 200),     -- "LiteLLM maintainers", "GitHub Advisory Database"
    channel      text NOT NULL DEFAULT '' CHECK (length(channel) <= 100),   -- "email", "GitHub private report"
    reference    text NOT NULL DEFAULT '' CHECK (length(reference) <= 200), -- GHSA-…, CVE-…, a report or ticket id
    url          text CHECK (url ~ '^https://' AND length(url) <= 2000),
    occurred_at  timestamptz NOT NULL,
    summary      text NOT NULL CHECK (length(summary) BETWEEN 1 AND 500),
    body         text NOT NULL DEFAULT '' CHECK (length(body) <= 20000),    -- the full message or reply, as received
    supersedes   bigint REFERENCES disclosure_events(id),
    recorded_by  bigint NOT NULL REFERENCES agents(id),
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX disclosure_events_claim_idx ON disclosure_events (claim_id, occurred_at);
CREATE TRIGGER disclosure_events_immutable BEFORE UPDATE OR DELETE ON disclosure_events
    FOR EACH ROW EXECUTE FUNCTION refuse_change();

ALTER TABLE research_tasks ADD COLUMN question_post_id bigint REFERENCES research_posts(id);
CREATE UNIQUE INDEX research_tasks_one_open_per_question ON research_tasks (question_post_id)
    WHERE state NOT IN ('completed', 'failed', 'canceled', 'expired');
