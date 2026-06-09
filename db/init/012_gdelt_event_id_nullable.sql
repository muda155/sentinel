-- Migration: 012_gdelt_event_id_nullable.sql
-- Purpose: Allow events.gdelt_global_event_id to be NULL.
--   Migration 006 made external_event_id the canonical per-source identifier
--   (GDELT GlobalEventID, ACLED event_id_cnty) but left gdelt_global_event_id
--   NOT NULL. That column is GDELT-specific: ACLED events have no GDELT global
--   event id, so the ACLED ingest path cannot satisfy the NOT NULL constraint.
--   Relax it so non-GDELT sources can insert (they leave the column NULL while
--   carrying their own id in external_event_id).
--
--   GDELT ingestion continues to populate gdelt_global_event_id with the real
--   GlobalEventID; only the constraint changes here.
-- Date: 2026-06-08

-- Idempotent: DROP NOT NULL is a no-op if the column is already nullable.
ALTER TABLE events
    ALTER COLUMN gdelt_global_event_id DROP NOT NULL;

COMMENT ON COLUMN events.gdelt_global_event_id IS
    'GDELT GlobalEventID for GDELT-sourced events; NULL for non-GDELT sources
     (e.g. ACLED). The canonical per-source identifier is external_event_id,
     unique together with source_system and event_date (see migration 006).';
