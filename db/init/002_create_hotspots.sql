CREATE TABLE IF NOT EXISTS hotspots (
    hotspot_id BIGSERIAL PRIMARY KEY,
    centroid_geom geometry(Point, 4326) NOT NULL,
    radius_km DOUBLE PRECISION NOT NULL,
    start_window timestamptz NOT NULL,
    end_window timestamptz NOT NULL,
    event_count INTEGER NOT NULL,
    unique_sources INTEGER NOT NULL,
    source_density DOUBLE PRECISION,
    geopolitical_diversity DOUBLE PRECISION,
    conf_score DOUBLE PRECISION,
    llm_verified BOOLEAN NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS event_hotspot (
    event_id BIGINT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    hotspot_id BIGINT NOT NULL REFERENCES hotspots(hotspot_id) ON DELETE CASCADE,
    PRIMARY KEY (event_id, hotspot_id)
);

CREATE INDEX IF NOT EXISTS idx_hotspots_centroid_geom ON hotspots USING GIST (centroid_geom);
CREATE INDEX IF NOT EXISTS idx_event_hotspot_hotspot_id ON event_hotspot (hotspot_id);
