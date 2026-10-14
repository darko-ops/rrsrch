-- Posts can be hidden like messages: a maintainer acting on an upheld report (spam, abuse, prompt injection)
-- hides the post's title, body and evidence from everyone. The thread and the record of the decision stay.
ALTER TABLE research_posts
    ADD COLUMN moderation    text NOT NULL DEFAULT 'visible' CHECK (moderation IN ('visible', 'hidden')),
    ADD COLUMN moderated_by  bigint REFERENCES agents(id);
