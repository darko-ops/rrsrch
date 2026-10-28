-- Every grokbot reports one model, grokbot/grok-bot (owner's decision, 2026-10-28): grokbots can't name the Grok
-- model under them, and their check-ins needn't send it (collab/checkin.py). collab/models.py lists it as grok-bot,
-- so the benchmark snapshots already stored as "grokbot" (0058) move to that name too.
UPDATE agents SET model = 'grokbot/grok-bot' WHERE lower(model) LIKE 'grokbot/%' AND lower(model) <> 'grokbot/grok-bot';
UPDATE benchmark_snapshots SET model = 'grok-bot' WHERE model = 'grokbot';
