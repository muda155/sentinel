-- Migration: 018_hotspots_end_window_index.sql
-- Purpose: Support recency filtering and stale-row cleanup on hotspots.
--   Queries and DELETEs now bound by `end_window` (most recent member event);
--   this B-tree keeps both cheap as the table grows.
-- Date: 2026-07-14

BEGIN;

CREATE INDEX IF NOT EXISTS idx_hotspots_end_window
    ON hotspots (end_window DESC);

COMMENT ON INDEX idx_hotspots_end_window IS
    'B-tree on end_window DESC. Supports the API max-age filter
     (fetch_hotspots) and the periodic stale-hotspot DELETE (retention).';

COMMIT;
