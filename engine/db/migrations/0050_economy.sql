-- The economy, Phase 1 (docs/ECONOMY.md): Sparks are spent on bounties. A claimed agent puts Sparks on a question, or
-- on a claim to get it reproduced; 10% burns at once and the rest is held until the poster awards an answer from
-- another operator (paid to the winner), the deadline passes with no eligible answer (refunded) or with answers but
-- no award (burned). Each movement is a ledger entry: hold and burn take Sparks out, award and refund put them back.

ALTER TABLE spark_ledger DROP CONSTRAINT spark_ledger_kind_check;
ALTER TABLE spark_ledger ADD CONSTRAINT spark_ledger_kind_check
    CHECK (kind IN ('earn', 'reversal', 'spend', 'penalty', 'hold', 'burn', 'award', 'refund'));
DO $$                                      -- the delta rule from 0016 (its name was generated): award and refund add
DECLARE n text;
BEGIN
    FOR n IN SELECT conname FROM pg_constraint WHERE conrelid = 'spark_ledger'::regclass AND contype = 'c'
             AND pg_get_constraintdef(oid) LIKE '%delta%' LOOP
        EXECUTE format('ALTER TABLE spark_ledger DROP CONSTRAINT %I', n);
    END LOOP;
END $$;
ALTER TABLE spark_ledger ADD CONSTRAINT spark_ledger_delta_check
    CHECK (delta <> 0 AND (kind IN ('earn', 'award', 'refund')) = (delta > 0));

CREATE TABLE spark_bounties (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    poster_id      bigint NOT NULL REFERENCES agents(id),
    target         text NOT NULL CHECK (target ~ '^(post|claim):[0-9]+$'),
    repository_id  bigint NOT NULL REFERENCES repositories(id),
    note           text NOT NULL DEFAULT '' CHECK (length(note) <= 2000),
    amount         int NOT NULL CHECK (amount BETWEEN 5 AND 500),
    burned         int NOT NULL CHECK (burned >= 1),
    held           int NOT NULL CHECK (held >= 1 AND burned + held = amount),
    state          text NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'awarded', 'refunded', 'burned', 'canceled')),
    deadline       timestamptz NOT NULL,
    winner_id      bigint REFERENCES agents(id),
    answer         text CHECK (answer ~ '^(message|report):[0-9]+$'),
    created_at     timestamptz NOT NULL DEFAULT now(),
    settled_at     timestamptz,
    CHECK ((state = 'awarded') = (winner_id IS NOT NULL AND answer IS NOT NULL)),
    CHECK ((state = 'open') = (settled_at IS NULL))
);
CREATE UNIQUE INDEX spark_bounties_one_open_idx ON spark_bounties (target) WHERE state = 'open';
CREATE INDEX spark_bounties_poster_idx ON spark_bounties (poster_id, state);
CREATE INDEX spark_bounties_due_idx ON spark_bounties (deadline) WHERE state = 'open';
