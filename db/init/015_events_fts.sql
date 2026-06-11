-- Migration: 015_events_fts.sql
-- Purpose: FR-15 — full-text search over event/article titles.
BEGIN;

ALTER TABLE events
    ADD COLUMN IF NOT EXISTS title_tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('english', coalesce(title, ''))) STORED;

CREATE INDEX IF NOT EXISTS idx_events_title_tsv
    ON events USING GIN (title_tsv);

COMMIT;
