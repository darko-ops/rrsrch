-- The weekly posts on X (collab/xposts.py): one row per post that went out, so each kind posts at most once a week
-- and a featured gauge isn't featured again for a few weeks.

CREATE TABLE IF NOT EXISTS x_posts (
    week      text        NOT NULL,                       -- ISO week, e.g. 2026-W43
    kind      text        NOT NULL CHECK (kind IN ('core', 'featured', 'popular')),
    ref       text        NOT NULL,                       -- the featured gauge, else the kind
    tweet_id  text        NOT NULL,
    text      text        NOT NULL,
    posted_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (week, kind)
);
