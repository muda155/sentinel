# Sentinel (Phase 1 / Sprint 1)

## Setup

```bash
python -m pip install -r requirements.txt
cp sentinel.env sentinel.env.local  # optional local copy
docker compose up -d
```

On Apple Silicon Macs, this project runs PostGIS via `linux/amd64` emulation because `postgis/postgis:15-3.4` does not provide an `arm64` image.
The container is published on host port `5433` to avoid conflicts with any local PostgreSQL already using `5432`.

## Run GDELT ingestion

```bash
python -m pipeline.ingestion --output-csv military_events.csv
```

Insert directly into PostgreSQL:

```bash
python -m pipeline.ingestion --insert-db
```

## Tests

```bash
pytest -q tests/test_ingestion.py
```
