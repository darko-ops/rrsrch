-- The handle and organization an agent had at its last check-in, so the next one can tell it when either changed
-- (collab/checkin.py): an agent that remembers an old identity is told to drop it.
ALTER TABLE agents ADD COLUMN checkin_handle text, ADD COLUMN checkin_org text;
