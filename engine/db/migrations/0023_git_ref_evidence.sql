-- Evidence of a second kind: a commit in a public repository, pinned by its full SHA (docs/security/PLAN.md §4).
--
-- A git ref says what the code says (a fix commit, the lines a flaw lives in), where a document span says what a
-- document says. It has no source document, so the span columns are empty for it; it never stands alone (a claim's
-- supporting sources are its document passages: trust/pipeline.py). Repositories accept git refs only when their
-- policy lists them in allowed_evidence, so nothing changes for the clinical repositories.
--
--   repo_url    https://github.com/OWNER/REPO (or gitlab.com, codeberg.org)
--   commit_sha  40 hex characters
--   git_tag     the release tag the commit should be in, when the claim is about that
--   path, start_line, end_line   lines of one file at that commit
--
-- excerpt holds a readable label ("github.com/o/r@abc123def456:path#L1-L9") so every evidence row can be shown.
ALTER TABLE evidence DROP CONSTRAINT evidence_kind_check;
ALTER TABLE evidence ADD CONSTRAINT evidence_kind_check CHECK (kind IN ('document_span', 'git_ref'));
ALTER TABLE evidence
    ALTER COLUMN source_id DROP NOT NULL,
    ALTER COLUMN document_id DROP NOT NULL,
    ALTER COLUMN doc_sha256 DROP NOT NULL,
    ALTER COLUMN span_start DROP NOT NULL,
    ALTER COLUMN span_end DROP NOT NULL,
    ADD COLUMN repo_url text,
    ADD COLUMN commit_sha text CHECK (commit_sha ~ '^[0-9a-f]{40}$'),
    ADD COLUMN git_tag text,
    ADD COLUMN path text,
    ADD COLUMN start_line int CHECK (start_line >= 1),
    ADD COLUMN end_line int CHECK (end_line >= start_line);
ALTER TABLE evidence ADD CONSTRAINT evidence_kind_columns CHECK (
    (kind = 'document_span' AND source_id IS NOT NULL AND document_id IS NOT NULL AND doc_sha256 IS NOT NULL
        AND span_start IS NOT NULL AND span_end IS NOT NULL AND repo_url IS NULL AND commit_sha IS NULL
        AND git_tag IS NULL AND path IS NULL AND start_line IS NULL AND end_line IS NULL)
    OR (kind = 'git_ref' AND repo_url IS NOT NULL AND commit_sha IS NOT NULL AND source_id IS NULL
        AND document_id IS NULL AND doc_sha256 IS NULL AND span_start IS NULL AND span_end IS NULL
        AND (start_line IS NULL) = (end_line IS NULL) AND (start_line IS NULL OR path IS NOT NULL)));
-- one row per distinct ref, as spans are one row per distinct span
CREATE UNIQUE INDEX evidence_git_ref_idx ON evidence
    (repo_url, commit_sha, coalesce(git_tag, ''), coalesce(path, ''), coalesce(start_line, 0), coalesce(end_line, 0))
    WHERE kind = 'git_ref';
