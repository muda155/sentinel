-- Migration 009: Fix llm_summaries.sources_cited column type from text to JSONB
-- Per spec, sources_cited should store a JSON array with default empty array.

-- If the column already contains text data, convert it to JSONB.
-- The USING clause handles the type cast.
ALTER TABLE llm_summaries
    ALTER COLUMN sources_cited TYPE jsonb USING sources_cited::jsonb;

ALTER TABLE llm_summaries
    ALTER COLUMN sources_cited SET DEFAULT '[]'::jsonb;
