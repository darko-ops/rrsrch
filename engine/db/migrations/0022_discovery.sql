-- Discovery: what search engines and agents need to find public knowledge (docs/AGENTS.md, "Being found").
--
--   claims.state_changed_at   when a claim's review state last changed, for the sitemap's lastmod
--   indexnow_queue            an outbox of public pages to announce to IndexNow (Bing, Yandex, Seznam, Naver):
--                             a claim whose state changed (or that entered a public repository), a question that
--                             was asked or answered. `rrsrch indexnow` sends it on a timer; nothing here waits on
--                             the network. Paths only: the sender adds the public base URL
--
-- Both are filled by triggers, so every place that writes a claim's state or a question is covered without each
-- remembering to.
ALTER TABLE claims ADD COLUMN state_changed_at timestamptz;

CREATE TABLE indexnow_queue (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    path        text NOT NULL CHECK (path ~ '^/(claims|questions)/[0-9]+$'),
    queued_at   timestamptz NOT NULL DEFAULT now(),
    sent_at     timestamptz,
    attempts    int NOT NULL DEFAULT 0,
    last_error  text
);
-- one pending row per page: a claim that changes state twice before the next send is announced once, and a page
-- that gave up after too many failed sends is tried afresh when it changes again
CREATE UNIQUE INDEX indexnow_queue_pending_idx ON indexnow_queue (path) WHERE sent_at IS NULL;

CREATE FUNCTION indexnow_claim() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.state IS NOT DISTINCT FROM OLD.state THEN
            RETURN NEW;
        END IF;
        NEW.state_changed_at := now();
    END IF;
    IF EXISTS (SELECT 1 FROM repositories WHERE id = NEW.repository_id AND visibility = 'public') THEN
        INSERT INTO indexnow_queue (path) VALUES ('/claims/' || NEW.id)
            ON CONFLICT (path) WHERE sent_at IS NULL DO UPDATE SET attempts = 0;
    END IF;
    RETURN NEW;
END $$;
-- BEFORE, so the timestamp lands in the same row write; AFTER INSERT, so the new claim has its id
CREATE TRIGGER claims_state_changed BEFORE UPDATE OF state ON claims
    FOR EACH ROW EXECUTE FUNCTION indexnow_claim();
CREATE TRIGGER claims_indexnow_insert AFTER INSERT ON claims
    FOR EACH ROW EXECUTE FUNCTION indexnow_claim();

CREATE FUNCTION indexnow_question() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.kind = 'question' AND NEW.moderation = 'visible'
       AND (TG_OP = 'INSERT' OR NEW.status IS DISTINCT FROM OLD.status)
       AND EXISTS (SELECT 1 FROM repositories WHERE id = NEW.repository_id AND visibility = 'public') THEN
        INSERT INTO indexnow_queue (path) VALUES ('/questions/' || NEW.id)
            ON CONFLICT (path) WHERE sent_at IS NULL DO UPDATE SET attempts = 0;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER research_posts_indexnow AFTER INSERT OR UPDATE OF status ON research_posts
    FOR EACH ROW EXECUTE FUNCTION indexnow_question();
