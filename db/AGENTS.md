# DOX — db/

## Purpose

PostgreSQL 15 + PostGIS schema: migration files applied in numeric order on first container init, plus Docker config.

## Ownership

All files in `db/`.

## Local Contracts

- Migrations in `db/init/` are applied once in numeric order — never modify an already-applied migration; always add a new numbered file
- Current highest migration: `019_events_geo_precision.sql` — next must be `020_*.sql`
- Key tables: `events` (partitioned by `event_date`), `hotspots`, `grid_cells`, `sources` (with `trust_tier`), `event_hotspot`
- `sources.trust_tier` feeds the scoring formula — changes to trust tiers require a scoring review

## Work Guidance

- Use PostGIS geometry types for all spatial columns — do not store lat/lon as plain floats without a geometry column
- Partition `events` by `event_date`; queries that don't filter by date will scan all partitions
- Test migrations with `pytest tests/test_migrate.py` before merging

## Verification

```bash
pytest tests/test_migrate.py tests/test_data_integrity.py -q
```
