-- Asking for work is a question (docs/SIMPLIFY.md, step 2): research tasks retire.
--
-- A question is the one way to ask for work; a bounty is a question with a contract, and its submissions are the
-- record of who answered it. Research tasks duplicated both (they had no rows in production and were already out of
-- view), so their tables are renamed retired_* until step 3 drops them, and bounty submissions no longer open a task.
ALTER TABLE bounty_submissions DROP COLUMN task_id;
DO $$
DECLARE t text; i record;
BEGIN
    FOREACH t IN ARRAY ARRAY['research_tasks', 'task_responses'] LOOP
        FOR i IN SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = t LOOP
            EXECUTE format('ALTER INDEX %I RENAME TO %I', i.indexname, 'retired_' || i.indexname);
        END LOOP;
    END LOOP;
END $$;
ALTER TABLE research_tasks RENAME TO retired_research_tasks;
ALTER TABLE task_responses RENAME TO retired_task_responses;
