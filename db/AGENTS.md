# DOX — db/

## Purpose

PostgreSQL 15 + PostGIS schema: migration files applied in numeric order on first container init, plus Docker config.

## Ownership

All files in `db/`.

## Local Contracts

- Migrations in `db/init/` are applied once in numeric order — never modify an already-applied migration; always add a new numbered file
- Current highest migration: `023_claim_origin_domains.sql` — adds `claims.origin_domains TEXT[]` (M9, FR-28): the domains that *asserted* each claim, so a client recomputation cannot let a source corroborate itself. `consensus()` in `pipeline/consistency.py` persists the resolved domains it already computes. **NULL means "written before migration 023" -> unverifiable**, never "no origin domains" — treating NULL as an empty set would count every domain as independent and inflate corroboration. Windowed consumers must report NULL-origin claims as `unverifiable` and force counts-only mode
- Migration `022_relevance_gate_stats.sql` — nullable `hotspots.gated_pairs` and `hotspots.vacuous_claims_dropped` for FR-26 tuning and evaluation. **NULL means the gate did not run** (pre-M8 row, or `SENTINEL_RELEVANCE_ENABLED=false`); `0` means it ran and suppressed nothing. The gate-effect analysis partitions on `gated_pairs IS NULL`, so never backfill these to 0
- Key tables: `events` (partitioned by `event_date`), `hotspots`, `grid_cells`, `sources` (with `trust_tier`), `event_hotspot`, `claims`, `claim_evidence`
- `claim_evidence.event_id` has no FK — events is partitioned; rows cascade via `claims → hotspots`
- `sources.trust_tier` feeds the scoring formula — changes to trust tiers require a scoring review

## Work Guidance

- Use PostGIS geometry types for all spatial columns — do not store lat/lon as plain floats without a geometry column
- Partition `events` by `event_date`; queries that don't filter by date will scan all partitions
- Test migrations with `pytest tests/test_migrate.py` before merging

## Verification

```bash
pytest tests/test_migrate.py tests/test_data_integrity.py -q
```
