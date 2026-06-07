-- Migration: 010_partition_events.sql
-- Purpose: Convert the live events table to monthly RANGE partitioning on event_date
--   so that retention is a metadata-only DROP of old partitions (spec Section 6.2.1, M1).
--   Idempotent: skips entirely if events is already partitioned.
-- Date: 2026-06-07

DO $$
BEGIN
    -- Skip if events is already a partitioned table (safe re-run / fresh-init order).
    IF EXISTS (
        SELECT 1 FROM pg_partitioned_table pt
        JOIN pg_class c ON c.oid = pt.partrelid
        WHERE c.relname = 'events'
    ) THEN
        RAISE NOTICE 'events is already partitioned; skipping 010.';
        RETURN;
    END IF;

    -- 1. Retire the stale parallel partitioned tables from the old 004 migration.
    DROP TABLE IF EXISTS events_partitioned CASCADE;
    DROP TABLE IF EXISTS hotspots_partitioned CASCADE;

    -- 2. Drop constraint and indexes on the old table that would conflict by name.
    ALTER TABLE events DROP CONSTRAINT IF EXISTS uq_events_external;
    DROP INDEX IF EXISTS idx_events_event_date;
    DROP INDEX IF EXISTS idx_events_point_geom;
    DROP INDEX IF EXISTS idx_events_grid_cell_id;
    DROP INDEX IF EXISTS idx_events_source_system;

    -- 3. Build a partitioned clone of the live events schema (column-set agnostic).
    CREATE TABLE events_new (LIKE events INCLUDING DEFAULTS INCLUDING COMMENTS)
        PARTITION BY RANGE (event_date);

    -- 4. Primary key must include the partition key.
    ALTER TABLE events_new ADD PRIMARY KEY (event_id, event_date);

    -- 5. Composite uniqueness (NFR-7) must include the partition key on a
    --    partitioned table. Idempotency holds because event_date is deterministic.
    ALTER TABLE events_new
        ADD CONSTRAINT uq_events_external
        UNIQUE (source_system, external_event_id, event_date);

    -- 6. Recreate the indexes the live events table carries (FR-WM / spatial / time).
    CREATE INDEX idx_events_event_date ON events_new (event_date DESC);
    CREATE INDEX idx_events_point_geom ON events_new USING GIST (point_geom);
    CREATE INDEX idx_events_grid_cell_id ON events_new (grid_cell_id);
    CREATE INDEX idx_events_source_system ON events_new (source_system);

    -- 7. Create partitions covering existing data through the current month.
    --    Future months are created ahead of time by pipeline.retention.ensure_partitions().
    DECLARE
        m  DATE;
        lo DATE := COALESCE(
            (SELECT date_trunc('month', min(event_date))::date FROM events),
            date_trunc('month', now())::date
        );
        hi DATE := date_trunc('month', now())::date;
        pname TEXT;
    BEGIN
        m := lo;
        WHILE m <= hi LOOP
            pname := 'events_' || to_char(m, 'YYYY_MM');
            EXECUTE format(
                'CREATE TABLE IF NOT EXISTS %I PARTITION OF events_new
                 FOR VALUES FROM (%L) TO (%L)',
                pname, m, (m + INTERVAL '1 month')::date
            );
            m := (m + INTERVAL '1 month')::date;
        END LOOP;
    END;

    -- 8. Copy existing rows into the partitioned table.
    INSERT INTO events_new SELECT * FROM events;

    -- 9. event_hotspot's FK to events(event_id) can no longer be satisfied
    --    (event_id is not unique alone on a partitioned table). Drop it; keep an index.
    ALTER TABLE event_hotspot DROP CONSTRAINT IF EXISTS event_hotspot_event_id_fkey;
    CREATE INDEX IF NOT EXISTS idx_event_hotspot_event_id ON event_hotspot (event_id);

    -- 10. Swap tables and re-own the BIGSERIAL sequence so it survives the drop.
    ALTER TABLE events RENAME TO events_old;
    ALTER TABLE events_new RENAME TO events;
    ALTER SEQUENCE events_event_id_seq OWNED BY events.event_id;

    -- 11. Drop the old non-partitioned table.
    DROP TABLE events_old CASCADE;

    RAISE NOTICE 'events converted to monthly range partitioning.';
END $$;