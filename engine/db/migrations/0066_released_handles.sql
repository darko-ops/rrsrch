-- A deactivated agent frees its handle (identity/store.revoke_agent): it is renamed deactivated-<id>, and the handle
-- it had is kept here so links to it still find it until another agent takes the name.
ALTER TABLE agents ADD COLUMN IF NOT EXISTS released_handle text;
CREATE INDEX IF NOT EXISTS agents_released_handle ON agents (released_handle) WHERE released_handle IS NOT NULL;

-- agents deactivated before this free theirs too; people keep their handles
DELETE FROM subscriptions s USING agents a
 WHERE s.target = 'agent:' || a.handle AND a.status = 'revoked' AND a.kind <> 'human' AND a.handle NOT LIKE 'deactivated-%';
DELETE FROM handle_history h USING agents a
 WHERE h.agent_id = a.id AND a.status = 'revoked' AND a.kind <> 'human';
UPDATE agents SET released_handle = handle, handle = 'deactivated-' || id
 WHERE status = 'revoked' AND kind <> 'human' AND handle NOT LIKE 'deactivated-%';
