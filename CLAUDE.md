# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## DOX work contract

@AGENTS.md

The root AGENTS.md above is imported every session and is binding. Child AGENTS.md files (`pipeline/`, `frontend/`, `frontend-next/`, `api/`, `tests/`, `db/`) are NOT imported — read the DOX chain for every path you touch before editing, per the Read Before Editing rules.

## Commands

```bash
# Infrastructure
docker compose up -d          # Start PostgreSQL+PostGIS (port 5433) + PgBouncer (port 6432)

# Pipeline
python -m pipeline.ingestion --insert-db          # Ingest GDELT events into DB
python -m pipeline.clustering --lookback-hours 6 --run-scoring  # Grid convergence + DBSCAN + scoring
python -m pipeline.scoring                         # Confidence scoring only
python -m pipeline.llm_verifier --threshold 40    # LLM verification (requires NIM credentials)
python -m pipeline.consistency --hotspot-id N     # Consistency engine (FR-22)
python -m pipeline.pipeline                        # Full orchestrated pipeline (runs once + starts scheduler)

# Dashboard
streamlit run frontend/app.py  # http://localhost:8501

# Tests
pytest tests/                              # All tests
pytest tests/test_ingestion.py -q         # Single file
pytest tests/test_dashboard_refresh.py -v # Verbose single file
```

## Architecture

Sentinel is a geopolitical OSINT pipeline: ingest → cluster → score → verify → visualize.

### Pipeline Flow (6 steps, `pipeline/pipeline.py`)
1. **GDELT Ingestion** (`pipeline/ingestion.py`) — fetches GDELT 2.0 CSV, filters CAMEO codes 14–19 (military events), inserts into `events` table
2. **ACLED Ingestion** (`pipeline/ingestion.py:ACLEDIngestor`) — fetches ACLED API events (academic tier, 1 req/s), normalizes to the `events` schema with `source_system='ACLED'`, caches responses in Redis (TTL = `SENTINEL_ACLED_POLL_HOURS × 3600`); falls back to GDELT-only data on API/Redis failure
3. **Grid-cell convergence** (`pipeline/clustering.py:bin_to_grid`) — bins events into 1°×1° cells; a cell becomes an active zone when `convergence_score ≥ 1` (≥1 classified event in 24h). 2+ distinct event types raise the alert level but aren't required to activate, so GDELT-only feeds still produce hotspots (FR-WM-CONVERGENCE)
4. **DBSCAN clustering** (`pipeline/clustering.py:run_clustering_pipeline`) — per-cell micro-clustering using haversine distance; produces precise hotspots stored in `hotspots` table
5. **Consensus Confidence Scoring** (`pipeline/scoring.py`) — computes `conf_score` (0–100) per hotspot: `0.7 × source_density + 0.3 × geopolitical_diversity`, where `source_density = tanh(Σ trust over unique domains / 3)` (env-configurable via `SENTINEL_CONF_W_DENSITY`, `SENTINEL_CONF_W_DIVERSITY`, `SENTINEL_CONF_DENSITY_DIVISOR`). Geopolitical diversity reads `sources.country_code` over unique domains.
6. **LLM Verification + Consistency** (`pipeline/llm_verifier.py`, `pipeline/consistency.py`) — two-phase shared entry point `generate_sitrep`: 6a Consistency Engine (claim extraction via NIM, local NLI agreement, trust-weighted consensus, `consistency_score`), 6b SITREP from verified claims (headline fallback if 6a produced nothing)

The scheduler (`APScheduler`) runs the full cycle every `SENTINEL_POLL_INTERVAL_S` seconds (default 900).

### Database
- PostgreSQL 15 + PostGIS via Docker; PgBouncer sits in front on port 6432
- Connection pool: `SentinelConnectionPool` singleton (`pipeline/pool.py`) — always use `get_pooled_connection()` and return with `pool.return_connection(conn)` in a `finally` block
- Schema migrations: `db/init/001_*.sql` through `db/init/020_*.sql` — applied in order on first container init
- Key tables: `events` (partitioned by `event_date`), `hotspots`, `grid_cells`, `sources` (with `trust_tier`), `event_hotspot`

### Scoring details
- `conf_score` = Sentinel's original research contribution (not in World Monitor)
- `convergence_score` = World Monitor formula: `min(100, event_types × 25 + min(25, total_events × 2))`
- Source trust tiers stored in `sources.trust_tier`; weights feed `source_density`

### Frontend (`frontend/app.py`)
Streamlit dashboard with Pydeck map. Hotspots color-coded: green (>70%), yellow (40–70%), grey (<40%). Auto-refreshes every 15 min via APScheduler; manual refresh button available. `frontend/refresh_utils.py` handles refresh timing logic.

### Environment
All config via env vars in `sentinel.env` (copy to override locally). Key vars:
- `PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD` — DB connection (port 6432 = PgBouncer)
- `NVIDIA_NIM_ENDPOINT`, `NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_MODEL` — LLM step (step 6 skipped if absent)
- `OLLAMA_ENDPOINT` — fallback LLM (default `http://localhost:11434`)
- `ACLED_EMAIL`/`ACLED_PASSWORD` — myACLED OAuth credentials (step 2 skipped if absent)
- `SENTINEL_LOOKBACK_HOURS` (default 24), `SENTINEL_DBSCAN_WINDOW_HOURS` (default 2), `SENTINEL_LLM_THRESHOLD` (default 40)
- `SENTINEL_CONF_W_DENSITY` (default 0.7), `SENTINEL_CONF_W_DIVERSITY` (default 0.3), `SENTINEL_CONF_DENSITY_DIVISOR` (default 3) — conf_score recalibration (FR-7/FR-8/FR-9)
- `SENTINEL_NLI_MODEL` (default `cross-encoder/nli-deberta-v3-base`), `SENTINEL_NLI_MIN_PROB` (default 0.6), `SENTINEL_CONSISTENCY_DISPUTE_RATIO` (default 0.5), `SENTINEL_CONSISTENCY_MAX_CLAIMS` (default 8), `SENTINEL_CONSISTENCY_MAX_DOMAINS` (default 20) — M6 Consistency Engine (FR-22)

## Spec compliance

`specs.md` is the authoritative design doc. When implementing new features, check it first — key FRs are listed in the imported AGENTS.md Spec Compliance section.
