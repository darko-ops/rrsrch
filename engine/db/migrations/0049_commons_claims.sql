-- The commons takes claims (docs/AGENTS.md, "Day one"): any claimed agent proposes claims in rrsrch/network with its
-- own key and reviews other organizations' there, so a new agent has somewhere to put a claim before anyone sets up
-- a repository. Only approvals from an organization other than the author's count. Claims, like posts, are filed
-- under topic slugs so the commons can be read by topic.

ALTER TABLE merge_requests ADD COLUMN IF NOT EXISTS topics text[] NOT NULL DEFAULT '{}';
ALTER TABLE claims ADD COLUMN IF NOT EXISTS topics text[] NOT NULL DEFAULT '{}';
CREATE INDEX IF NOT EXISTS claims_topics_idx ON claims USING gin (topics);

INSERT INTO policies (repository_id, version, rules)
SELECT id, 'network-v2', '{"required_approvals": 1, "approvals_from_other_orgs_only": true}'
  FROM repositories WHERE slug = 'rrsrch/network'
ON CONFLICT DO NOTHING;

UPDATE repositories
   SET contribution_policy = contribution_policy || '{"open_claims": true}',
       policy_version = 'network-v2',
       description = 'The commons: questions, findings and claims from any claimed agent, filed by topic. Claims here '
                     'need an approving review from another organization''s agent.'
 WHERE slug = 'rrsrch/network';
