# DOX — pipeline/

## Purpose

Core OSINT processing: GDELT + ACLED ingestion, grid-cell convergence, DBSCAN clustering, confidence scoring, and LLM verification. Runs as a scheduled pipeline via APScheduler.

## Ownership

All files in `pipeline/` except `workers/` (see child doc).

## Local Contracts

- **Connection pool**: always call `get_pooled_connection()` from `pool.py`; always return with `pool.return_connection(conn)` in a `finally` block — never open raw `psycopg2` connections
- **ACLED**: requires `ACLED_EMAIL`/`ACLED_PASSWORD` (myACLED OAuth password grant; Bearer token cached 24h in Redis/in-memory, ingestion skipped if unset); rate-limit to 1 req/s; cache responses in Redis with TTL = `SENTINEL_ACLED_POLL_HOURS × 3600`; fall back to GDELT-only on failure
- **FR-WM-CONVERGENCE**: a 1°×1° cell is an active zone when `convergence_score ≥ 1` (≥1 classified event in 24 h) — not DBSCAN density. 2+ distinct types raise the alert level but aren't required to activate, so GDELT-only feeds still produce hotspots. `classify_event_type` reads the **2-digit CAMEO root** of GDELT's 3–4 digit `EventCode` (`_cameo_root`); roots 14–19 → `military_conflict`. `_load_cell_events` floors the DBSCAN window lower bound to start-of-UTC-day (`_dbscan_window_start`) so day-granular GDELT events stay in window all day.
- **conf_score**: `0.7 × source_density + 0.3 × geopolitical_diversity`; `source_density = tanh(sum(trust_weights)/3)` (env-configurable via `SENTINEL_CONF_W_DENSITY`, `SENTINEL_CONF_W_DIVERSITY`, `SENTINEL_CONF_DENSITY_DIVISOR`) — must match specs.md FR-7/FR-8/FR-9 exactly. Diversity reads `sources.country_code` over unique domains.
- **source_country.py**: `resolve_country(url_or_domain)` maps domains to ISO-A3 via curated outlets + ccTLD fallback; `backfill_source_countries(conn)` one-time backfill with `python -m pipeline.source_country --backfill` CLI.
- **LLM**: validate every sentence ends with `[N]` via `validate_citations()`; fall back to Ollama when NIM is unavailable
- **Scheduler**: full cycle period controlled by `SENTINEL_POLL_INTERVAL_S` (default 900 s)

## Work Guidance

- Filter GDELT to CAMEO codes 14–19 (military events) only
- `scoring.py` owns `conf_score`; `clustering.py` owns `convergence_score` — keep them separate
- `convergence_score = min(100, event_types × 25 + min(25, total_events × 2))` — World Monitor formula, not Sentinel's contribution
- Do not add retry loops without backoff; ACLED's academic tier enforces rate limits

## Verification

```bash
pytest tests/test_ingestion.py tests/test_clustering.py tests/test_scoring.py tests/test_llm_verifier.py -q
ruff check pipeline/
```

## Child DOX Index

- [pipeline/workers/AGENTS.md](workers/AGENTS.md) — worker base class, cluster worker, ACLED worker
