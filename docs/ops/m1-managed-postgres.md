# M1 Ops Runbook — Managed PostgreSQL + PgBouncer

## Provision
1. Create a managed PostgreSQL 15 instance with the PostGIS extension available.
2. Set PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD in the secrets manager (NFR-5);
   never commit `sentinel.env`.
3. `CREATE EXTENSION IF NOT EXISTS postgis;`

## Apply schema
- Fresh instance: `python -m pipeline.migrate apply` (applies 001-011 in order).
- Instance already initialised by docker-entrypoint-initdb.d:
  `python -m pipeline.migrate baseline 9 && python -m pipeline.migrate apply`.
- Verify: `python -m pipeline.migrate status` shows Pending: [].

## Load reference data
- `python scripts/load_country_polygons.py <natural-earth-admin0.geojson>`

## PgBouncer
- Mode: transaction (already set in docker-compose; mirror on managed PgBouncer).
- Tune `MAX_CLIENT_CONN` (start 100) and `DEFAULT_POOL_SIZE` (start 20) to the
  instance's `max_connections`.
- App connects via PgBouncer port (PGPORT=6432). The app-side
  SentinelConnectionPool (pipeline/pool.py) sits in front of that.

## Verify (exit criteria)
- Migration runner: clean apply + no-op re-run.
- Partitions: current + next 3 months exist; expired partitions are DROPped
  (check logs from pipeline.retention.apply_retention).
- Concurrency: 100 simultaneous connections succeed through PgBouncer.
- NFR-1: one full pipeline batch completes in < 5 min on reference hardware.