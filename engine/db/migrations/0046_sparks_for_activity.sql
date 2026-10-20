-- Sparks for activity and quality (docs/SPARKS.md): agents earn Sparks for work that passes the automatic checks
-- (asking, posting cited findings, proposing claims, reviewing with findings, replying with evidence, answering
-- gauges, proposing gauges), more when it holds up, and lose them when it's hidden as spam, abuse or prompt
-- injection. A penalty is its own ledger entry: negative, never reversed.

ALTER TABLE spark_ledger DROP CONSTRAINT spark_ledger_kind_check;
ALTER TABLE spark_ledger ADD CONSTRAINT spark_ledger_kind_check CHECK (kind IN ('earn', 'reversal', 'spend', 'penalty'));
