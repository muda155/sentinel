# Phase 1 Sprint 4 Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Sprint 4 Streamlit dashboard with a pydeck map, hotspot coloring, SITREP popups, and refresh workflow integrated with the Sprint 1–3 pipeline.

**Architecture:** Add a thin dashboard data-access module in `pipeline/` that returns hotspot + summary rows from PostgreSQL, then render those rows in a single Streamlit app (`frontend/app.py`) using pydeck scatter layers and a details panel. Keep map styling and color mapping centralized in small helper functions so testing can focus on deterministic behavior. Provide both manual refresh and 15-minute auto-refresh in the app loop.

**Tech Stack:** Python, Streamlit, pydeck (Deck.gl), pandas, psycopg2, pytest

---

### Task 1: Add dashboard dependencies and data access module

**Files:**
- Create: `pipeline/dashboard_data.py`
- Modify: `requirements.txt`
- Test: `tests/test_dashboard_data.py`

- [ ] **Step 1: Write failing tests for hotspot data fetch and confidence color bins**

```python
def test_confidence_to_color_bins():
    from pipeline.dashboard_data import confidence_to_color
    assert confidence_to_color(75) == [34, 197, 94, 180]
    assert confidence_to_color(55) == [234, 179, 8, 180]
    assert confidence_to_color(20) == [107, 114, 128, 180]

def test_fetch_dashboard_hotspots_returns_expected_columns(fake_conn):
    from pipeline.dashboard_data import fetch_dashboard_hotspots
    rows = fetch_dashboard_hotspots(fake_conn, limit=5)
    assert rows[0]["hotspot_id"] == 1
    assert {"latitude", "longitude", "conf_score", "summary_text"} <= set(rows[0].keys())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dashboard_data.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.dashboard_data'`.

- [ ] **Step 3: Write minimal implementation**

```python
# pipeline/dashboard_data.py
def confidence_to_color(conf_score: float | None) -> list[int]:
    score = float(conf_score or 0)
    if score > 70:
        return [34, 197, 94, 180]  # green
    if score >= 40:
        return [234, 179, 8, 180]  # yellow
    return [107, 114, 128, 180]  # grey
```

```python
def fetch_dashboard_hotspots(conn, limit: int = 100) -> list[dict]:
    query = """
    SELECT h.hotspot_id,
           ST_Y(h.centroid_geom) AS latitude,
           ST_X(h.centroid_geom) AS longitude,
           COALESCE(h.conf_score, 0) AS conf_score,
           h.event_count,
           h.start_window,
           h.end_window,
           COALESCE(ls.summary_text, '') AS summary_text,
           COALESCE(ls.conflict_detected, false) AS conflict_detected
    FROM hotspots h
    LEFT JOIN llm_summaries ls ON ls.hotspot_id = h.hotspot_id
    ORDER BY h.conf_score DESC NULLS LAST, h.hotspot_id DESC
    LIMIT %s
    """
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_dashboard_data.py -v`  
Expected: PASS.

- [ ] **Step 5: Add dependencies**

```bash
# requirements.txt
streamlit
pydeck
```

- [ ] **Step 6: Commit**

```bash
git add requirements.txt pipeline/dashboard_data.py tests/test_dashboard_data.py
git commit -m "feat: add dashboard data access and confidence color mapping"
```

### Task 2: Implement Streamlit map with marker colors and SITREP panel

**Files:**
- Create: `frontend/app.py`
- Test: `tests/test_dashboard_app_logic.py`

- [ ] **Step 1: Write failing tests for app helper logic**

```python
def test_build_map_dataframe_contains_color_array():
    from frontend.app import build_map_dataframe
    rows = [{"hotspot_id": 1, "latitude": 10.7, "longitude": 106.6, "conf_score": 72, "summary_text": "ok"}]
    df = build_map_dataframe(rows)
    assert df.loc[0, "color"] == [34, 197, 94, 180]

def test_format_hotspot_label_includes_sitrep():
    from frontend.app import format_hotspot_label
    row = {"hotspot_id": 3, "conf_score": 58, "summary_text": "Escalation observed [1].", "event_count": 4}
    text = format_hotspot_label(row)
    assert "Hotspot #3" in text and "Escalation observed" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dashboard_app_logic.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'frontend.app'`.

- [ ] **Step 3: Write minimal app implementation**

```python
# frontend/app.py
def build_map_dataframe(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["color"] = df["conf_score"].apply(confidence_to_color)
    return df
```

```python
def format_hotspot_label(row: dict) -> str:
    return (
        f"Hotspot #{row['hotspot_id']}\\n"
        f"Confidence: {row.get('conf_score', 0):.1f}\\n"
        f"Events: {row.get('event_count', 0)}\\n"
        f"SITREP: {row.get('summary_text') or 'No summary yet'}"
    )
```

```python
# app entrypoint behavior
# - connect db
# - fetch rows
# - render pydeck ScatterplotLayer with get_fill_color='color'
# - show manual Refresh button
# - show selected hotspot details in right column
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_dashboard_app_logic.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/app.py tests/test_dashboard_app_logic.py
git commit -m "feat: add streamlit pydeck hotspot dashboard"
```

### Task 3: Add refresh behavior and integration test

**Files:**
- Modify: `frontend/app.py`
- Create: `tests/test_dashboard_integration.py`
- Modify: `README.md`

- [ ] **Step 1: Write failing integration test for refresh behavior contract**

```python
def test_refresh_interval_constant_is_15_minutes():
    from frontend.app import REFRESH_SECONDS
    assert REFRESH_SECONDS == 900
```

```python
def test_dashboard_query_limit_default():
    from pipeline.dashboard_data import DEFAULT_DASHBOARD_LIMIT
    assert DEFAULT_DASHBOARD_LIMIT == 100
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dashboard_integration.py -v`  
Expected: FAIL until constants/logic exist.

- [ ] **Step 3: Implement minimal refresh + docs wiring**

```python
# frontend/app.py
REFRESH_SECONDS = 900
# st.button("Refresh now") triggers rerun
# st_autorefresh(interval=REFRESH_SECONDS * 1000, key="dashboard-refresh")
```

```markdown
# README.md
python -m pipeline.ingestion --insert-db
python -m pipeline.clustering --lookback-hours 6 --run-scoring
streamlit run frontend/app.py
```

- [ ] **Step 4: Run full test suite**

Run: `pytest -q`  
Expected: PASS.

- [ ] **Step 5: Run sprint end-to-end verification**

Run:

```bash
docker compose up -d
python -m pipeline.ingestion --insert-db
python -m pipeline.clustering --lookback-hours 6 --run-scoring
streamlit run frontend/app.py
```

Expected:
- App loads with map and markers.
- Marker colors follow confidence bins (>70 green, 40–70 yellow, <40 grey).
- Manual refresh works.
- Auto-refresh interval is 15 minutes.

- [ ] **Step 6: Commit**

```bash
git add frontend/app.py tests/test_dashboard_integration.py README.md
git commit -m "feat: complete sprint4 dashboard refresh and integration flow"
```
