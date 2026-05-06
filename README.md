# Sentinel (Phase 1 / Sprint 1)

## Setup

```bash
python -m pip install -r requirements.txt
cp sentinel.env sentinel.env.local  # optional local copy
docker compose up -d
```

On Apple Silicon Macs, this project runs PostGIS via `linux/amd64` emulation because `postgis/postgis:15-3.4` does not provide an `arm64` image.
The container is published on host port `5433` to avoid conflicts with any local PostgreSQL already using `5432`.
Schema migrations are loaded from `db/init/*.sql` on first container initialization (including Sprint 2 `hotspots` and `event_hotspot` tables).

## Run GDELT ingestion

```bash
python -m pipeline.ingestion --output-csv military_events.csv
```

Insert directly into PostgreSQL:

```bash
python -m pipeline.ingestion --insert-db
```

## Run clustering + scoring

```bash
python -m pipeline.clustering --lookback-hours 6 --run-scoring
```

Run scoring only:

```bash
python -m pipeline.scoring
```

Run LLM verification (requires `NVIDIA_NIM_ENDPOINT` and `NVIDIA_NIM_API_KEY` in environment):

```bash
python -m pipeline.llm_verifier --threshold 40
```

## Run Dashboard

Launch the Streamlit dashboard to visualize hotspots:

```bash
streamlit run frontend/app.py
```

The dashboard will be available at `http://localhost:8501`

### Dashboard Features

**Auto-Refresh:** The dashboard automatically fetches fresh hotspots every 15 minutes. This prevents stale data while avoiding excessive database queries.

**Manual Refresh:** Click the "🔄 Refresh Now" button in the sidebar to immediately fetch the latest hotspots.

**Last Refresh Display:** Shows when hotspots were last updated (displays "Just now", relative time, or timestamp).

**Map Visualization:** Interactive Pydeck map showing hotspot locations color-coded by confidence level:
- **Green**: High confidence (>70%)
- **Yellow**: Medium confidence (40-70%)
- **Grey**: Low confidence (<40%)

**SITREP Details:** Select a hotspot to view detailed Situation Report with:
- Conflict classification
- Confidence score and category
- Geographic location
- Number of supporting events
- Time window
- LLM-generated summary

**Statistics Dashboard:** Footer displays aggregated metrics:
- Total number of hotspots
- Count of high-confidence hotspots
- Total number of supporting events

### Environment Variables

The dashboard requires database connectivity. Ensure these environment variables are set:

```bash
PGHOST=localhost
PGPORT=5433
PGUSER=sentinel_user
PGPASSWORD=sentinel_password
PGDATABASE=sentinel_db
```

Or set them in your `sentinel.env` file before running the dashboard.

## Tests

```bash
pytest -q tests/test_ingestion.py
```

Run all tests:

```bash
pytest tests/
```

Run specific test file:

```bash
pytest tests/test_dashboard_refresh.py -v
pytest tests/test_e2e_dashboard.py -v
```

