# DOX — pipeline/

## Purpose

Core OSINT processing: GDELT + ACLED ingestion, grid-cell convergence, DBSCAN clustering, confidence scoring, and LLM verification. Runs as a scheduled pipeline via APScheduler.

## Ownership

All files in `pipeline/` except `workers/` (see child doc).

## Local Contracts

- **Connection pool**: always call `get_pooled_connection()` from `pool.py`; always return with `pool.return_connection(conn)` in a `finally` block — never open raw `psycopg2` connections
- **ACLED**: requires `ACLED_EMAIL`/`ACLED_PASSWORD` (myACLED OAuth password grant; Bearer token cached 24h in Redis/in-memory, ingestion skipped if unset); rate-limit to 1 req/s; cache responses in Redis with TTL = `SENTINEL_ACLED_POLL_HOURS × 3600`; fall back to GDELT-only on failure
- **FR-WM-CONVERGENCE**: a 1°×1° cell is an active zone when `convergence_score ≥ 1` (≥1 classified event in 24 h) — not DBSCAN density. 2+ distinct types raise the alert level but aren't required to activate, so GDELT-only feeds still produce hotspots. `classify_event_type` reads the **2-digit CAMEO root** of GDELT's 3–4 digit `EventCode` (`_cameo_root`); roots 14–19 → `military_conflict`. `_load_cell_events` floors the DBSCAN window lower bound to start-of-UTC-day (`_dbscan_window_start`) so day-granular GDELT events stay in window all day. `save_clusters` diffs against existing cell hotspots by non-noise event membership — unchanged clusters keep their `hotspot_id` (and `llm_summaries` row); only stale hotspots are deleted. `_load_cell_events` also drops rows with `geo_precision < SENTINEL_MIN_GEO_PRECISION` (default 2; NULL fails open) so GDELT country-centroid mention piles never enter DBSCAN; `load_events_for_convergence` deliberately keeps them (FR-WM bins all events).
- **conf_score**: `0.7 × source_density + 0.3 × geopolitical_diversity`; `source_density = tanh(sum(trust_weights)/3)` (env-configurable via `SENTINEL_CONF_W_DENSITY`, `SENTINEL_CONF_W_DIVERSITY`, `SENTINEL_CONF_DENSITY_DIVISOR`) — must match specs.md FR-7/FR-8/FR-9 exactly. Diversity reads `sources.country_code` over unique domains.
- **source_country.py**: `resolve_country(url_or_domain)` maps domains to ISO-A3 via curated outlets + ccTLD fallback; `backfill_source_countries(conn)` one-time backfill with `python -m pipeline.source_country --backfill` CLI.
- **LLM**: validate every sentence ends with `[N]` via `validate_citations()` (regex `\[\d+\]` accepts a **single** index only — `build_prompt` must instruct the model to emit one index per sentence and never `[1, 2]`, or rich multi-source hotspots get permanently rejected). Fall back to Ollama when NIM is unavailable. Parse model output with `_extract_json()` (tolerates ```` ```json ```` fences/prose — never bare `json.loads`). NIM request params are env-configurable: `SENTINEL_LLM_TIMEOUT_S` (default 60 — must exceed 70B generation time or every call times out), `SENTINEL_LLM_MAX_TOKENS` (default 500), `SENTINEL_LLM_TEMPERATURE` (default 0). Note: `sentinel.env` points `OLLAMA_ENDPOINT` at `host.docker.internal:11434` (localhost inside a container is the container itself); the fallback still requires Ollama running on the host. A failed NIM+Ollama call is acked by the LLM worker (`llm_failed_total` metric) and retried on the next tick's re-emission — never left pending for the stale-claim sweep. LLM generation is skipped when `llm_summaries` already has a row for the hotspot (`candidate_hotspots` NOT EXISTS filter + `LLMWorker.summary_exists` guard); with stable hotspot identity, an existing summary means membership is unchanged.
- **Scheduler**: full cycle period controlled by `SENTINEL_POLL_INTERVAL_S` (default 900 s)
- **Hotspot TTL**: `retention.delete_stale_hotspots(conn)` deletes hotspots whose `end_window` is older than `SENTINEL_HOTSPOT_TTL_HOURS` (default 720 = 30 days); `event_hotspot` links cascade. Called every `IngestionWorker.tick()` (worker deployment) and in `pipeline.py` Step 0 (monolith). Without it, aged-out grid cells are never re-clustered so their hotspots render forever.

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
