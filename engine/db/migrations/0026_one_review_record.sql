-- One review record (docs/SIMPLIFY.md, step 2): every way of judging someone else's work is a row in `reviews`.
--
--   kind          verdicts                                                        on
--   decision      approve | request_changes | reject                              proposal:N, claim:N
--   objection     object (details.objection: contradiction | missing_assumption    claim:N, submission:N
--                 | evidence_problem | scope | other), with state open | upheld
--                 | dismissed | withdrawn and a resolution
--   reproduction  reproduced | failed | inconclusive | insufficient_evidence       claim:N, post:N
--   usage         worked | worked_with_conditions | failed | outdated              claim:N, post:N
--                 | missing_step | unclear
--   judgment      accepted | partially_accepted | rejected | needs_info            submission:N (bounties)
--
-- These were five tables: reviews (of proposals), claim_reviews, challenges, verification_reports and
-- bounty_judgments, plus bounty_challenges. They are renamed retired_* and their rows copied here; views with the
-- old names keep every existing read working while the code moves over (step 3 drops the views and the retired
-- tables). Ids are new: a copied row records where it came from in details.legacy, and the two things that pointed
-- at old ids (bounty appeals, and comment threads on a challenge) are repointed.
--
-- Decisions can be revised (one per reviewer per proposal, or per claim revision); objections change state when
-- resolved; reproduction, usage and judgment rows never change.
DO $$
DECLARE t text; i record;
BEGIN
    FOREACH t IN ARRAY ARRAY['reviews', 'claim_reviews', 'challenges', 'verification_reports', 'bounty_judgments',
                             'bounty_challenges'] LOOP
        FOR i IN SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = t LOOP
            EXECUTE format('ALTER INDEX %I RENAME TO %I', i.indexname, 'retired_' || i.indexname);
        END LOOP;
    END LOOP;
END $$;
ALTER TABLE reviews RENAME TO retired_proposal_reviews;
ALTER TABLE claim_reviews RENAME TO retired_claim_reviews;
ALTER TABLE challenges RENAME TO retired_challenges;
ALTER TABLE verification_reports RENAME TO retired_verification_reports;
ALTER TABLE bounty_judgments RENAME TO retired_bounty_judgments;
ALTER TABLE bounty_challenges RENAME TO retired_bounty_challenges;

CREATE TABLE reviews (
    id                      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    target                  text NOT NULL CHECK (target ~ '^(proposal|claim|post|submission):[0-9]+$'),
    repository_id           bigint NOT NULL REFERENCES repositories(id),
    reviewer_id             bigint NOT NULL REFERENCES agents(id),
    kind                    text NOT NULL CHECK (kind IN ('decision', 'objection', 'reproduction', 'usage', 'judgment')),
    verdict                 text NOT NULL,
    findings                text NOT NULL DEFAULT '' CHECK (length(findings) <= 8000),
    details                 jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(details) = 'object'),
    revision_id             bigint REFERENCES claim_revisions(id),               -- the claim revision reviewed
    submission_revision_id  bigint REFERENCES bounty_submission_revisions(id),   -- the submission revision judged
    blocking                boolean NOT NULL DEFAULT false,                      -- objections: holds the claim
    state                   text NOT NULL DEFAULT 'final' CHECK (state IN ('final', 'open', 'upheld', 'dismissed',
                                                                            'withdrawn')),
    resolution              text CHECK (length(resolution) <= 4000),
    resolved_by             bigint REFERENCES agents(id),
    resolved_at             timestamptz,
    content_hash            text,
    created_at              timestamptz NOT NULL DEFAULT now(),
    -- what the target names, for joins
    merge_request_id  bigint GENERATED ALWAYS AS (CASE WHEN target LIKE 'proposal:%'
                          THEN split_part(target, ':', 2)::bigint END) STORED,
    claim_id          bigint GENERATED ALWAYS AS (CASE WHEN target LIKE 'claim:%'
                          THEN split_part(target, ':', 2)::bigint END) STORED,
    submission_id     bigint GENERATED ALWAYS AS (CASE WHEN target LIKE 'submission:%'
                          THEN split_part(target, ':', 2)::bigint END) STORED,
    CHECK (
        (kind = 'decision' AND verdict IN ('approve', 'request_changes', 'reject')
            AND target ~ '^(proposal|claim):' AND (verdict <> 'request_changes' OR target LIKE 'proposal:%'))
     OR (kind = 'objection' AND verdict = 'object' AND target ~ '^(claim|submission):'
            AND state IN ('open', 'upheld', 'dismissed', 'withdrawn') AND length(findings) >= 1)
     OR (kind = 'reproduction' AND verdict IN ('reproduced', 'failed', 'inconclusive', 'insufficient_evidence')
            AND target ~ '^(claim|post):' AND length(findings) >= 1)
     OR (kind = 'usage' AND verdict IN ('worked', 'worked_with_conditions', 'failed', 'outdated', 'missing_step',
                                        'unclear') AND target ~ '^(claim|post):' AND length(findings) >= 1)
     OR (kind = 'judgment' AND verdict IN ('accepted', 'partially_accepted', 'rejected', 'needs_info')
            AND target LIKE 'submission:%' AND length(findings) >= 1)),
    CHECK (kind = 'objection' OR (state = 'final' AND NOT blocking)),
    CHECK ((state IN ('final', 'open')) = (resolved_at IS NULL))
);
CREATE UNIQUE INDEX reviews_one_decision_per_proposal ON reviews (merge_request_id, reviewer_id)
    WHERE kind = 'decision' AND merge_request_id IS NOT NULL;
CREATE UNIQUE INDEX reviews_one_decision_per_revision ON reviews (revision_id, reviewer_id)
    WHERE kind = 'decision' AND claim_id IS NOT NULL;
CREATE INDEX reviews_target_idx ON reviews (target, kind, id);
CREATE INDEX reviews_reviewer_idx ON reviews (reviewer_id, created_at);
CREATE INDEX reviews_claim_idx ON reviews (claim_id, kind, state) WHERE claim_id IS NOT NULL;
CREATE INDEX reviews_mr_idx ON reviews (merge_request_id) WHERE merge_request_id IS NOT NULL;
CREATE INDEX reviews_submission_idx ON reviews (submission_id, kind) WHERE submission_id IS NOT NULL;

CREATE FUNCTION reviews_keep_records() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' OR OLD.kind IN ('reproduction', 'usage', 'judgment') THEN
        RAISE EXCEPTION 'reviews of kind % are immutable (review %)', OLD.kind, OLD.id;
    END IF;
    IF NEW.kind <> OLD.kind OR NEW.target <> OLD.target OR NEW.reviewer_id <> OLD.reviewer_id THEN
        RAISE EXCEPTION 'a review keeps its kind, target and reviewer (review %)', OLD.id;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER reviews_keep_records BEFORE UPDATE OR DELETE ON reviews
    FOR EACH ROW EXECUTE FUNCTION reviews_keep_records();

-- copy what there was
INSERT INTO reviews (target, repository_id, reviewer_id, kind, verdict, findings, details, created_at)
SELECT 'proposal:' || r.merge_request_id, m.repository_id, r.reviewer_id, 'decision', r.verdict, r.findings,
       jsonb_build_object('legacy', 'proposal_review:' || r.id), r.created_at
FROM retired_proposal_reviews r JOIN merge_requests m ON m.id = r.merge_request_id ORDER BY r.id;

INSERT INTO reviews (target, repository_id, reviewer_id, kind, verdict, findings, details, revision_id, created_at)
SELECT 'claim:' || r.claim_id, c.repository_id, r.reviewer_id, 'decision', r.verdict, r.findings,
       jsonb_build_object('legacy', 'claim_review:' || r.id), r.revision_id, r.created_at
FROM retired_claim_reviews r JOIN claims c ON c.id = r.claim_id ORDER BY r.id;

INSERT INTO reviews (target, repository_id, reviewer_id, kind, verdict, findings, details, revision_id, blocking,
                     state, resolution, resolved_by, resolved_at, created_at)
SELECT 'claim:' || h.claim_id, c.repository_id, h.author_id, 'objection', 'object', h.statement,
       jsonb_build_object('legacy', 'challenge:' || h.id, 'objection', h.kind, 'evidence', h.evidence), h.revision_id,
       h.blocking, h.state, h.resolution, h.resolved_by, h.resolved_at, h.created_at
FROM retired_challenges h JOIN claims c ON c.id = h.claim_id ORDER BY h.id;

INSERT INTO reviews (target, repository_id, reviewer_id, kind, verdict, findings, details, revision_id,
                     content_hash, created_at)
SELECT v.target, v.repository_id, v.author_id, v.context, v.outcome, v.observations,
       jsonb_build_object('legacy', 'verification:' || v.id, 'method', v.method, 'environment', v.environment,
                          'conditions', v.conditions, 'limitations', v.limitations, 'versions', v.versions,
                          'artifacts', v.artifacts), v.claim_revision_id, v.content_hash, v.created_at
FROM retired_verification_reports v ORDER BY v.id;

INSERT INTO reviews (target, repository_id, reviewer_id, kind, verdict, findings, details, submission_revision_id,
                     created_at)
SELECT 'submission:' || j.submission_id, b.repository_id, j.judge_id, 'judgment', j.decision, j.reasons,
       jsonb_build_object('legacy', 'judgment:' || j.id, 'on_appeal', j.on_appeal), j.revision_id, j.created_at
FROM retired_bounty_judgments j JOIN bounty_submissions s ON s.id = j.submission_id
JOIN bounties b ON b.id = s.bounty_id ORDER BY j.id;

INSERT INTO reviews (target, repository_id, reviewer_id, kind, verdict, findings, details, state, resolution,
                     resolved_by, resolved_at, created_at)
SELECT 'submission:' || h.submission_id, b.repository_id, h.author_id, 'objection', 'object', h.statement,
       jsonb_build_object('legacy', 'bounty_challenge:' || h.id, 'objection', 'other', 'evidence', h.evidence,
                          'judgment_id', (SELECT r.id FROM reviews r WHERE r.details->>'legacy' = 'judgment:' || h.judgment_id)),
       h.state, h.resolution, h.resolved_by, h.resolved_at, h.created_at
FROM retired_bounty_challenges h JOIN bounty_submissions s ON s.id = h.submission_id
JOIN bounties b ON b.id = s.bounty_id ORDER BY h.id;

-- repoint what pointed at the old ids
ALTER TABLE bounty_appeals DROP CONSTRAINT bounty_appeals_judgment_id_fkey;
UPDATE bounty_appeals a SET judgment_id = r.id FROM reviews r WHERE r.details->>'legacy' = 'judgment:' || a.judgment_id;
ALTER TABLE bounty_appeals ADD CONSTRAINT bounty_appeals_judgment_id_fkey FOREIGN KEY (judgment_id) REFERENCES reviews(id);
UPDATE discussions d SET subject = 'challenge:' || r.id FROM reviews r
WHERE d.subject LIKE 'challenge:%' AND r.details->>'legacy' = d.subject;

-- the old names, as views, for reads that haven't moved yet
CREATE VIEW claim_reviews AS
    SELECT id, claim_id, revision_id, reviewer_id, verdict, findings, created_at
    FROM reviews WHERE kind = 'decision' AND claim_id IS NOT NULL;
CREATE VIEW challenges AS
    SELECT id, claim_id, reviewer_id AS author_id, details->>'objection' AS kind, findings AS statement,
           coalesce(details->'evidence', '[]') AS evidence, blocking, state, resolution, resolved_by, created_at,
           resolved_at, revision_id
    FROM reviews WHERE kind = 'objection' AND claim_id IS NOT NULL;
CREATE VIEW verification_reports AS
    SELECT id, target, repository_id, revision_id AS claim_revision_id, reviewer_id AS author_id, kind AS context,
           verdict AS outcome, coalesce(details->>'method', '') AS method,
           coalesce(details->>'environment', '') AS environment, findings AS observations,
           coalesce(details->>'conditions', '') AS conditions, coalesce(details->>'limitations', '') AS limitations,
           coalesce(details->'versions', '{}') AS versions, coalesce(details->'artifacts', '[]') AS artifacts,
           content_hash, created_at
    FROM reviews WHERE kind IN ('reproduction', 'usage');
CREATE VIEW bounty_judgments AS
    SELECT id, submission_id, submission_revision_id AS revision_id, reviewer_id AS judge_id, verdict AS decision,
           findings AS reasons, coalesce((details->>'on_appeal')::boolean, false) AS on_appeal, created_at
    FROM reviews WHERE kind = 'judgment';
CREATE VIEW bounty_challenges AS
    SELECT id, submission_id, (details->>'judgment_id')::bigint AS judgment_id, reviewer_id AS author_id,
           findings AS statement, coalesce(details->'evidence', '[]') AS evidence, state, resolved_by, resolution,
           created_at, resolved_at
    FROM reviews WHERE kind = 'objection' AND submission_id IS NOT NULL;
