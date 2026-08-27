# Sentinel

Geopolitical OSINT pipeline: **ingest → cluster → score → verify → visualize**.

Sentinel ingests open-source conflict events (GDELT + ACLED), detects convergence
zones where multiple event types co-occur, micro-clusters them into hotspots,
scores each hotspot's confidence, optionally generates an LLM SITREP, and serves
it all through a REST/SSE API and a Next.js dashboard.

---

## Quickstart (full stack, Docker)

The entire system runs from `docker compose` — Postgres/PostGIS, PgBouncer, Redis,
the FastAPI gateway, five pipeline workers, and the Next.js frontend.

```bash
cp sentinel.env.example sentinel.env   # first time only; then edit as needed
docker compose up -d --build
```

This starts:

| Service          | Host port | Purpose                                              |
| ---------------- | --------- | ---------------------------------------------------- |
| `frontend-next`  | **3000**  | Next.js dashboard (MapLibre + deck.gl) — **the app** |
| `api`            | **8000**  | FastAPI gateway (REST + SSE), JWT-gated              |
| `postgres`       | 5433      | PostgreSQL 15 + PostGIS                              |
| `pgbouncer`      | 6432      | Transaction-mode connection pooler                   |
| `redis`          | 6379      | Worker stream bus (`StreamBus`)                      |
| `*-worker` (×5)  | —         | ingestion · gridcell · clustering · consensus · llm  |

Open the dashboard at **http://localhost:3000** and sign in.

### Default logins

Seeded automatically on first DB init (`seed_default_users`):

| Username  | Password  | Role    |
| --------- | --------- | ------- |
| `admin`   | `admin`   | admin   |
| `analyst` | `analyst` | analyst |

> Change these before any non-local deployment. Auth is JWT (`SENTINEL_JWT_SECRET`);
> the API refuses to boot in `SENTINEL_ENV=production` while the default secret is in place.

### Verify it's up

```bash
curl -s http://localhost:8000/health                                   # {"status":"ok"}
curl -s -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin"}'                         # -> {access_token,...}
```

API routes: `/health`, `/auth/login`, `/hotspots`, `/hotspots/{id}/summary`,
`/hotspots/stream` (SSE), `/grid_cells`, `/events`, `/sources`, `/metrics`.
All data routes require an `Authorization: Bearer <token>` header.

---

## How data flows

Workers are long-running consumers chained over Redis streams:

```
ingestion-worker  ─(sentinel:ingested_events)→  gridcell-worker
  └ GDELT + ACLED → events table             └ 1°×1° convergence (2+ distinct types)
                                                 ─(sentinel:convergence_zone_detected)→  clustering-worker
                                                       └ per-cell DBSCAN → hotspots
                                                          ─→ consensus-worker (conf_score)
                                                             ─→ llm-worker (SITREP, if NIM configured)
```

Convergence fires when a grid cell holds **2+ distinct event types**. Note that all
GDELT CAMEO 14–19 codes map to the single type `military_conflict`, so convergence
requires GDELT events to co-occur with ACLED-typed events (`armed_conflict`,
`civilian_violence`, `civil_unrest`) in the same cell.

### Seeding data for a live demo

The ingestion worker fetches **live** GDELT/ACLED on its tick. If the host clock is
ahead of the latest available GDELT data, or you want deterministic demo hotspots,
seed a few convergent events dated *now* and publish them to the chain:

```bash
# 1) insert mixed-source events into the same 1° cells, dated within the DBSCAN
#    window (default 2h) — see SENTINEL_DBSCAN_WINDOW_HOURS. Each cell needs
#    >= min_samples (3) events and 2+ distinct types (mix GDELT + ACLED rows).
#    (populate events.point_geom, event_date=now(), cameo_code, source_system,
#     external_event_id, grid_cell_id = '1x1_LAT<floor>_LON<floor>')

# 2) publish the new event ids so the worker chain processes them:
docker compose exec -T api python -c "
from pipeline.streams import StreamBus
from pipeline.db import get_pooled_connection
import uuid, datetime
conn, pool = get_pooled_connection()
cur = conn.cursor(); cur.execute(\"SELECT event_id FROM events WHERE external_event_id LIKE 'seed-%'\")
ids = [r[0] for r in cur.fetchall()]; pool.return_connection(conn)
StreamBus().publish('sentinel:ingested_events',
    {'batch_id': str(uuid.uuid4()), 'event_ids': ids,
     'ts': datetime.datetime.now(datetime.timezone.utc).isoformat()})
print('published', len(ids))
"
```

Hotspots then appear at `GET /hotspots` and on the dashboard map (color-coded by
`conf_score`: green >70%, yellow 40–70%, grey <40%).

---

## Configuration

All config is env-driven via `sentinel.env` (copy from `sentinel.env.example`). Key vars:

- `PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD` — DB connection. **In compose the app
  services connect to `pgbouncer:5432` and take `PGPASSWORD` from `POSTGRES_PASSWORD`
  (default `sentinel_pass`); for host-run tools use port `6432` (PgBouncer) or `5433`
  (direct Postgres).**
- `SENTINEL_JWT_SECRET`, `SENTINEL_JWT_TTL_MIN`, `SENTINEL_ENV` — auth.
- `SENTINEL_CORS_ORIGINS` — comma-separated origins allowed to call the API
  (default `http://localhost:3000,http://127.0.0.1:3000`).
- `SENTINEL_LOOKBACK_HOURS` (24), `SENTINEL_DBSCAN_WINDOW_HOURS` (2),
  `SENTINEL_LLM_THRESHOLD` (40), `SENTINEL_POLL_INTERVAL_S` (900).
- `NVIDIA_NIM_ENDPOINT`, `NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_MODEL` — LLM SITREP step
  (skipped if absent; falls back to `OLLAMA_ENDPOINT`).
- `ACLED_EMAIL` / `ACLED_PASSWORD` — myACLED OAuth credentials; enable ACLED ingestion (GDELT-only without them).
- `ACLED_ACCESS_TOKEN` / `ACLED_REFRESH_TOKEN` — alternatives to the password: a token pasted from myACLED (24h) or a refresh token. Any one of the three enables step 2. A `403 Access denied` from the read endpoint means the account itself lacks API data access.

Frontend build args (compose): `NEXT_PUBLIC_API_BASE` (default `http://localhost:8000`),
`NEXT_PUBLIC_MAP_STYLE`. Changing these requires rebuilding `frontend-next`.

### Schema

`db/init/001_*.sql` … `db/init/0NN_*.sql` run **only on first init of an empty
Postgres volume**. For an existing volume or a managed deploy, apply migrations
explicitly:

```bash
python -m pipeline.migrate apply
```

---

## Common operations

```bash
docker compose ps                          # service status
docker compose logs -f api                 # tail the API
docker compose logs -f clustering-worker   # tail a worker
docker compose build api && docker compose up -d api   # rebuild after code changes
docker compose down                        # stop (add -v to also wipe the DB volume)
```

> The image uses `COPY . .`, so **rebuild** the relevant service after editing
> Python (`api`/workers) or frontend code — restarting alone won't pick up changes.

### Apple Silicon

`postgis/postgis:15-3.4` is amd64-only and runs under `linux/amd64` emulation.
Postgres is published on host port `5433` to avoid clashing with a local `5432`.

---

## Run the pipeline standalone (no workers)

The monolithic pipeline still works for local runs / debugging against a DB on
port `6432` (PgBouncer) or `5433` (direct):

```bash
python -m pipeline.ingestion --insert-db                          # ingest GDELT
python -m pipeline.clustering --lookback-hours 6 --run-scoring    # cluster + score
python -m pipeline.scoring                                        # scoring only
python -m pipeline.llm_verifier --threshold 40                    # LLM (needs NIM creds)
python -m pipeline.pipeline                                       # full orchestrated run + scheduler
```

### Legacy Streamlit dashboard

The original Pydeck/Streamlit dashboard remains under `frontend/app.py` and reads
the same DB directly (no API/auth):

```bash
streamlit run frontend/app.py    # http://localhost:8501
```

---

## Tests

```bash
pytest tests/                              # all
pytest tests/test_ingestion.py -q          # single file
pytest tests/test_dashboard_refresh.py -v  # verbose
cd frontend-next && npm test               # frontend (vitest)
```

---

## Spec

`specs.md` is the authoritative design doc. Key invariants:
**FR-WM-CONVERGENCE** (cells fire on 2+ distinct event types),
**FR-7/8/9** (`conf_score = 0.6·source_density + 0.4·geopolitical_diversity`),
**FR-11/12** (LLM citations validated — every sentence ends with `[N]`, on either side of the full stop).
