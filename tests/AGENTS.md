# DOX — tests/

## Purpose

pytest suite: unit and integration tests for every pipeline module, API layer, dashboard, and worker.

## Ownership

All files in `tests/`.

## Local Contracts

- Integration tests hit a real database — do not mock the DB layer (past mock/prod divergence caused silent failures)
- Seed helpers live in `tests/helpers_seed.py` — use them rather than duplicating fixture logic
- `seed_demo_events` **commits** (so worker-driven tests reading through `get_pooled_connection()` on a separate connection can see the rows), and its `ON CONFLICT (source_system, external_event_id, event_date)` never fires because each insert takes a fresh `NOW()`. Its rows therefore outlive the `live_conn` rollback and accumulate across runs. Never assert an exact row count against a query keyed on its `external_event_id`s, and never treat its URLs as unique — every accumulated copy of `'9001'` reuses `https://seed/9001`, which silently inflates any duplicate-URL or per-domain assertion. Tests needing an exact shape must seed their own rows; `live_conn` rolls back, so self-seeded rows leave nothing behind.
- Never hardcode a literal `event_date` in a fixture. Migration 010 provisions partitions only through the current month on a fresh DB, so a past literal passes on a dev DB (which has accumulated partitions) and fails CI with `no partition of relation "events" found for row` the moment the clock rolls into a new month. Use `NOW()`/`date_trunc('month', now())` in SQL, or `tests.helpers_seed.current_month_start()` for Python fixtures (GDELT `SQLDATE`, ACLED `event_date`)
- `tests/conftest.py` owns all shared fixtures; add new fixtures there, not in individual test files
- `tests/fixtures/claim_value_parity.json` is read by **both** `tests/test_consistency_parity.py` and `frontend-next/__tests__/window-consistency.test.ts`. It is the only mechanism binding `pipeline/consistency.py:claim_value` to its TypeScript port; regenerate with `python -m tests.test_consistency_parity --regenerate` after a deliberate FR-22(d) change, and never hand-edit it to make a failing port pass — that failure is the alarm working.
- `conftest._reset_rate_limit_buckets` (autouse) replaces `api.ratelimit._bucket`, `_auth_bucket`, `_report_bucket` and `_translate_bucket` for every test. Those are module singletons keyed on client IP, and every `TestClient` request presents the same key, so without the reset one budget is shared by the whole session. The auth bucket is 10 tokens and tokens refill at only 1 per 6s: the suite's 11th `/auth/login` hands a 429 to whatever unrelated test happens to make it, and because refill is wall-clock the loser changes with runner speed — a fast CI box fails where a slow dev machine passes. Never assert against these buckets' cross-test state, and never "fix" a spurious 429 by reordering tests or trimming logins; the budget is not a shared resource tests must ration.
- Test files are named `test_<module>.py` matching their target module. FR-30 is covered by `tests/test_translate.py` (pure pipeline helpers, no network) and `tests/test_api_translate.py` (endpoint against a dead Redis and stubbed Google calls, so no key or live API is needed); the frontend port lives in `frontend-next/__tests__/translation.test.ts`. FR-31 transport is covered by `tests/test_llm_providers.py`: every `requests.post` is mocked, the auth (401/402/403) and 400 tests assert **call counts** (`post.call_count == 1`), not just the exception type, because a test that only checks the exception cannot distinguish "fell through after one attempt" from "fell through after three" — the same trap PR #31 recorded. The env autouse fixture clears every provider key so a developer's real `sentinel.env` cannot change which providers a test sees.
- **Two DSN sources for live tests:** the `live_conn` fixture uses `SENTINEL_TEST_DB`, but worker-driven tests (`IngestionWorker().tick()` → `get_pooled_connection`) read the pool env vars (`PGHOST`/`PGPORT`/`PGDATABASE`/`PGUSER`/`PGPASSWORD`). Point BOTH at the same throwaway DB when running the suite — with only `SENTINEL_TEST_DB` set, the pool defaults to the dev stack (`PGDATABASE=sentinel` via pgbouncer 6432) and `tick()` mutates live data.
- Tests that delete real admin rows (`test_cannot_delete_the_last_admin`, `test_last_admin_guard_holds_under_concurrent_deletes`) MUST snapshot and restore the admins they remove via `_snapshot_admins`/`_restore_admins` in `test_api_users.py`. A last-admin test that deletes the seeded `admin` and never restores it locks everyone out of the user-management screen with no recovery short of a psql session (the seeded login is what incident 2 in the PR #31 follow-up destroyed). The restore re-inserts the original `password_hash` so credentials keep working. The A1 concurrency test also reduces the admin set to exactly two rows mid-test, so both tests depend on the restore.
- When a test claims to cover a specific branch, prove the branch executes — three tests in PR #31 looked green while the code path they were written for never ran. `TestClient` serializes every request through one portal, so a "concurrent" scenario must be forced: drive raw psycopg2 connections on a barrier (the A1 guard test), or intercept the route's dependency with `monkeypatch` that performs the concurrent write on a second connection before delegating to the real function, and assert an invocation counter (e.g. `test_delete_vanished_user_is_404` asserts `calls["delete_user"] == 1`). A test that only asserts the end state cannot distinguish "the branch ran and produced the right answer" from "the branch was skipped and the end state looks the same".

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
