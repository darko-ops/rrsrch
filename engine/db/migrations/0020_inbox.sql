-- Read state for an agent's inbox (GET /v1/inbox): everything up to inbox_read_through counts as read ("mark all
-- read"), and inbox_reads holds items read one at a time above that line. Items are "event:N" (an audit event
-- delivered as a notification) or "review_request:N".
ALTER TABLE agents ADD COLUMN inbox_read_through bigint NOT NULL DEFAULT 0;
CREATE TABLE inbox_reads (
    agent_id  bigint NOT NULL REFERENCES agents(id),
    item      text NOT NULL CHECK (item ~ '^(event|review_request):[0-9]+$'),
    read_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_id, item)
);
