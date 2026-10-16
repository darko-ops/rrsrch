-- Keys that stay alive while they're used (docs/AGENTS.md, "Keys"). A key with idle_days set expires that many days
-- after it was last used: each use pushes expires_at forward, never past max_expires_at when that is set. A key used
-- regularly never needs renewing; one nobody uses dies on its own; revoking still cuts it off at once. Keys with
-- idle_days null keep the fixed lifetime they were issued with.
--
--   claimed agents' keys    idle 90 days, no fixed end
--   unclaimed agents' keys  idle 30 days, never past 30 days after signing up (claiming lifts that)

ALTER TABLE api_keys
    ADD COLUMN idle_days       int CHECK (idle_days BETWEEN 1 AND 365),
    ADD COLUMN max_expires_at  timestamptz;

-- the 90-day cap on a key's lifetime gives way to the idle window
DO $$
DECLARE c text;
BEGIN
    FOR c IN SELECT conname FROM pg_constraint WHERE conrelid = 'api_keys'::regclass AND contype = 'c'
             AND pg_get_constraintdef(oid) LIKE '%90 days%' LOOP
        EXECUTE format('ALTER TABLE api_keys DROP CONSTRAINT %I', c);
    END LOOP;
END $$;
ALTER TABLE api_keys ADD CONSTRAINT api_keys_expiry CHECK (expires_at > created_at),
                     ADD CONSTRAINT api_keys_capped CHECK (max_expires_at IS NULL OR expires_at <= max_expires_at);

-- live keys switch to the idle window now, so nothing in use lapses on its old date
UPDATE api_keys k SET idle_days = 90
FROM agents a WHERE a.id = k.agent_id AND k.revoked_at IS NULL AND k.expires_at > now()
  AND a.organization_id <> 'unclaimed';
UPDATE api_keys k SET idle_days = 30, max_expires_at = greatest(k.expires_at, a.created_at + interval '30 days')
FROM agents a WHERE a.id = k.agent_id AND k.revoked_at IS NULL AND k.expires_at > now()
  AND a.organization_id = 'unclaimed';
