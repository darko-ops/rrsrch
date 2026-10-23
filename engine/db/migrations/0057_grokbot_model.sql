-- Agents on the grokbot platform report "grokbot/<the bot's own name>"; collab/models.py now counts them as grok.
-- Relabel the benchmark snapshots already stored under each bot's name.
UPDATE benchmark_snapshots s SET model = 'grok', family = 'grok'
FROM agents a
WHERE a.id = s.agent_id AND lower(a.model) LIKE 'grokbot/%' AND s.model NOT LIKE 'grok%';
