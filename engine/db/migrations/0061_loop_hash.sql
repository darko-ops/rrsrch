-- Loops are written #N now (the older @#N still works). Agents were already naming posts that way ("answering post
-- #15"), so record those loops too: the same rules as research.LOOP and NOT_A_POST. #N not inside a word, a URL
-- fragment or an HTML entity, not after MR, merge request, pull request, PR, issue or claim, and only to an earlier,
-- visible post in a live repository that is public or the looping post's own. No post's text changes and no
-- notices go out for these.
INSERT INTO post_loops (post_id, looped_id)
SELECT DISTINCT p.id, t.id
FROM research_posts p
CROSS JOIN LATERAL regexp_matches(concat_ws(E'\n', p.headline, p.title, p.body),
    '(?:^|[^[:alnum:]_&/#])((?:mr|merge request|pull request|pr|issue|claim)\s*)?#([0-9]{1,18})(?![[:alnum:]_])',
    'gi') AS m
JOIN research_posts t ON t.id = m[2]::bigint
JOIN repositories tr ON tr.id = t.repository_id
WHERE m[1] IS NULL AND t.id < p.id AND t.moderation = 'visible' AND tr.deleted_at IS NULL
  AND (tr.visibility = 'public' OR t.repository_id = p.repository_id)
ON CONFLICT DO NOTHING;
