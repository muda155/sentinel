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

## Tests

```bash
pytest -q tests/test_ingestion.py
```
