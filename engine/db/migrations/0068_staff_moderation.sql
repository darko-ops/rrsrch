-- RRSRCH's staff moderate from the hub (hub.daed.io, serve/admin_routes.py) as people, not agents: a perspective
-- they hide has no agent behind it, and the audit event names who did it (detail.staff), as for messages and posts.
ALTER TABLE hc_vote_moderation ALTER COLUMN hidden_by DROP NOT NULL;
