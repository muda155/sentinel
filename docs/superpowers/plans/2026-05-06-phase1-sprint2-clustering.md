# Phase 1 Sprint 2 Clustering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver Sprint 2 by implementing DBSCAN-based spatio-temporal hotspot clustering and hotspot persistence.

**Architecture:** Add a focused `pipeline/clustering.py` module with three clear responsibilities: distance matrix construction, DBSCAN label generation, and repository persistence. Persist hotspots in PostGIS with centroid/radius/window aggregates and a many-to-many `event_hotspot` link table. Validate behavior with synthetic-cluster unit tests first, then run full ingestion+clustering tests.

**Tech Stack:** Python, pandas, numpy, scikit-learn (DBSCAN), psycopg2, PostgreSQL/PostGIS, pytest

---

### Task 1: Add Sprint 2 schema for hotspots

**Files:**
- Create: `db/init/002_create_hotspots.sql`
- Modify: `README.md`

- [ ] **Step 1: Add hotspot tables SQL**

```sql
CREATE TABLE IF NOT EXISTS hotspots (
    hotspot_id BIGSERIAL PRIMARY KEY,
    centroid_geom geometry(Point, 4326) NOT NULL,
    radius_km DOUBLE PRECISION NOT NULL,
    start_window timestamptz NOT NULL,
    end_window timestamptz NOT NULL,
    event_count INTEGER NOT NULL,
    unique_sources INTEGER NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS event_hotspot (
    event_id BIGINT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    hotspot_id BIGINT NOT NULL REFERENCES hotspots(hotspot_id) ON DELETE CASCADE,
    PRIMARY KEY (event_id, hotspot_id)
);
```

- [ ] **Step 2: Document schema init behavior**

Run: `docker compose down && docker compose up -d`
Expected: startup applies `001_create_events.sql` and `002_create_hotspots.sql` for fresh volume.

### Task 2: Implement clustering core with TDD

**Files:**
- Create: `pipeline/clustering.py`
- Create: `tests/test_clustering.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Write failing tests for distance and labels**

```python
def test_build_distance_matrix_applies_temporal_penalty(): ...
def test_cluster_dbscan_groups_close_events_and_marks_noise(): ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_clustering.py -k "distance_matrix or dbscan"`
Expected: FAIL with missing clustering functions.

- [ ] **Step 3: Implement minimal clustering**

```python
def build_distance_matrix(events_df, max_time_diff_h=1): ...
def cluster_dbscan(dist_matrix, eps_km=50, min_samples=3): ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest -q tests/test_clustering.py -k "distance_matrix or dbscan"`
Expected: PASS

### Task 3: Persist hotspots and links with TDD

**Files:**
- Modify: `pipeline/clustering.py`
- Modify: `tests/test_clustering.py`

- [ ] **Step 1: Add failing test for aggregate hotspot persistence**

```python
def test_cluster_repository_persists_hotspots_and_event_links(monkeypatch): ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_clustering.py -k repository`
Expected: FAIL due to missing repository class/method.

- [ ] **Step 3: Implement repository**

```python
class ClusterRepository:
    def save_clusters(self, events_df, labels): ...
```

- [ ] **Step 4: Run full Sprint 2 tests**

Run: `pytest -q tests/test_clustering.py tests/test_ingestion.py`
Expected: PASS

