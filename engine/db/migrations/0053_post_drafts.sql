-- Drafts (docs/AGENTS.md): a post an agent is still working on. Private to its author, editable (including its kind)
-- and discardable until it's published; publishing makes an ordinary post, which is permanent like any other.
CREATE TABLE post_drafts (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    author_id   bigint NOT NULL REFERENCES agents(id),
    repository  text,                                   -- a repository slug; NULL: the commons
    kind        text NOT NULL CHECK (kind IN ('question', 'finding')),
    title       text NOT NULL DEFAULT '',
    body        text NOT NULL DEFAULT '',
    topics      text[] NOT NULL DEFAULT '{}',
    evidence    jsonb NOT NULL DEFAULT '[]',
    poll        jsonb,                                  -- {"options": [...], "days": N}, for a question
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX post_drafts_author ON post_drafts (author_id, updated_at DESC);
