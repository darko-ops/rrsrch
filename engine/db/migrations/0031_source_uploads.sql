-- Uploads (docs/SOURCES.md, step 2): a document an agent sent itself, for sources with no public address. Its
-- provenance is 'uploaded' (agent-supplied: reviewers can't fetch it themselves), and the agent says where it came
-- from, which is shown with every passage cited from it.
ALTER TABLE sources ADD COLUMN origin text CHECK (origin IS NULL OR length(origin) BETWEEN 1 AND 1000);
