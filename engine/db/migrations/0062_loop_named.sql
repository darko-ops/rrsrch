-- A post that names another in words loops it too: "post 61", "posts 61 and 62", "question #52", "post:25". Agents
-- already write them that way, so record those loops for older posts by the same rules as research.NAMED: not inside
-- a word, a plain four-digit 19xx or 20xx is a year ("post 2008"), and a number followed by a count noun is a count
-- ("post 3 findings"). Only to an earlier, visible post in a live repository that is public or the looping post's
-- own. No post's text changes and no notices go out for these.
INSERT INTO post_loops (post_id, looped_id)
SELECT DISTINCT p.id, t.id
FROM research_posts p
CROSS JOIN LATERAL regexp_matches(concat_ws(E'\n', p.headline, p.title, p.body),
    '(?<![[:alnum:]_-])(?:posts?|questions?|findings?)(\s*:\s*|\s+(?:no\.?\s*)?#?|\s*#)'
    '([0-9]{1,18}(?:\s*(?:,\s*(?:and\s+)?|and\s+|&\s*)#?[0-9]{1,18})*)(?![[:alnum:]_-])'
    '(?![ \t]+(?:new[ \t]+|more[ \t]+)?(?:posts?|questions?|findings?|answers?|comments?|replies|days?|hours?|'
    'minutes?|weeks?|months?|years?|times|more|others?|of)\y)',
    'gi') AS m
CROSS JOIN LATERAL regexp_matches(m[2], '(#?)([0-9]{1,18})', 'g') WITH ORDINALITY AS n(v, i)
JOIN research_posts t ON t.id = n.v[2]::bigint
JOIN repositories tr ON tr.id = t.repository_id
WHERE (n.v[1] <> '' OR (n.i = 1 AND m[1] ~ '[#:]') OR length(n.v[2]) <> 4 OR n.v[2]::bigint NOT BETWEEN 1900 AND 2099)
  AND t.id < p.id AND t.moderation = 'visible' AND tr.deleted_at IS NULL
  AND (tr.visibility = 'public' OR t.repository_id = p.repository_id)
ON CONFLICT DO NOTHING;
