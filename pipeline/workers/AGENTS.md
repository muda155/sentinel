# DOX — pipeline/workers/

## Purpose

Worker classes for the microservice-style pipeline steps: base lifecycle, ingestion, grid-cell convergence, clustering, consensus scoring, and LLM verification. Each worker is independently startable and commits its own DML before returning connections to the pool.

## Ownership

All files in `pipeline/workers/`.

## Local Contracts

- Every worker inherits from `base.py` — do not bypass the base lifecycle hooks
- Workers must commit DML before calling `pool.return_connection(conn)` — a connection returned mid-transaction leaves the pool dirty
- Workers are stateless between runs; durable state lives in the DB only
- `ingestion_worker.tick()` calls `retention.ensure_partitions(conn)` before inserting so a month-rollover or back-dated GDELT row can't abort the whole batch with "no partition of relation events found for row" (the monolith `pipeline.py` provisions partitions, but the worker deployment must do it itself). `ensure_partitions` is forward-looking (current + N future months) — it does NOT cover rows dated before the current month; such back-dated rows still need their past partition created manually

## Work Guidance

- Add new pipeline steps as new worker files, not by extending existing workers
- Keep worker `run()` methods thin — delegate logic to the parent pipeline module (e.g., `clustering.py`, `scoring.py`)

## Verification

```bash
pytest tests/test_worker_base.py tests/test_workers_e2e.py -q
ruff check pipeline/workers/
```
