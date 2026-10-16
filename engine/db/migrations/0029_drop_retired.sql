-- Simplification step 3 (docs/SIMPLIFY.md): what step 2 retired goes.
--
-- Every read now uses `reviews` directly, so the views that kept the old names alive are dropped, and with them the
-- retired tables. Their rows were copied into `reviews` by 0026 (research tasks and reactions had none).
DROP VIEW claim_reviews;
DROP VIEW challenges;
DROP VIEW verification_reports;
DROP VIEW bounty_judgments;
DROP VIEW bounty_challenges;

DROP TABLE retired_bounty_challenges;
DROP TABLE retired_bounty_judgments;
DROP TABLE retired_proposal_reviews;
DROP TABLE retired_claim_reviews;
DROP TABLE retired_challenges;
DROP TABLE retired_verification_reports;
DROP TABLE retired_task_responses;
DROP TABLE retired_research_tasks;
DROP TABLE retired_reactions;
