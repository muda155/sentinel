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
- Pydantic schemas in `api/schemas.py` are the API contract — changing field names is a breaking change
- Metrics exported via `api/metrics.py`; add new counters/gauges there, not inline

## Work Guidance

- New endpoints go in `api/routes/` as separate files; register them in `api/app.py`
- Use `api/queries.py` for all DB reads; the API layer must not write to the DB
- Test all new endpoints with corresponding tests in `tests/test_api_*.py`

## Verification

```bash
pytest tests/test_api_events.py tests/test_api_hotspots.py tests/test_api_sse.py tests/test_ratelimit.py tests/test_metrics.py -q
ruff check api/
```
