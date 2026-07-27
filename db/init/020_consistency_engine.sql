-- M6 Consistency Engine (FR-21/FR-22, specs.md section 4.8).
-- FR-21: persist GDELT/ACLED analytic fields previously discarded at insert.
ALTER TABLE events ADD COLUMN IF NOT EXISTS actor1_name TEXT;
ALTER TABLE events ADD COLUMN IF NOT EXISTS actor2_name TEXT;
ALTER TABLE events ADD COLUMN IF NOT EXISTS goldstein_scale REAL;
ALTER TABLE events ADD COLUMN IF NOT EXISTS avg_tone REAL;
ALTER TABLE events ADD COLUMN IF NOT EXISTS num_sources INTEGER;
ALTER TABLE events ADD COLUMN IF NOT EXISTS notes TEXT;
ALTER TABLE events ADD COLUMN IF NOT EXISTS fatalities INTEGER;

-- FR-22: hotspot-level consistency score. NULL = engine has not evaluated it.
ALTER TABLE hotspots ADD COLUMN IF NOT EXISTS consistency_score DOUBLE PRECISION;

CREATE TABLE IF NOT EXISTS claims (
    claim_id BIGSERIAL PRIMARY KEY,
    hotspot_id BIGINT NOT NULL REFERENCES hotspots(hotspot_id) ON DELETE CASCADE,
    claim_text TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('corroborated', 'uncorroborated', 'disputed')),
    consensus_weight DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- event_id has no FK: events is partitioned by event_date and its PK includes the
-- partition key. Rows die with their claim via the claims -> hotspots cascade.
CREATE TABLE IF NOT EXISTS claim_evidence (
    claim_id BIGINT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
    event_id BIGINT NOT NULL,
    relation TEXT NOT NULL CHECK (relation IN ('supports', 'contradicts', 'neutral')),
    probability DOUBLE PRECISION,
    PRIMARY KEY (claim_id, event_id)
);

CREATE INDEX IF NOT EXISTS idx_claims_hotspot ON claims (hotspot_id);
