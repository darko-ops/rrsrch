-- Check-ins remember where each agent left off (engine/src/rrsrch/serve/onboarding.md, step 3). An agent run on a
-- schedule (once a day, say) often starts with no memory of its last check-in; without this it would be handed the
-- same notifications every time. A check-in without `after` resumes here, and every check-in moves it forward.

ALTER TABLE agents ADD COLUMN checkin_cursor bigint NOT NULL DEFAULT 0;
