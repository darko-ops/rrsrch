-- Sharing a result, and talking (docs/SIMPLIFY.md, step 2).
--
-- A post is a question or a finding. Observations and proposals were findings by another name; the ones there are
-- become findings. Reactions retire: discussion is one comment thread on a question, claim or proposal, and nothing
-- is ranked or weighed by reactions anyway. They had no rows in production and were already out of view; the table
-- is renamed retired_reactions until step 3 drops it.
UPDATE research_posts SET kind = 'finding' WHERE kind IN ('observation', 'proposal');
ALTER TABLE research_posts DROP CONSTRAINT research_posts_kind_check;
ALTER TABLE research_posts ADD CONSTRAINT research_posts_kind_check CHECK (kind IN ('question', 'finding'));

DO $$
DECLARE i record;
BEGIN
    FOR i IN SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = 'reactions' LOOP
        EXECUTE format('ALTER INDEX %I RENAME TO %I', i.indexname, 'retired_' || i.indexname);
    END LOOP;
END $$;
ALTER TABLE reactions RENAME TO retired_reactions;
