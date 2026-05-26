-- Migration: 008_align_hotspots_schema.sql
-- Purpose: Align hotspots table schema with spec Section 6.2 (FR-6, FR-WM-CONVERGENCE)
--   - Add cell_id FK reference to grid_cells table
--   - Add convergence_score inherited from parent grid cell
--   - Add alert_level (Critical / High / Medium) derived from convergence thresholds
--   - Add unique_event_types for per-hotspot type tracking
--   - Add B-tree indexes on alert_level, convergence_score, and start_window
--
-- All ALTER TABLE statements use IF NOT EXISTS for idempotency.
--
-- Date: 2026-05-26

BEGIN;

-- ==============================================================================
-- ADD NEW COLUMNS TO HOTSPOTS TABLE
-- ==============================================================================

-- Add cell_id FK reference to grid_cells table (FR-6)
-- Links each hotspot to its parent 1x1 degree grid cell
ALTER TABLE hotspots
    ADD COLUMN IF NOT EXISTS cell_id TEXT;

-- Add convergence_score inherited from parent grid cell
-- Uses World Monitor formula: min(100, event_type_count * 25 + min(25, total_events * 2))
-- This is distinct from conf_score (Sentinel's original consensus confidence score)
ALTER TABLE hotspots
    ADD COLUMN IF NOT EXISTS convergence_score DOUBLE PRECISION;

-- Add alert_level derived from convergence score thresholds
-- Values: 'Critical' (80-100), 'High' (55-80), 'Medium' (30-55)
ALTER TABLE hotspots
    ADD COLUMN IF NOT EXISTS alert_level TEXT;

-- Add unique_event_types for per-hotspot distinct event type tracking
-- GDELT-only cells have at most 1 type (military_conflict), ACLED+GDELT can have more
ALTER TABLE hotspots
    ADD COLUMN IF NOT EXISTS unique_event_types INTEGER DEFAULT 0;

-- ==============================================================================
-- ADD INDEXES
-- ==============================================================================

-- B-tree index on alert_level for filtering by severity
-- Enables queries like: WHERE alert_level IN ('High', 'Critical')
CREATE INDEX IF NOT EXISTS idx_hotspots_alert_level
    ON hotspots (alert_level);

-- B-tree index on convergence_score DESC for sorting by convergence signal
-- Enables ordering hotspots by strongest cross-domain signal co-occurrence
CREATE INDEX IF NOT EXISTS idx_hotspots_convergence_score
    ON hotspots (convergence_score DESC);

-- B-tree index on start_window DESC for sorting by recency
-- Enables efficient time-based sorting and filtering of hotspots
CREATE INDEX IF NOT EXISTS idx_hotspots_start_window
    ON hotspots (start_window DESC);

-- B-tree index on cell_id for efficient cell-based hotspot lookups
CREATE INDEX IF NOT EXISTS idx_hotspots_cell_id
    ON hotspots (cell_id);

-- ==============================================================================
-- COMMENTS
-- ==============================================================================

COMMENT ON COLUMN hotspots.cell_id IS
    'Foreign key reference to grid_cells.cell_id.
     Links each hotspot to its parent 1x1 degree geographic grid cell.
     Enables convergence score inheritance from the parent cell.';

COMMENT ON COLUMN hotspots.convergence_score IS
    'World Monitor convergence score (0-100) inherited from the parent grid cell.
     Measures cross-domain signal co-occurrence (geographic signal strength).
     This is DISTINCT from conf_score which measures source reliability.
     Thresholds: >= 80 Critical, >= 55 High, >= 30 Medium.';

COMMENT ON COLUMN hotspots.alert_level IS
    'Alert level derived from convergence score thresholds:
     - ''Critical'': convergence_score >= 80 (3+ event types, high event count)
     - ''High'': convergence_score >= 55 (2-3 event types, moderate event count)
     - ''Medium'': convergence_score >= 30 (2 event types, low event count)
     Used for UI filtering and prioritization.';

COMMENT ON COLUMN hotspots.unique_event_types IS
    'Number of distinct event types represented in this hotspot.
     Derived from the event types of member events.
     Used to determine convergence type score component.';

COMMENT ON INDEX idx_hotspots_alert_level IS
    'B-tree index on alert_level for efficient filtering by severity.
     Enables fast queries filtering to High/Critical alerts for dashboard display.';

COMMENT ON INDEX idx_hotspots_convergence_score IS
    'B-tree index on convergence_score DESC for sorting by convergence signal strength.
     Enables fast identification of strongest cross-domain convergence zones.';

COMMENT ON INDEX idx_hotspots_start_window IS
    'B-tree index on start_window DESC for efficient time-based sorting.
     Enables fast retrieval of most recent hotspots.';

COMMENT ON INDEX idx_hotspots_cell_id IS
    'B-tree index on cell_id for efficient cell-based hotspot lookups.
     Enables fast JOINs between hotspots and grid_cells.';

COMMIT;
