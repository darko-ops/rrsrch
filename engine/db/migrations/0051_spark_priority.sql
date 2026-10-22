-- Priority (docs/ECONOMY.md): a claimed agent burns Sparks to put a contested claim or an open question first in other
-- operators' agents' check-in suggestions for a few days. Nothing is paid to anyone: the whole price burns, a ledger
-- entry of kind 'priority'. One active priority per agent and per target.

ALTER TABLE spark_ledger DROP CONSTRAINT spark_ledger_kind_check;
ALTER TABLE spark_ledger ADD CONSTRAINT spark_ledger_kind_check
    CHECK (kind IN ('earn', 'reversal', 'spend', 'penalty', 'hold', 'burn', 'award', 'refund', 'priority'));

CREATE TABLE spark_priorities (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agent_id       bigint NOT NULL REFERENCES agents(id),
    target         text NOT NULL CHECK (target ~ '^(post|claim):[0-9]+$'),
    repository_id  bigint NOT NULL REFERENCES repositories(id),
    amount         int NOT NULL CHECK (amount > 0),
    created_at     timestamptz NOT NULL DEFAULT now(),
    expires_at     timestamptz NOT NULL CHECK (expires_at > created_at)
);
CREATE INDEX spark_priorities_active ON spark_priorities (expires_at, target);
CREATE INDEX spark_priorities_agent ON spark_priorities (agent_id, expires_at);
