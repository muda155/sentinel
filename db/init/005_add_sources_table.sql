-- Migration: 005_add_sources_table.sql
-- Purpose: Add sources table for tracking event source domains and their metadata
-- This enables tracking of source reliability, geographic origin, and anonymous sources
--
-- Date: 2026-05-15

BEGIN;

-- ==============================================================================
-- SOURCES TABLE
-- ==============================================================================

-- Create sources table to track event source domains
-- This table deduplicates source information and provides trust scoring
CREATE TABLE IF NOT EXISTS sources (
    source_id BIGSERIAL PRIMARY KEY,
    domain VARCHAR(255) NOT NULL UNIQUE,
    country_code VARCHAR(3),
    country_name VARCHAR(100),
    trust_score REAL DEFAULT 0.5,
    last_verified_at TIMESTAMPTZ,
    is_anonymous BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index on domain for fast lookups (unique constraint already creates an index)
CREATE UNIQUE INDEX idx_sources_domain ON sources (domain);

-- Index on country_code for geographic queries and reporting
CREATE INDEX idx_sources_country_code ON sources (country_code);

-- Index on trust_score for identifying high/low trust sources
CREATE INDEX idx_sources_trust_score ON sources (trust_score DESC);

-- Index on is_anonymous to quickly find/exclude anonymous sources
CREATE INDEX idx_sources_is_anonymous ON sources (is_anonymous) WHERE is_anonymous = TRUE;

COMMENT ON TABLE sources IS
    'Stores information about event source domains. Each unique domain is recorded once
     with metadata including country origin, trust score, and verification status.
     Linked to events via source_id foreign key for source attribution.';

COMMENT ON COLUMN sources.domain IS
    'The domain name extracted from the event URL (e.g., ''bbc.com'').
     Used as unique identifier for source deduplication.';

COMMENT ON COLUMN sources.country_code IS
    'ISO 3166-1 alpha-3 country code of the source organization''s origin.
     Used for geopolitical diversity calculations.';

COMMENT ON COLUMN sources.country_name IS
    'Human-readable country name for reporting purposes.';

COMMENT ON COLUMN sources.trust_score IS
    'Numeric trust score from 0.0 to 1.0. Default 0.5.
     Sources with higher trust scores contribute more to confidence calculations.
     Should be updated based on verification results and fact-checking feedback.';

COMMENT ON COLUMN sources.last_verified_at IS
    'Timestamp of the last verification check for this source.
     NULL if never verified.';

COMMENT ON COLUMN sources.is_anonymous IS
    'TRUE for sources that should not be publicly identified (e.g., leaked documents).
     Used to exclude anonymous sources from certain reports while still using them for data.';

-- ==============================================================================
-- ADD SOURCE_ID TO EVENTS TABLE
-- ==============================================================================

-- Add source_id column to events table for source attribution
ALTER TABLE events
    ADD COLUMN IF NOT EXISTS source_id BIGINT;

-- Add foreign key constraint to link events to sources
-- This ensures referential integrity and enables JOIN queries
ALTER TABLE events
    ADD CONSTRAINT fk_events_source_id
    FOREIGN KEY (source_id)
    REFERENCES sources (source_id)
    ON DELETE SET NULL;  -- Keep events even if source is deleted

-- Create index on source_id for efficient joins and source-based queries
CREATE INDEX IF NOT EXISTS idx_events_source_id ON events (source_id);

COMMENT ON COLUMN events.source_id IS
    'Foreign key to the sources table, linking this event to its source domain.
     Enables source-based filtering, trust scoring, and attribution.';

-- ==============================================================================
-- POPULATE SOURCES FROM EXISTING EVENTS (OPTIONAL)
-- ==============================================================================

-- Example query to extract domains from existing events and populate sources:
-- This is commented out as it depends on your URL format and deduplication strategy
--
-- INSERT INTO sources (domain, created_at)
-- SELECT DISTINCT
--     COALESCE(
--         SPLIT_PART(SPLIT_PART(url, '://', 2), '/', 1),
--         'unknown'
--     ) AS domain,
--     NOW()
-- FROM events
-- WHERE url IS NOT NULL
-- ON CONFLICT (domain) DO NOTHING;

-- ==============================================================================
-- FUNCTION TO REGISTER A NEW SOURCE
-- ==============================================================================

-- Function to safely add a new source with domain extraction from URL
CREATE OR REPLACE FUNCTION register_source(
    p_url TEXT,
    p_country_code VARCHAR(3) DEFAULT NULL,
    p_country_name VARCHAR(100) DEFAULT NULL,
    p_is_anonymous BOOLEAN DEFAULT FALSE
)
RETURNS BIGINT AS $$
DECLARE
    extracted_domain VARCHAR(255);
    v_source_id BIGINT;
BEGIN
    -- Extract domain from URL
    extracted_domain := COALESCE(
        SPLIT_PART(SPLIT_PART(p_url, '://', 2), '/', 1),
        'unknown'
    );

    -- Insert or get existing source
    INSERT INTO sources (domain, country_code, country_name, is_anonymous, created_at)
    VALUES (extracted_domain, p_country_code, p_country_name, p_is_anonymous, NOW())
    ON CONFLICT (domain) DO UPDATE SET
        country_code = COALESCE(EXCLUDED.country_code, sources.country_code),
        country_name = COALESCE(EXCLUDED.country_name, sources.country_name),
        is_anonymous = COALESCE(EXCLUDED.is_anonymous, sources.is_anonymous)
    RETURNING source_id INTO v_source_id;

    RETURN v_source_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION register_source IS
    'Registers a new source or returns existing source_id for the given URL.
     Automatically extracts domain from URL.
     Parameters: url, country_code (optional), country_name (optional), is_anonymous (default false).
     Returns: source_id of the registered source.';

-- ==============================================================================
-- POST-MIGRATION NOTES
-- ==============================================================================
--
-- To backfill source_id for existing events:
--   UPDATE events e
--   SET source_id = register_source(url)
--   WHERE e.source_id IS NULL AND e.url IS NOT NULL;
--
-- This should be run in batches to avoid locking:
--   UPDATE events e
--   SET source_id = register_source(url)
--   WHERE e.source_id IS NULL AND e.url IS NOT NULL
--   LIMIT 1000;
--
-- Consider adding a trusted_sources table for manual trust score overrides:
--   CREATE TABLE trusted_sources (
--       source_id BIGINT PRIMARY KEY REFERENCES sources(source_id),
--       trusted_score REAL NOT NULL CHECK (trusted_score BETWEEN 0 AND 1),
--       reason TEXT,
--       verified_by VARCHAR(100),
--       verified_at TIMESTAMPTZ DEFAULT NOW()
--   );
--
-- ==============================================================================

COMMIT;