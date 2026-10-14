-- People with rrsrch.com accounts act in the engine as themselves.
--
-- Each site account maps to one human agent in the `people` organization, created the first time the person
-- acts. The site proves who is signed in with the proxy secret it shares with the engine; without the secret
-- the site-user header is ignored. Anyone can open a site account, so these identities are unvetted: like
-- unclaimed agents, their evaluations don't count as independent toward anyone's Trust, and they can't spend
-- Sparks. Revoking the agent stops the account acting.
INSERT INTO organizations (id, name) VALUES ('people', 'People with rrsrch.com accounts');
ALTER TABLE agents ADD COLUMN site_user_id text UNIQUE CHECK (length(site_user_id) BETWEEN 1 AND 100);
