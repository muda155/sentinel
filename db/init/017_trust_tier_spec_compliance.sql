-- Migration: 017_trust_tier_spec_compliance.sql
-- Purpose: align sources.trust_tier with spec Section 6.2:
--   int trust_tier  "DEFAULT 4 — 1=wire, 2=major, 3=specialist, 4=unknown"
--   float trust_score GENERATED: CASE trust_tier WHEN 1 THEN 1.0 WHEN 2 THEN 0.8
--                                 WHEN 3 THEN 0.6 ELSE 0.4 END
-- Long-lived databases accumulated ad-hoc state: text tiers 'A'/'B'/'C', a
-- hand-made check constraint, and manually edited trust_score values. All are
-- replaced here; trust_score becomes derived state so the admin tier editor
-- (PATCH /sources/{id}) actually drives FR-7 source_density weighting.
BEGIN;

ALTER TABLE sources DROP CONSTRAINT IF EXISTS sources_trust_tier_check;

-- Normalize legacy text values, then convert the column type.
UPDATE sources SET trust_tier = CASE upper(trim(trust_tier))
    WHEN 'A' THEN '1'
    WHEN 'B' THEN '2'
    WHEN 'C' THEN '3'
    WHEN 'D' THEN '4'
    ELSE CASE WHEN trim(trust_tier) ~ '^[1-4]$' THEN trim(trust_tier) END
END
WHERE trust_tier IS NOT NULL;

ALTER TABLE sources ALTER COLUMN trust_tier DROP DEFAULT;
ALTER TABLE sources
    ALTER COLUMN trust_tier TYPE smallint USING trust_tier::smallint,
    ALTER COLUMN trust_tier SET DEFAULT 4;

ALTER TABLE sources
    ADD CONSTRAINT sources_trust_tier_range CHECK (trust_tier BETWEEN 1 AND 4);

-- trust_score becomes a stored generated column (spec 6.2). Any manually
-- edited values are intentionally discarded: tier is the source of truth.
DROP INDEX IF EXISTS idx_sources_trust_score;
ALTER TABLE sources DROP COLUMN IF EXISTS trust_score;
ALTER TABLE sources ADD COLUMN trust_score real GENERATED ALWAYS AS (
    CASE trust_tier WHEN 1 THEN 1.0 WHEN 2 THEN 0.8 WHEN 3 THEN 0.6 ELSE 0.4 END
) STORED;
CREATE INDEX idx_sources_trust_score ON sources (trust_score DESC);

COMMENT ON COLUMN sources.trust_tier IS
    'Spec 6.2: 1=wire/gov, 2=major outlet, 3=specialist/regional, 4=aggregator/unknown.';
COMMENT ON COLUMN sources.trust_score IS
    'GENERATED from trust_tier (1.0/0.8/0.6/0.4); feeds FR-7 source_density.';

COMMIT;
