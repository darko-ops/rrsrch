-- A "needs work" reaction: the negative half of the quick ▲/▼ feedback on posts. Like every reaction it is
-- informal: it never changes ordering, review state or anyone's standing.
ALTER TABLE reactions DROP CONSTRAINT reactions_kind_check;
ALTER TABLE reactions ADD CONSTRAINT reactions_kind_check
    CHECK (kind IN ('useful', 'interesting', 'needs_clarification', 'needs_work'));
