-- Migration: 006_align_events_schema.sql
-- Purpose: Align events table schema with spec Section 6.2 (FR-3, FR-WM-CONVERGENCE, NFR-7)
--   - Add source_system discriminator column for multi-source ingestion (GDELT/ACLED)
--   - Add external_event_id as the canonical external ID per source system
--   - Add grid_cell_id for 1x1 degree grid-cell convergence detection
--   - Drop old UNIQUE constraint on gdelt_global_event_id (keep the column)
--   - Add composite UNIQUE (source_system, external_event_id) for idempotent inserts
--   - Add index on grid_cell_id for efficient cell-based queries
--
-- Date: 2026-05-26

BEGIN;

-- ==============================================================================
-- ADD NEW COLUMNS TO EVENTS TABLE
-- ==============================================================================

-- Add source_system discriminator column (FR-3 / NFR-7)
-- 'GDELT' for GDELT 2.0 events, 'ACLED' for ACLED events
ALTER TABLE events
    ADD COLUMN IF NOT EXISTS source_system TEXT NOT NULL DEFAULT 'GDELT';

-- Add external_event_id as the canonical external identifier per source system
-- GDELT uses GlobalEventID (string), ACLED uses event_id_cnty
ALTER TABLE events
    ADD COLUMN IF NOT EXISTS external_event_id TEXT;

-- Populate external_event_id from existing gdelt_global_event_id values
UPDATE events
SET external_event_id = gdelt_global_event_id::TEXT
WHERE external_event_id IS NULL;

-- Make external_event_id NOT NULL after population
ALTER TABLE events
    ALTER COLUMN external_event_id SET NOT NULL;

-- Add grid_cell_id for 1x1 degree grid-cell convergence detection (FR-WM-CONVERGENCE)
-- Format: '1x1_LAT{floor_lat}_LON{floor_lon}' (e.g., '1x1_LAT48_LON2')
ALTER TABLE events
    ADD COLUMN IF NOT EXISTS grid_cell_id TEXT;

-- ==============================================================================
-- DROP OLD UNIQUE CONSTRAINT AND ADD COMPOSITE UNIQUE
-- ==============================================================================

-- Drop the old UNIQUE constraint on gdelt_global_event_id (keep the column)
-- We are replacing it with a composite unique constraint (source_system, external_event_id)
ALTER TABLE events
    DROP CONSTRAINT IF EXISTS events_gdelt_global_event_id_key;

-- Also drop the unique index from the partitioned schema if it exists
DROP INDEX IF EXISTS idx_events_partitioned_gdelt_event_id;

-- Add composite unique constraint (source_system, external_event_id) for idempotent inserts
-- This guarantees no duplicates per source system (NFR-7 / FR-3)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_events_external'
          AND conrelid = 'events'::regclass
    ) THEN
        ALTER TABLE events
            ADD CONSTRAINT uq_events_external UNIQUE (source_system, external_event_id);
    END IF;
END $$;

-- ==============================================================================
-- ADD INDEX ON GRID_CELL_ID
-- ==============================================================================

-- B-tree index on grid_cell_id for efficient cell-based queries
-- Used for grid-cell convergence detection and filtering events by cell
CREATE INDEX IF NOT EXISTS idx_events_grid_cell_id
    ON events (grid_cell_id);

-- Create index on source_system for multi-source query filtering
CREATE INDEX IF NOT EXISTS idx_events_source_system
    ON events (source_system);

-- ==============================================================================
-- COMMENTS
-- ==============================================================================

COMMENT ON COLUMN events.source_system IS
    'Source system discriminator: ''GDELT'' for GDELT 2.0 events, ''ACLED'' for ACLED events.
     Used as part of the composite unique key (source_system, external_event_id) for idempotent inserts.';

COMMENT ON COLUMN events.external_event_id IS
    'Canonical external event identifier per source system.
     For GDELT: GlobalEventID (string). For ACLED: event_id_cnty.
     Combined with source_system to form a composite unique key (NFR-7).';

COMMENT ON COLUMN events.grid_cell_id IS
    '1x1 degree grid cell identifier for geographic convergence detection.
     Format: ''1x1_LAT{floor_lat}_LON{floor_lon}'' (e.g., ''1x1_LAT48_LON2'' for Paris).
     Used for World Monitor-style grid-cell convergence scoring (FR-WM-CONVERGENCE).';

COMMENT ON INDEX idx_events_grid_cell_id IS
    'B-tree index on grid_cell_id for efficient cell-based queries.
     Enables fast filtering and grouping of events by their 1x1 degree grid cell.';

COMMENT ON INDEX idx_events_source_system IS
    'B-tree index on source_system for multi-source query filtering.
     Enables efficient filtering by data source (GDELT vs ACLED).';

COMMIT;
