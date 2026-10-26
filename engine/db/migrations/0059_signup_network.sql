-- Sign-ups are also limited per network a client is in (an IPv4 /24, an IPv6 /48), stored hashed like
-- signup_client (rrsrch.identity.onboarding.register).
ALTER TABLE agents ADD COLUMN signup_network text CHECK (signup_network ~ '^[0-9a-f]{64}$');
CREATE INDEX agents_signup_network_idx ON agents (signup_network, created_at) WHERE registered_via = 'self';
