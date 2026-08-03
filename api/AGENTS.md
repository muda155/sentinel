# DOX — api/

## Purpose

FastAPI REST + SSE layer: hotspot and event endpoints, rate limiting, Prometheus metrics, and server-sent event streams.

## Ownership

All files in `api/`, including `api/routes/`.

## Local Contracts

- All SQL lives in `api/queries.py` — no inline SQL in route handlers or `sse.py`
- Rate limiting enforced via `ratelimit.py` — do not bypass for any endpoint
- SSE streams are in `api/sse.py` and `api/routes/stream.py`; keep them separate from request/response routes
- SSE generators run on the shared asyncio event loop: every synchronous blocking call inside them (Redis `StreamBus.read`/`ack` with `block=`, pooled DB reads like `_enrich`) MUST be wrapped in `asyncio.to_thread`. A blocking call left on the loop starves all concurrent REST requests — a live stream once hung `/hotspots` for minutes. Covered by `test_sse_read_does_not_block_event_loop`.
- SSE frames MUST serialize through `json.dumps(..., default=_json_default)`. `_enrich` returns a raw `hotspots` row whose `end_window`/`created_at` are `timestamp with time zone` → `datetime`, which plain `json.dumps` cannot encode. That exception escapes mid-yield, so the chunked response ends without its final chunk (browser: `ERR_INCOMPLETE_CHUNKED_ENCODING`) and the `bus.ack` on the following line never runs. Because `StreamBus.read` uses `>` (new entries only), the unacked message is never retried — it strands in the group's pending list while the next emitted event crashes the next connection identically (observed: 218 crashes in 40 min, 18k stranded pending messages, `hotspot_created` never reaching any client). ISO-8601 output matches the `Hotspot` response_model on `GET /hotspots`. Covered by `test_sse_hotspot_created_frame_is_json_serializable`.
- Pydantic schemas in `api/schemas.py` are the API contract — changing field names is a breaking change
- Metrics exported via `api/metrics.py`; add new counters/gauges there, not inline
- `GET /hotspots` and `GET /grid_cells` accept `max_age_hours` (default 720 = 30 days); rows whose `end_window` (hotspots) / `updated_at` (grid_cells) is older are excluded. This is the server-side guard against stale hotspots accumulating in the response window — do not remove it. `max_age_hours=None` in `queries.py` disables the cap (used only by internal callers/tests).
- `fetch_hotspot_events` excludes `is_noise` links and must stay in lockstep (filter + ORDER BY + duplicate collapse) with `LLMRepository.fetch_hotspot_articles` and `pipeline.consistency.fetch_hotspot_evidence` — FR-16 citation numbering depends on all three agreeing row-for-row. The collapse itself is `pipeline.citations.collapse_duplicate_urls`; never reimplement it locally.
- `fetch_hotspot_events` rows carry `duplicate_count` (≥ 1) — how many `events` rows shared that URL before the collapse. GDELT emits one row per extracted actor pair, so an uncollapsed list cited one article under several numbers and read as independent corroboration.
- `fetch_hotspot_events` exposes the FR-21 severity columns (`goldstein_scale`, `avg_tone`, `num_sources`, `fatalities`) as nullable passthroughs. They are additive SELECT columns only — the `ORDER BY` and `is_noise` filter must never change, or `citation_index` renumbers and SITREP `[N]` markers desync.
- `fetch_hotspots`, `fetch_hotspot_by_id`, and the search payloads (`_HOTSPOT_SELECT` and the FTS `SearchEvent.hotspot` dict) all carry `start_window`, `end_window`, `created_at`, and `consistency_score` so the detail panel shows hotspot lifespan and consistency whichever way the hotspot was opened; SSE `hotspot_created` frames carry them through `_json_default` as ISO-8601.
- The `/search` events group deduplicates on `(url, hotspot_id)` via `row_number()`, keeping the most recent row and reporting `report_count`. The `LIMIT 10` sits outside the dedupe subquery — limiting first would return fewer than ten distinct articles. Partitioning on `url` alone would be wrong: the same article under two hotspots is two distinct destinations.
- `fetch_hotspot_claims` recomputes `citation_index` from `fetch_hotspot_events` — the lockstep contract now covers claims too
- `GET /hotspots/{id}/claims` follows the standard Bearer + rate-limit pattern (FR-24)

## Work Guidance

- New endpoints go in `api/routes/` as separate files; register them in `api/app.py`
- Use `api/queries.py` for all DB reads; the API layer must not write to the DB
- Test all new endpoints with corresponding tests in `tests/test_api_*.py`

## Verification

```bash
pytest tests/test_api_events.py tests/test_api_hotspots.py tests/test_api_sse.py tests/test_ratelimit.py tests/test_metrics.py -q
ruff check api/
```
