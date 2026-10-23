-- Grokbot agents that don't say which Grok model they run are listed as "grokbot" (owner's decision, 2026-10-23),
-- not plain "grok" as 0057 relabelled them.
UPDATE benchmark_snapshots s SET model = 'grokbot'
FROM agents a
WHERE a.id = s.agent_id AND lower(a.model) LIKE 'grokbot/%' AND s.model = 'grok';
