-- ============================================================================
-- Pie360 — Supabase migrations
-- Run once in the Supabase SQL editor (Dashboard → SQL editor → New query).
-- Safe to re-run: all statements use IF NOT EXISTS / ON CONFLICT DO NOTHING.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- 1. macro_signals
--    Single-row store for the latest Macro Pulse forecaster signals.
--    The app upserts id=1 on every refresh; reads via .eq("id", 1).single().
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS macro_signals (
    id              INTEGER         PRIMARY KEY,          -- always 1
    signals_json    JSONB           NOT NULL,             -- full signals dict
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- Seed row so the first .single() call doesn't throw PostgREST 406.
-- The app will overwrite this on the next Refresh.
INSERT INTO macro_signals (id, signals_json)
VALUES (1, '{}'::jsonb)
ON CONFLICT (id) DO NOTHING;

-- Auto-stamp updated_at on every upsert
CREATE OR REPLACE FUNCTION _set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS macro_signals_updated_at ON macro_signals;
CREATE TRIGGER macro_signals_updated_at
    BEFORE UPDATE ON macro_signals
    FOR EACH ROW EXECUTE FUNCTION _set_updated_at();


-- ----------------------------------------------------------------------------
-- 2. alert_history
--    Append-only log of every alert that fires.
--    Written by components/alert_engine.py _log_trigger().
--    Readable in pages/12_Alerts.py for the history tab.
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS alert_history (
    id              BIGSERIAL       PRIMARY KEY,
    user_email      TEXT            NOT NULL,
    rule_id         TEXT            NOT NULL,             -- alert_rules.id (uuid)
    rule_name       TEXT            NOT NULL,
    series_id       TEXT            NOT NULL,             -- e.g. "T10Y3M", "RECESSION_PROB"
    operator        TEXT            NOT NULL,             -- ">", "crosses_below", etc.
    threshold       DOUBLE PRECISION NOT NULL,
    current_value   DOUBLE PRECISION NOT NULL,
    triggered_at    TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- Efficient lookups: per-user history, recent-first
CREATE INDEX IF NOT EXISTS idx_ah_user_email    ON alert_history (user_email);
CREATE INDEX IF NOT EXISTS idx_ah_triggered_at  ON alert_history (triggered_at DESC);
CREATE INDEX IF NOT EXISTS idx_ah_rule_id       ON alert_history (rule_id);

-- Retention: keep 90 days (optional — needs pg_cron extension enabled in Supabase)
-- SELECT cron.schedule('alert-history-cleanup', '0 4 * * *',
--   $$DELETE FROM alert_history WHERE triggered_at < NOW() - INTERVAL '90 days'$$);


-- ----------------------------------------------------------------------------
-- 3. alert_rules (ensure it exists — app inserts into this on first rule add)
--    If you already have this table, this is a no-op.
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS alert_rules (
    id              TEXT            PRIMARY KEY,          -- uuid4 hex
    user_email      TEXT            NOT NULL,
    name            TEXT            NOT NULL,
    series_id       TEXT            NOT NULL,
    operator        TEXT            NOT NULL,
    threshold       DOUBLE PRECISION NOT NULL,
    email           TEXT,
    active          BOOLEAN         NOT NULL DEFAULT TRUE,
    last_value      DOUBLE PRECISION,
    last_triggered  TEXT,                                 -- ISO date string
    created_at      TEXT            NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ar_user_email ON alert_rules (user_email);
