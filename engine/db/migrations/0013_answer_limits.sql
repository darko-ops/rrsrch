-- Who asked for each answer, so new answers can be limited per visitor (by IP) or per agent (by key).
ALTER TABLE answer_jobs ADD COLUMN client_key text;
CREATE INDEX answer_jobs_client_idx ON answer_jobs (client_key, created_at);
