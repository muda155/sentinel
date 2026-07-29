# DOX — tests/

## Purpose

pytest suite: unit and integration tests for every pipeline module, API layer, dashboard, and worker.

## Ownership

All files in `tests/`.

## Local Contracts

- Integration tests hit a real database — do not mock the DB layer (past mock/prod divergence caused silent failures)
- Seed helpers live in `tests/helpers_seed.py` — use them rather than duplicating fixture logic
- `tests/conftest.py` owns all shared fixtures; add new fixtures there, not in individual test files
- Test files are named `test_<module>.py` matching their target module

## Work Guidance

- Every new pipeline module or API endpoint must have a corresponding `test_*.py` file
- Fake LLM/NLI callables are injected via function parameters (never `unittest.mock.patch` on DB); `SENTINEL_NLI_TEST=1` opts into real-model NLI tests
- E2E tests (`test_e2e_*.py`) may be slow; mark them with `@pytest.mark.slow` if they exceed 5 s
- `tests/conftest.py` forces `SENTINEL_GKG_ENABLED=false` and `SENTINEL_RELEVANCE_ENABLED=false` unless the test carries `@pytest.mark.gkg` / `@pytest.mark.relevance`. Register any new opt-in marker in `pytest.ini` — unregistered markers silently disable nothing.
- Fake NLI judges must recognise the planted premise by full equality with `eval.consistency.inject.contradiction_premise(hypothesis)`, never by a prefix or sentinel string. A fake keyed on a marker the real model never sees passed for months while the harness measured noise.
- Any test that wipes whole tables (`DELETE FROM events/hotspots/grid_cells/event_hotspot`, `TRUNCATE`, `DROP` of shared tables) MUST carry `@pytest.mark.destructive`. `pytest.ini` sets `addopts = -m "not destructive"`, so these are deselected by default and can never clobber a real DB. Opt in explicitly with `pytest -m destructive` against a throwaway `SENTINEL_TEST_DB`.
- Do not use `unittest.mock.patch` on DB calls — use real DB transactions that roll back via fixture teardown

## Verification

```bash
pytest tests/ -q
ruff check tests/
```
