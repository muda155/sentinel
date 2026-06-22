import importlib
from unittest import mock

import numpy as np
import pandas as pd
import pytest


def _sample_events() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "event_id": [1, 2, 3, 4],
            "ActionGeo_Lat": [10.0, 10.04, 10.5, 11.5],
            "ActionGeo_Long": [106.0, 106.03, 106.5, 107.5],
            "event_date": pd.to_datetime(
                [
                    "2026-05-06T00:00:00Z",
                    "2026-05-06T00:30:00Z",
                    "2026-05-06T00:20:00Z",
                    "2026-05-06T03:30:00Z",
                ],
                utc=True,
            ),
        }
    )


# ---------------------------------------------------------------------------
# Existing tests (must continue to pass)
# ---------------------------------------------------------------------------

def test_build_distance_matrix_applies_temporal_penalty() -> None:
    clustering = importlib.import_module("pipeline.clustering")
    df = _sample_events()

    matrix = clustering.build_distance_matrix(df, max_time_diff_h=1)

    assert matrix.shape == (4, 4)
    assert matrix[0, 1] < 10
    assert matrix[0, 3] == float("inf")


def test_cluster_dbscan_groups_close_events_and_marks_noise() -> None:
    clustering = importlib.import_module("pipeline.clustering")
    df = _sample_events().iloc[[0, 1, 2]].reset_index(drop=True)
    matrix = clustering.build_distance_matrix(df, max_time_diff_h=1)

    labels = clustering.cluster_dbscan(matrix, eps_km=8, min_samples=2)

    assert labels[0] == labels[1]
    assert labels[2] == -1


def test_cluster_repository_persists_hotspots_and_event_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clustering = importlib.import_module("pipeline.clustering")
    events_df = pd.DataFrame(
        {
            "event_id": [10, 11, 12],
            "ActionGeo_Lat": [10.0, 10.02, 13.0],
            "ActionGeo_Long": [106.0, 106.02, 109.0],
            "event_date": pd.to_datetime(
                ["2026-05-06T00:00:00Z", "2026-05-06T00:20:00Z", "2026-05-06T00:30:00Z"],
                utc=True,
            ),
            "SOURCEURL": [
                "https://a.example.com/news/1",
                "https://b.example.com/news/2",
                "https://c.example.com/news/3",
            ],
        }
    )
    labels = np.array([0, 0, -1])

    class FakeCursor:
        def __init__(self) -> None:
            self.executed = []

        def execute(self, query, params=None) -> None:
            self.executed.append((query, params))

        def fetchone(self):
            return (55,)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    class FakeConn:
        def __init__(self) -> None:
            self.cursor_obj = FakeCursor()
            self.committed = False

        def cursor(self):
            return self.cursor_obj

        def commit(self) -> None:
            self.committed = True

    fake_conn = FakeConn()
    execute_values_mock = mock.Mock()
    monkeypatch.setattr("pipeline.clustering.execute_values", execute_values_mock)

    repository = clustering.ClusterRepository(fake_conn)
    summary = repository.save_clusters(events_df, labels)

    assert fake_conn.committed is True
    assert summary["hotspot_count"] == 1
    assert summary["linked_events"] == 2
    assert any("INSERT INTO hotspots" in query for query, _ in fake_conn.cursor_obj.executed)
    execute_values_mock.assert_called_once()
    assert execute_values_mock.call_args.args[2] == [(10, 55), (11, 55)]


def test_run_clustering_pipeline_calls_repository() -> None:
    clustering = importlib.import_module("pipeline.clustering")
    events_df = pd.DataFrame(
        {
            "event_id": [1, 2, 3],
            "ActionGeo_Lat": [10.0, 10.02, 12.5],
            "ActionGeo_Long": [106.0, 106.01, 109.5],
            "event_date": pd.to_datetime(
                ["2026-05-06T00:00:00Z", "2026-05-06T00:15:00Z", "2026-05-06T03:00:00Z"],
                utc=True,
            ),
            "SOURCEURL": [
                "https://a.example.com/x",
                "https://b.example.com/y",
                "https://c.example.com/z",
            ],
        }
    )

    class Repo:
        def __init__(self) -> None:
            self.called = False
            self.labels = None

        def save_clusters(self, events_df_arg, labels_arg):
            self.called = True
            self.labels = labels_arg
            return {"hotspot_count": 1, "linked_events": 2}

    repo = Repo()
    summary = clustering.run_clustering_pipeline(
        events_df, repository=repo, eps_km=8, min_samples=2, max_time_diff_h=1
    )

    assert repo.called is True
    assert summary["hotspot_count"] == 1
    assert summary["linked_events"] == 2
    assert summary["noise_count"] == 1


# ---------------------------------------------------------------------------
# New tests for Phase B — Grid-Cell Convergence Engine
# ---------------------------------------------------------------------------

def test_assign_grid_cell() -> None:
    """Verify cell ID format for various lat/lon."""
    clustering = importlib.import_module("pipeline.clustering")

    assert clustering.assign_grid_cell(48.85, 2.35) == "1x1_LAT48_LON2"
    assert clustering.assign_grid_cell(-5.3, -30.7) == "1x1_LAT-6_LON-31"
    assert clustering.assign_grid_cell(0.0, 0.0) == "1x1_LAT0_LON0"
    assert clustering.assign_grid_cell(89.9, 179.9) == "1x1_LAT89_LON179"
    assert clustering.assign_grid_cell(-89.9, -179.9) == "1x1_LAT-90_LON-180"


def test_assign_grid_cell_custom_grid_size() -> None:
    """Verify custom grid size works."""
    clustering = importlib.import_module("pipeline.clustering")

    cell = clustering.assign_grid_cell(10.5, 20.5, grid_size=2.0)
    # grid_size=2.0, lat=10.5 -> floor(10.5/2)*2 = 10, lon=20.5 -> floor(20.5/2)*2 = 20
    assert cell == "1x1_LAT10_LON20"


def test_classify_event_type_gdelt_military() -> None:
    """GDELT events with CAMEO 14-19 map to military_conflict."""
    clustering = importlib.import_module("pipeline.clustering")

    for code in range(14, 20):
        row = {"source_system": "GDELT", "cameo_code": code}
        assert clustering.classify_event_type(row) == "military_conflict"


def test_classify_event_type_gdelt_non_military() -> None:
    """GDELT events outside CAMEO 14-19 map to unknown."""
    clustering = importlib.import_module("pipeline.clustering")

    row = {"source_system": "GDELT", "cameo_code": 10}
    assert clustering.classify_event_type(row) == "unknown"


def test_classify_event_type_acled() -> None:
    """ACLED events map by event_type field."""
    clustering = importlib.import_module("pipeline.clustering")

    assert (
        clustering.classify_event_type(
            {"source_system": "ACLED", "event_type": "Battles"}
        )
        == "armed_conflict"
    )
    assert (
        clustering.classify_event_type(
            {"source_system": "ACLED", "event_type": "Explosions/Remote violence"}
        )
        == "armed_conflict"
    )
    assert (
        clustering.classify_event_type(
            {"source_system": "ACLED", "event_type": "Violence against civilians"}
        )
        == "civilian_violence"
    )
    assert (
        clustering.classify_event_type(
            {"source_system": "ACLED", "event_type": "Protests"}
        )
        == "civil_unrest"
    )


def test_classify_event_type_unknown_source() -> None:
    """Unknown source system returns unknown."""
    clustering = importlib.import_module("pipeline.clustering")

    row = {"source_system": "UNKNOWN", "cameo_code": 14}
    assert clustering.classify_event_type(row) == "unknown"


def test_classify_event_type_gdelt_multidigit_cameo() -> None:
    """Live GDELT EventCodes are 3-4 digits ('190', '1712'); the CAMEO root
    (first two digits, 14-19) must classify as military_conflict, not 'unknown'.
    Regression: int('190') is not in [14,19], which silently mislabeled every
    real GDELT event and starved convergence of its only event type."""
    clustering = importlib.import_module("pipeline.clustering")

    for code in ["141", "150", "164", "173", "180", "190", "196", "1712", "1823"]:
        row = {"source_system": "GDELT", "cameo_code": code}
        assert clustering.classify_event_type(row) == "military_conflict", code

    # Non-military roots (outside 14-19) stay unknown.
    assert (
        clustering.classify_event_type({"source_system": "GDELT", "cameo_code": "010"})
        == "unknown"
    )
    assert (
        clustering.classify_event_type({"source_system": "GDELT", "cameo_code": "100"})
        == "unknown"
    )


def test_dbscan_window_start_floors_to_day_for_daily_data() -> None:
    """GDELT events are stamped midnight UTC (day-granular SQLDATE). A 2h DBSCAN
    window computed from NOW excludes them once NOW is >2h past midnight, so the
    lower bound must floor to start-of-day UTC."""
    from datetime import datetime, timezone

    clustering = importlib.import_module("pipeline.clustering")

    now = datetime(2026, 6, 22, 7, 52, tzinfo=timezone.utc)
    start = clustering._dbscan_window_start(now, 2)
    assert start == datetime(2026, 6, 22, 0, 0, tzinfo=timezone.utc)


def test_dbscan_window_start_keeps_longer_window() -> None:
    """A window longer than the time elapsed since midnight still reaches back
    the full window (the day-floor only ever widens, never narrows)."""
    from datetime import datetime, timezone

    clustering = importlib.import_module("pipeline.clustering")

    now = datetime(2026, 6, 22, 7, 52, tzinfo=timezone.utc)
    start = clustering._dbscan_window_start(now, 48)
    assert start == datetime(2026, 6, 20, 7, 52, tzinfo=timezone.utc)


def test_compute_convergence_score() -> None:
    """Test: 2 types x 3 events -> type_score=50, count_boost=6, total=56."""
    clustering = importlib.import_module("pipeline.clustering")

    score = clustering.compute_convergence_score(event_type_count=2, total_events=3)
    assert score == 56.0


def test_compute_convergence_score_capped() -> None:
    """Test: 4 types x 100 events -> min(100, 100+25) = 100."""
    clustering = importlib.import_module("pipeline.clustering")

    score = clustering.compute_convergence_score(event_type_count=4, total_events=100)
    assert score == 100.0


def test_compute_convergence_score_single_type() -> None:
    """Single event type score: 1*25 + min(25, 10*2) = 25+20 = 45."""
    clustering = importlib.import_module("pipeline.clustering")

    score = clustering.compute_convergence_score(event_type_count=1, total_events=10)
    assert score == 45.0


def test_classify_alert_level_critical_4_types() -> None:
    """4 types, score 80 -> Critical."""
    clustering = importlib.import_module("pipeline.clustering")

    assert clustering.classify_alert_level(80.0, 4) == "Critical"
    assert clustering.classify_alert_level(100.0, 4) == "Critical"


def test_classify_alert_level_critical_3_types() -> None:
    """3 types, score 70 -> Critical."""
    clustering = importlib.import_module("pipeline.clustering")

    assert clustering.classify_alert_level(70.0, 3) == "Critical"
    assert clustering.classify_alert_level(99.0, 3) == "Critical"


def test_classify_alert_level_high() -> None:
    """2-3 types, score 55-80 -> High."""
    clustering = importlib.import_module("pipeline.clustering")

    assert clustering.classify_alert_level(55.0, 2) == "High"
    assert clustering.classify_alert_level(65.0, 2) == "High"
    assert clustering.classify_alert_level(65.0, 3) == "High"


def test_classify_alert_level_medium() -> None:
    """2 types, score < 55 -> Medium."""
    clustering = importlib.import_module("pipeline.clustering")

    assert clustering.classify_alert_level(25.0, 2) == "Medium"
    assert clustering.classify_alert_level(40.0, 2) == "Medium"


def test_classify_alert_level_none() -> None:
    """Very low score with few types -> None."""
    clustering = importlib.import_module("pipeline.clustering")

    assert clustering.classify_alert_level(10.0, 1) is None
    assert clustering.classify_alert_level(20.0, 2) is None
    assert clustering.classify_alert_level(0.0, 0) is None


def test_bin_to_grid() -> None:
    """Events binned to correct cells based on grid_cell_id and event type."""
    clustering = importlib.import_module("pipeline.clustering")

    events_df = pd.DataFrame(
        {
            "event_id": [1, 2, 3],
            "lat": [10.5, 10.3, 20.1],
            "lon": [106.2, 106.1, 107.0],
            "source_system": ["GDELT", "GDELT", "GDELT"],
            "cameo_code": [14, 18, 19],
            "grid_cell_id": [
                "1x1_LAT10_LON106",
                "1x1_LAT10_LON106",
                "1x1_LAT20_LON107",
            ],
        }
    )

    binned = clustering.bin_to_grid(events_df)

    assert len(binned) == 2
    assert "1x1_LAT10_LON106" in binned
    assert "1x1_LAT20_LON107" in binned

    cell_a = binned["1x1_LAT10_LON106"]
    assert cell_a["total_events"] == 2
    assert cell_a["type_counts"].get("military_conflict") == 2
    assert cell_a["event_ids"] == [1, 2]

    cell_b = binned["1x1_LAT20_LON107"]
    assert cell_b["total_events"] == 1
    assert cell_b["type_counts"].get("military_conflict") == 1


def test_bin_to_grid_missing_grid_cell_id() -> None:
    """Events without grid_cell_id have it computed from lat/lon."""
    clustering = importlib.import_module("pipeline.clustering")

    events_df = pd.DataFrame(
        {
            "event_id": [1],
            "lat": [48.85],
            "lon": [2.35],
            "source_system": ["GDELT"],
            "cameo_code": [14],
            "grid_cell_id": [None],
        }
    )

    binned = clustering.bin_to_grid(events_df)

    assert "1x1_LAT48_LON2" in binned
    assert binned["1x1_LAT48_LON2"]["total_events"] == 1


def test_single_type_no_convergence() -> None:
    """Cell with 1 event type -> convergence_score=25, no convergence zone alert."""
    clustering = importlib.import_module("pipeline.clustering")

    score = clustering.compute_convergence_score(event_type_count=1, total_events=5)
    # type_score=25, count_boost=min(25,10)=10, score=35
    assert score == 35.0

    alert = clustering.classify_alert_level(score, 1)
    assert alert is None


def test_bin_to_grid_mixed_event_types() -> None:
    """Cell with GDELT + ACLED produces correct type counts."""
    clustering = importlib.import_module("pipeline.clustering")

    events_df = pd.DataFrame(
        {
            "event_id": [1, 2, 3],
            "lat": [32.0, 32.3, 32.1],
            "lon": [35.0, 35.1, 35.2],
            "source_system": ["GDELT", "GDELT", "ACLED"],
            "cameo_code": [18, 19, None],
            "event_type": [None, None, "Battles"],
            "grid_cell_id": [
                "1x1_LAT32_LON35",
                "1x1_LAT32_LON35",
                "1x1_LAT32_LON35",
            ],
        }
    )

    binned = clustering.bin_to_grid(events_df)

    assert len(binned) == 1
    cell = binned["1x1_LAT32_LON35"]
    assert cell["total_events"] == 3
    assert cell["type_counts"].get("military_conflict") == 2
    assert cell["type_counts"].get("armed_conflict") == 1


def test_compute_convergence_score_with_mixed_types() -> None:
    """2 types (military_conflict + armed_conflict), 3 events -> score 56."""
    clustering = importlib.import_module("pipeline.clustering")

    score = clustering.compute_convergence_score(event_type_count=2, total_events=3)
    # type_score=50, count_boost=min(25,6)=6, score=56
    assert score == 56.0

    alert = clustering.classify_alert_level(score, 2)
    assert alert == "High"


def test_grid_cell_repository_parse_cell_id() -> None:
    """Parse cell_id string back to lat/lon."""
    clustering = importlib.import_module("pipeline.clustering")

    repo = clustering.GridCellRepository.__new__(clustering.GridCellRepository)
    assert repo._parse_cell_id("1x1_LAT48_LON2") == (48, 2)
    assert repo._parse_cell_id("1x1_LAT-5_LON-30") == (-5, -30)
    assert repo._parse_cell_id("1x1_LAT0_LON0") == (0, 0)


def test_compute_convergence_score_3_types_6_events() -> None:
    """Taiwan Strait example: 3 types + 6 events -> score 87."""
    clustering = importlib.import_module("pipeline.clustering")

    score = clustering.compute_convergence_score(event_type_count=3, total_events=6)
    # type_score=75, count_boost=min(25,12)=12, score=87
    assert score == 87.0

    alert = clustering.classify_alert_level(score, 3)
    assert alert == "Critical"


def test_classify_event_type_from_series() -> None:
    """classify_event_type works with pandas Series."""
    clustering = importlib.import_module("pipeline.clustering")

    row = pd.Series({"source_system": "GDELT", "cameo_code": 17})
    assert clustering.classify_event_type(row) == "military_conflict"
