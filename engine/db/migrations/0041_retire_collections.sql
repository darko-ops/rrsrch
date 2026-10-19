-- Retiring a collection (repository): the owner asks for it to be deleted, but the audit log is a hash chain whose
-- entries name their repository, so the row can't go without breaking the chain for everything after it. A retired
-- collection is gone from every list, read and action (query.visible, identity.store.get_repo); its history stays
-- on the record, and its slug stays taken. docs/TOPICS.md, "Retiring a collection".

-- On a fresh database the migrations share one transaction, and 0040's updates leave this deferred check pending,
-- which ALTER TABLE refuses: settle it now, then put it back as it was (DEFERRABLE INITIALLY DEFERRED, 0008).
SET CONSTRAINTS repositories_policy_fk IMMEDIATE;

ALTER TABLE repositories
    ADD COLUMN deleted_at  timestamptz,
    ADD COLUMN deleted_by  bigint REFERENCES agents(id);

SET CONSTRAINTS repositories_policy_fk DEFERRED;
