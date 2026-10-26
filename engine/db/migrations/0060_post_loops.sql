-- Loops (serve/onboarding.md, section 4): a post connects to earlier posts by writing @#N in its title or body. Like citations, loops
-- are fixed when the post is published (the text they come from can't change, and the content hash covers it), and
-- the post page lists them both ways: the posts it loops and the posts that loop it.
CREATE TABLE post_loops (
    post_id     bigint NOT NULL REFERENCES research_posts(id),     -- the post that writes @#N
    looped_id   bigint NOT NULL REFERENCES research_posts(id),     -- post N
    PRIMARY KEY (post_id, looped_id),
    CHECK (post_id <> looped_id)
);
CREATE INDEX post_loops_looped_idx ON post_loops (looped_id, post_id DESC);
