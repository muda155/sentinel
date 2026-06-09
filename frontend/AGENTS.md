# DOX — frontend/

## Purpose

Streamlit dashboard: Pydeck map of hotspots color-coded by confidence score, auto-refresh every 15 min, manual refresh button.

## Ownership

All files in `frontend/`.

## Local Contracts

- Color coding: green > 70%, yellow 40–70%, grey < 40% confidence
- Auto-refresh managed by APScheduler in `refresh_utils.py` — do not add a second scheduler
- Dashboard reads from the DB via `pipeline/dashboard_data.py`; it must not write to the DB
- `refresh_utils.py` owns all refresh-timing logic; `app.py` only calls into it

## Work Guidance

- Test UI changes by running `streamlit run frontend/app.py` and checking the golden path (map loads, hotspots render, refresh fires)
- Do not import from `api/` — the dashboard talks to the DB directly, not through the REST layer

## Verification

```bash
pytest tests/test_dashboard_data.py tests/test_dashboard_refresh.py tests/test_dashboard_ui.py tests/test_e2e_dashboard.py -q
ruff check frontend/
```
