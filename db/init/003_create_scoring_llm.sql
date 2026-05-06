ALTER TABLE events
    ADD COLUMN IF NOT EXISTS country_code text;

ALTER TABLE hotspots
    ADD COLUMN IF NOT EXISTS source_density DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS geopolitical_diversity DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS conf_score DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS llm_verified BOOLEAN NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS llm_summaries (
    summary_id BIGSERIAL PRIMARY KEY,
    hotspot_id BIGINT NOT NULL UNIQUE REFERENCES hotspots(hotspot_id) ON DELETE CASCADE,
    summary_text text NOT NULL,
    conflict_detected BOOLEAN NOT NULL,
    conflict_detail text,
    sources_cited text NOT NULL,
    llm_model_version text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_hotspots_conf_score ON hotspots (conf_score DESC);
