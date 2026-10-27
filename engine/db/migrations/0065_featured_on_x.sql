-- RRSRCH's admins feature gauges and findings for the weekly posts on X (collab/xposts.py): a featured gauge's result
-- posts every week until it's unfeatured, a featured finding posts once. With nothing featured, the engine picks.

ALTER TABLE gauges ADD COLUMN IF NOT EXISTS featured boolean NOT NULL DEFAULT false;
ALTER TABLE research_posts ADD COLUMN IF NOT EXISTS featured_at timestamptz;
CREATE INDEX IF NOT EXISTS research_posts_featured_idx ON research_posts (featured_at) WHERE featured_at IS NOT NULL;

-- several featured gauges and findings a week, each once: a row per post, not per kind
ALTER TABLE x_posts DROP CONSTRAINT IF EXISTS x_posts_pkey;
ALTER TABLE x_posts ADD PRIMARY KEY (week, kind, ref);
ALTER TABLE x_posts DROP CONSTRAINT IF EXISTS x_posts_kind_check;
ALTER TABLE x_posts ADD CONSTRAINT x_posts_kind_check CHECK (kind IN ('core', 'featured', 'popular', 'finding'));
