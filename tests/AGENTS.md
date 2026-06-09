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
- E2E tests (`test_e2e_*.py`) may be slow; mark them with `@pytest.mark.slow` if they exceed 5 s
- Do not use `unittest.mock.patch` on DB calls — use real DB transactions that roll back via fixture teardown

## Verification

```bash
pytest tests/ -q
ruff check tests/
```
