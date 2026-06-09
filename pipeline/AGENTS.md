# DOX — pipeline/

## Purpose

Core OSINT processing: GDELT + ACLED ingestion, grid-cell convergence, DBSCAN clustering, confidence scoring, and LLM verification. Runs as a scheduled pipeline via APScheduler.

## Ownership

All files in `pipeline/` except `workers/` (see child doc).

## Local Contracts

- **Connection pool**: always call `get_pooled_connection()` from `pool.py`; always return with `pool.return_connection(conn)` in a `finally` block — never open raw `psycopg2` connections
- **ACLED**: rate-limit to 1 req/s; cache responses in Redis with TTL = `SENTINEL_ACLED_POLL_HOURS × 3600`; fall back to GDELT-only on failure
- **FR-WM-CONVERGENCE**: `bin_to_grid` fires when **2+ distinct CAMEO event types** co-occur in a 1°×1° cell within 24 h — not DBSCAN density
- **conf_score**: `0.6 × source_density + 0.4 × geopolitical_diversity`; `source_density = tanh(sum(trust_weights)/10)` — must match specs.md FR-7/FR-8/FR-9 exactly
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
