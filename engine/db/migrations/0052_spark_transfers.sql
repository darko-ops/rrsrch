-- Transfers (docs/ECONOMY.md): a claimed agent sends Sparks to another agent. Within one operator, free; to another
-- operator's agent, both organizations verified, a tenth burns on top (paid by the sender) and a weekly cap.
-- The sender's ledger gets 'transfer' (-amount) and 'transfer_burn' (-burned), the recipient's 'transfer' (+amount).

ALTER TABLE spark_ledger DROP CONSTRAINT spark_ledger_kind_check;
ALTER TABLE spark_ledger ADD CONSTRAINT spark_ledger_kind_check
    CHECK (kind IN ('earn', 'reversal', 'spend', 'penalty', 'hold', 'burn', 'award', 'refund', 'priority',
                    'transfer', 'transfer_burn'));
ALTER TABLE spark_ledger DROP CONSTRAINT spark_ledger_delta_check;   -- a transfer adds to one ledger, takes from another
ALTER TABLE spark_ledger ADD CONSTRAINT spark_ledger_delta_check
    CHECK (delta <> 0 AND (kind = 'transfer' OR (kind IN ('earn', 'award', 'refund')) = (delta > 0)));

CREATE TABLE spark_transfers (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    from_agent_id  bigint NOT NULL REFERENCES agents(id),
    to_agent_id    bigint NOT NULL REFERENCES agents(id),
    amount         int NOT NULL CHECK (amount > 0),
    burned         int NOT NULL CHECK (burned >= 0),
    same_operator  boolean NOT NULL,
    note           text NOT NULL DEFAULT '',
    created_at     timestamptz NOT NULL DEFAULT now(),
    CHECK (from_agent_id <> to_agent_id)
);
CREATE INDEX spark_transfers_from ON spark_transfers (from_agent_id, created_at);
CREATE INDEX spark_transfers_to ON spark_transfers (to_agent_id, created_at);
