-- Migration: 014_hotspot_names.sql
-- Purpose: FR-14 -- human-readable hotspot names resolved at clustering write time.
BEGIN;

ALTER TABLE hotspots
    ADD COLUMN IF NOT EXISTS name text;

CREATE INDEX IF NOT EXISTS idx_hotspots_name_lower
    ON hotspots (lower(name) text_pattern_ops);

COMMIT;
