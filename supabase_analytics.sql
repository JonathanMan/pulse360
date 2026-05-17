-- T3-5: Usage analytics table
-- Run once in the Supabase SQL editor.

CREATE TABLE IF NOT EXISTS user_analytics (
    id           BIGSERIAL   PRIMARY KEY,
    event        TEXT        NOT NULL,
    user_id      TEXT,                           -- NULL for unauthenticated sessions
    session_id   TEXT        NOT NULL,
    properties   JSONB       NOT NULL DEFAULT '{}',
    occurred_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for common queries: events by user, events by type, recent events
CREATE INDEX IF NOT EXISTS idx_ua_user_id     ON user_analytics (user_id);
CREATE INDEX IF NOT EXISTS idx_ua_event       ON user_analytics (event);
CREATE INDEX IF NOT EXISTS idx_ua_occurred_at ON user_analytics (occurred_at DESC);

-- No RLS needed — app uses the service role key.
-- Retention: optionally add a pg_cron job to delete rows older than 90 days:
--   SELECT cron.schedule('analytics-cleanup', '0 3 * * *',
--     $$DELETE FROM user_analytics WHERE occurred_at < NOW() - INTERVAL '90 days'$$);
