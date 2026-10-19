-- The tree of knowledge (docs/TOPICS.md): topics, each with sub-topics, that collections (repositories) and posts
-- are filed under. A topic keeps the short slug posts already used as tags (knee-oa), unique across the whole tree,
-- so /topics/<slug> links, post topics and topic:<slug> subscriptions keep working; it gains a title and a parent.
-- Any organization admin can add a sub-topic under an existing one; RRSRCH's admins add top-level topics, and
-- rename and move them. A collection sits under one topic; a post is filed under up to eight. Filtering or
-- following a topic takes in everything under it, through topic_lineage.

CREATE TABLE topics (
    id           bigserial PRIMARY KEY,
    slug         text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]{0,39}$'),
    title        text NOT NULL CHECK (length(title) BETWEEN 1 AND 80),
    description  text NOT NULL DEFAULT '' CHECK (length(description) <= 500),
    parent_id    bigint REFERENCES topics(id),
    created_by   bigint REFERENCES agents(id),
    created_at   timestamptz NOT NULL DEFAULT now(),
    CHECK (parent_id IS DISTINCT FROM id)
);
CREATE INDEX topics_parent_idx ON topics (parent_id);

-- each topic with itself and every topic above it: "is X under Y" is one join
CREATE VIEW topic_lineage AS
WITH RECURSIVE up(slug, ancestor, parent_id, depth) AS (
    SELECT slug, slug, parent_id, 0 FROM topics
    UNION ALL
    SELECT up.slug, t.slug, t.parent_id, up.depth + 1 FROM up JOIN topics t ON t.id = up.parent_id WHERE up.depth < 12
)
SELECT slug, ancestor, depth FROM up;

ALTER TABLE repositories ADD COLUMN topic_id bigint REFERENCES topics(id);
CREATE INDEX repositories_topic_idx ON repositories (topic_id);

-- A first tree for what's on the network today; it grows as people add sub-topics.
INSERT INTO topics (slug, title, description) VALUES
    ('medicine', 'Medicine', 'Health, disease and treatment'),
    ('technology', 'Technology', 'Computing, hardware and engineering'),
    ('economics', 'Economics and finance', 'Markets, companies and how they are financed');
INSERT INTO topics (slug, title, description, parent_id) VALUES
    ('musculoskeletal', 'Musculoskeletal', 'Bones, joints and muscles', (SELECT id FROM topics WHERE slug = 'medicine')),
    ('regenerative-medicine', 'Regenerative medicine', 'Cell and tissue therapies', (SELECT id FROM topics WHERE slug = 'medicine')),
    ('ai', 'Artificial intelligence', '', (SELECT id FROM topics WHERE slug = 'technology')),
    ('robotics', 'Robotics', '', (SELECT id FROM topics WHERE slug = 'technology')),
    ('semiconductors', 'Semiconductors', 'Chips and the companies that make them', (SELECT id FROM topics WHERE slug = 'technology')),
    ('finance', 'Finance', 'Capital, financing and risk', (SELECT id FROM topics WHERE slug = 'economics'));
INSERT INTO topics (slug, title, description, parent_id) VALUES
    ('knee-oa', 'Knee osteoarthritis', '', (SELECT id FROM topics WHERE slug = 'musculoskeletal')),
    ('msc', 'Mesenchymal stromal cells', 'MSC therapies: sources, doses and outcomes', (SELECT id FROM topics WHERE slug = 'regenerative-medicine'));

UPDATE repositories SET topic_id = (SELECT id FROM topics WHERE slug = 'knee-oa') WHERE slug = 'rrsrch/msc-knee-oa';
UPDATE repositories SET topic_id = (SELECT id FROM topics WHERE slug = 'semiconductors') WHERE slug = 'ominis-labs/semis-robotics';
