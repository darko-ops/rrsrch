-- Reviewing claims that are already in a repository (docs/SPEC-v2.md §7.3, §10.4).
--
-- Merge requests carry review for proposed changes. Claims the reader extracted entered the ledger directly
-- as structurally_valid, so they had no way to become supported. A claim review is one reviewer's verdict on
-- one revision of a claim; the repository's policy (independent approvals, a human approval) decides from
-- these rows whether the claim is supported, exactly as it decides merges.

CREATE TABLE claim_reviews (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    claim_id     bigint NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    revision_id  bigint NOT NULL REFERENCES claim_revisions(id) ON DELETE CASCADE,   -- what was reviewed
    reviewer_id  bigint NOT NULL REFERENCES agents(id),
    verdict      text NOT NULL CHECK (verdict IN ('approve', 'reject')),
    findings     text NOT NULL DEFAULT '',
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (revision_id, reviewer_id)
);
CREATE INDEX claim_reviews_claim_idx ON claim_reviews (claim_id);
