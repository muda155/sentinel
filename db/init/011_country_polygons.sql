-- Migration: 011_country_polygons.sql
-- Purpose: Country boundary polygons for PostGIS reverse-geocoding (M1, Sprint 6).
--   Populated from Natural Earth admin-0 by scripts/load_country_polygons.py.
-- Date: 2026-06-07

CREATE TABLE IF NOT EXISTS country_polygons (
    iso_a3     CHAR(3) PRIMARY KEY,
    name       TEXT NOT NULL,
    geom       GEOMETRY(MultiPolygon, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_country_polygons_geom
    ON country_polygons USING GIST (geom);

COMMENT ON TABLE country_polygons IS
    'Natural Earth admin-0 country boundaries for ST_Contains reverse-geocoding.
     iso_a3 is the ISO 3166-1 alpha-3 code used in sources.country_code.';