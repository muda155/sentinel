-- Migration: 007_add_grid_cells.sql
-- Purpose: Create grid_cells table for World Monitor-style 1x1 degree geographic
--   convergence detection (FR-WM-CONVERGENCE).
--
-- This table stores per-cell statistics and convergence scores used to identify
-- areas where multiple distinct event types co-occur within a 24-hour window.
--
-- Grid-cell ID format: '1x1_LAT{floor_lat}_LON{floor_lon}' (e.g., '1x1_LAT48_LON2')
-- Convergence score formula (World Monitor):
--   type_score = unique_event_types * 25
--   count_boost = min(25, total_events * 2)
--   convergence_score = min(100, type_score + count_boost)
--
-- Date: 2026-05-26

BEGIN;

-- ==============================================================================
-- GRID_CELLS TABLE
-- ==============================================================================

-- Create grid_cells table to store 1x1 degree geographic cell statistics
-- Each row represents a single grid cell with convergence metadata
CREATE TABLE IF NOT EXISTS grid_cells (
    cell_id TEXT PRIMARY KEY,
    cell_geom GEOMETRY(Polygon, 4326),
    event_type_count INTEGER DEFAULT 0,
    total_events INTEGER DEFAULT 0,
    convergence_score DOUBLE PRECISION DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ==============================================================================
-- SPATIAL INDEX ON CELL_GEOM
-- ==============================================================================

-- GIST index on cell_geom for efficient spatial queries
-- Enables fast polygon-based queries like "which cell contains this point?"
CREATE INDEX IF NOT EXISTS idx_grid_cells_cell_geom
    ON grid_cells USING GIST (cell_geom);

-- ==============================================================================
-- B-TREE INDEX ON CONVERGENCE_SCORE
-- ==============================================================================

-- B-tree index on convergence_score DESC for sorting and filtering active cells
-- Used to quickly identify high-convergence cells for DBSCAN micro-clustering
CREATE INDEX IF NOT EXISTS idx_grid_cells_convergence_score
    ON grid_cells (convergence_score DESC);

-- ==============================================================================
-- COMMENTS
-- ==============================================================================

COMMENT ON TABLE grid_cells IS
    'Stores 1x1 degree geographic grid cells for World Monitor-style convergence detection.
     Each cell tracks distinct event types and total events within the look-back window.
     Convergence score measures cross-domain signal co-occurrence (FR-WM-CONVERGENCE).';

COMMENT ON COLUMN grid_cells.cell_id IS
    'Primary key. Format: ''1x1_LAT{floor_lat}_LON{floor_lon}''.
     Example: ''1x1_LAT48_LON2'' for the Paris cell (48N, 2E).
     Derived from event coordinates using assign_grid_cell().';

COMMENT ON COLUMN grid_cells.cell_geom IS
    'PostGIS polygon geometry representing the 1x1 degree cell boundary.
     Enables spatial queries: point-in-cell containment, cell intersection, and overlap analysis.
     Generated using ST_MakeEnvelope(lon, lat, lon+1, lat+1, 4326).';

COMMENT ON COLUMN grid_cells.event_type_count IS
    'Number of distinct event types in this cell within the look-back window.
     Used to compute type_score = event_type_count * 25 in the convergence formula.';

COMMENT ON COLUMN grid_cells.total_events IS
    'Total number of events in this cell within the look-back window.
     Used to compute count_boost = min(25, total_events * 2) in the convergence formula.';

COMMENT ON COLUMN grid_cells.convergence_score IS
    'World Monitor convergence score (0-100).
     Formula: min(100, event_type_count * 25 + min(25, total_events * 2)).
     Cells with score >= 1 are considered active convergence zones.';

COMMENT ON INDEX idx_grid_cells_cell_geom IS
    'GIST index on cell_geom for efficient spatial queries.
     Enables fast point-in-cell containment checks during convergence detection.';

COMMENT ON INDEX idx_grid_cells_convergence_score IS
    'B-tree index on convergence_score DESC for identifying high-convergence cells.
     Used to filter active cells for DBSCAN micro-clustering.';

COMMIT;
