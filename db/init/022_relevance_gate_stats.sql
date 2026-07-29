-- FR-26: observability for the relevance gate. Without these counters the
-- thresholds would be tuned blind and the evaluation could not quantify the
-- gate's effect. Nullable: rows scored before M8 have no measurement.
ALTER TABLE hotspots ADD COLUMN IF NOT EXISTS gated_pairs INTEGER;
ALTER TABLE hotspots ADD COLUMN IF NOT EXISTS vacuous_claims_dropped INTEGER;
