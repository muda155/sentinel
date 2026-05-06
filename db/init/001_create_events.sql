CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS events (
    event_id BIGSERIAL PRIMARY KEY,
    gdelt_global_event_id BIGINT NOT NULL UNIQUE,
    point_geom geometry(Point, 4326) NOT NULL,
    event_date timestamptz NOT NULL,
    cameo_code text,
    url text,
    title text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_events_event_date ON events (event_date DESC);
CREATE INDEX IF NOT EXISTS idx_events_point_geom ON events USING GIST (point_geom);
