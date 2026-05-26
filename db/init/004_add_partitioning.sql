-- Migration: 004_add_partitioning.sql
-- Purpose: Add table partitioning for events and hotspots tables
-- This migration enables efficient time-based data management and query performance
-- for large-scale OSINT event data
--
-- Note: Partitioning is added via new tables (events_partitioned, hotspots_partitioned)
-- to avoid disrupting existing tables. Data migration would be handled separately.
--
-- Date: 2026-05-15

BEGIN;

-- ==============================================================================
-- PARTITIONED EVENTS TABLE
-- ==============================================================================

-- Create partitioned parent table for events (PARTITION BY RANGE event_date)
-- This table replaces the standard events table for new partitions
CREATE TABLE IF NOT EXISTS events_partitioned (
    event_id BIGSERIAL,
    gdelt_global_event_id VARCHAR(50) NOT NULL,
    point_geom GEOMETRY(POINT, 4326),
    event_date TIMESTAMPTZ NOT NULL,
    cameo_code INTEGER,
    country_code VARCHAR(3),
    url TEXT,
    title TEXT,
    source_id BIGINT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (event_id, event_date)
) PARTITION BY RANGE (event_date);

-- Add partitioning indexes on parent table
-- GIST index for spatial queries on point_geom
CREATE INDEX idx_events_partitioned_point_geom
    ON events_partitioned USING GIST (point_geom);

-- B-tree index for time-range queries and sorting
CREATE INDEX idx_events_partitioned_event_date
    ON events_partitioned (event_date DESC);

-- Unique index on gdelt_global_event_id within each partition
-- Note: Composite key with event_date required due to partitioning
CREATE UNIQUE INDEX idx_events_partitioned_gdelt_event_id
    ON events_partitioned (gdelt_global_event_id, event_date);

-- ==============================================================================
-- PARTITIONED HOTSPOTS TABLE
-- ==============================================================================

-- Create partitioned parent table for hotspots (PARTITION BY RANGE start_window)
-- Enables efficient querying of hotspots by time window
CREATE TABLE IF NOT EXISTS hotspots_partitioned (
    hotspot_id BIGSERIAL,
    centroid_geom GEOMETRY(POINT, 4326),
    radius_km REAL,
    start_window TIMESTAMPTZ NOT NULL,
    end_window TIMESTAMPTZ NOT NULL,
    event_count INTEGER DEFAULT 0,
    unique_sources INTEGER DEFAULT 0,
    source_density REAL DEFAULT 0.0,
    geopolitical_diversity REAL DEFAULT 0.0,
    conf_score REAL DEFAULT 0.0,
    llm_verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (hotspot_id, start_window)
) PARTITION BY RANGE (start_window);

-- Add partitioning indexes on parent table
-- GIST index for spatial queries on centroid_geom
CREATE INDEX idx_hotspots_partitioned_centroid_geom
    ON hotspots_partitioned USING GIST (centroid_geom);

-- B-tree index for confidence score sorting (high-priority hotspots first)
CREATE INDEX idx_hotspots_partitioned_conf_score
    ON hotspots_partitioned (conf_score DESC);

-- B-tree index for time-range queries and sorting
CREATE INDEX idx_hotspots_partitioned_start_window
    ON hotspots_partitioned (start_window DESC);

-- ==============================================================================
-- DYNAMIC PARTITION CREATION FUNCTION
-- ==============================================================================

-- Function: create_monthly_partitions()
-- Purpose: Create monthly partitions for events and hotspots tables
-- Parameters:
--   - target_month: Format 'YYYY-MM' (e.g., '2026-05')
--
-- This function creates partitions for both events_partitioned and hotspots_partitioned
-- for the specified month, enabling efficient data management

CREATE OR REPLACE FUNCTION create_monthly_partitions(target_month VARCHAR(7))
RETURNS void AS $$
DECLARE
    partition_start DATE;
    partition_end DATE;
    partition_suffix TEXT;
    events_partition_name TEXT;
    hotspots_partition_name TEXT;
BEGIN
    -- Parse the target month
    partition_start := target_month || '-01';
    partition_end := partition_start + INTERVAL '1 month';
    partition_suffix := REPLACE(target_month, '-', '_');

    -- Create events partition
    events_partition_name := 'events_' || partition_suffix;
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS %I PARTITION OF events_partitioned
         FOR VALUES FROM (%L) TO (%L)',
        events_partition_name, partition_start, partition_end
    );

    -- Create hotspots partition
    hotspots_partition_name := 'hotspots_' || partition_suffix;
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS %I PARTITION OF hotspots_partitioned
         FOR VALUES FROM (%L) TO (%L)',
        hotspots_partition_name, partition_start, partition_end
    );

    RAISE NOTICE 'Created partitions for month %: events_%, hotspots_%',
        target_month, partition_suffix, partition_suffix;
END;
$$ LANGUAGE plpgsql;

-- ==============================================================================
-- CREATE INITIAL PARTITIONS
-- ==============================================================================

-- Create partitions for current month (2026-05)
SELECT create_monthly_partitions('2026-05');

-- Create partitions for next month (2026-06)
SELECT create_monthly_partitions('2026-06');

-- ==============================================================================
-- COMMENTS
-- ==============================================================================

COMMENT ON TABLE events_partitioned IS
    'Partitioned parent table for GDELT events. Partitions are created monthly by event_date.
     Use create_monthly_partitions() function to add new monthly partitions.
     Replaces standard events table for new data ingestion.';

COMMENT ON TABLE hotspots_partitioned IS
    'Partitioned parent table for clustered activity hotspots. Partitions are created monthly by start_window.
     Use create_monthly_partitions() function to add new monthly partitions.
     Replaces standard hotspots table for new data ingestion.';

COMMENT ON FUNCTION create_monthly_partitions IS
    'Creates monthly partitions for both events_partitioned and hotspots_partitioned tables.
     Input: target_month in format ''YYYY-MM'' (e.g., ''2026-05'').
     Creates partitions for the full month range.';

COMMENT ON INDEX idx_events_partitioned_point_geom IS
    'GIST index for efficient spatial queries on event locations.
     Enables fast radius/box queries for geographic hotspot detection.';

COMMENT ON INDEX idx_hotspots_partitioned_centroid_geom IS
    'GIST index for efficient spatial queries on hotspot centroids.
     Enables fast radius queries to find nearby hotspots.';

COMMIT;

-- ==============================================================================
-- POST-MIGRATION NOTES
-- ==============================================================================
--
-- To migrate existing data from events to events_partitioned:
--   INSERT INTO events_partitioned (gdelt_global_event_id, point_geom, event_date,
--       cameo_code, country_code, url, title, source_id)
--   SELECT gdelt_global_event_id, point_geom, event_date,
--       cameo_code, country_code, url, title, source_id
--   FROM events;
--
-- To migrate existing data from hotspots to hotspots_partitioned:
--   INSERT INTO hotspots_partitioned (centroid_geom, radius_km, start_window, end_window,
--       event_count, unique_sources, source_density, geopolitical_diversity,
--       conf_score, llm_verified)
--   SELECT centroid_geom, radius_km, start_window, end_window,
--       event_count, unique_sources, source_density, geopolitical_diversity,
--       conf_score, llm_verified
--   FROM hotspots;
--
-- Schedule the create_monthly_partitions() function via pg_cron or similar
-- to automatically create partitions ahead of time.
-- ==============================================================================