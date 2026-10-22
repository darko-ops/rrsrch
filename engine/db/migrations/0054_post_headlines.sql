-- Headlines (docs/AGENTS.md): a post can carry a short headline above its title, which then reads as a subheader.
-- Optional; posts without one show their title as the headline. Like the rest of a post, it can't be changed later.
ALTER TABLE research_posts ADD COLUMN headline text CHECK (char_length(headline) BETWEEN 1 AND 80);
ALTER TABLE post_drafts ADD COLUMN headline text NOT NULL DEFAULT '';
