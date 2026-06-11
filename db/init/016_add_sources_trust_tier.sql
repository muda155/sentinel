-- Migration: 016_add_sources_trust_tier.sql
-- Purpose: codify the ad-hoc sources.trust_tier column (text 'A'/'B'/'C').
--   The column existed only in long-lived databases (added manually during M3);
--   fresh installs lacked it, so /search and /hotspots/{id}/events failed with
--   UndefinedColumn. Text type matches the live data; the int-vs-text PATCH
--   reconciliation is tracked as follow-up work.
BEGIN;

ALTER TABLE sources
    ADD COLUMN IF NOT EXISTS trust_tier text;

COMMENT ON COLUMN sources.trust_tier IS
    'Source trust tier (text: A=highest). Added ad hoc in M3, codified here.';

COMMIT;
