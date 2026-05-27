import pytest


@pytest.fixture
def fake_conn():
    """Mock connection that returns test data with convergence columns."""

    class FakeCursor:
        def __init__(self):
            self.description = [
                ("hotspot_id",),
                ("latitude",),
                ("longitude",),
                ("conf_score",),
                ("event_count",),
                ("start_window",),
                ("end_window",),
                ("summary_text",),
                ("conflict_detected",),
                ("convergence_score",),
                ("alert_level",),
            ]

        def execute(self, query, params):
            pass

        def fetchall(self):
            return [
                (
                    1,
                    10.5,
                    20.5,
                    75.0,
                    5,
                    "2024-01-01",
                    "2024-01-02",
                    "Test summary",
                    False,
                    62.0,
                    "High",
                ),
            ]

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    return FakeConnection()


def test_confidence_to_color_bins():
    from pipeline.dashboard_data import confidence_to_color

    assert confidence_to_color(75) == [34, 197, 94, 180]
    assert confidence_to_color(55) == [234, 179, 8, 180]
    assert confidence_to_color(20) == [107, 114, 128, 180]


def test_alert_to_ring_color():
    from pipeline.dashboard_data import alert_to_ring_color

    assert alert_to_ring_color("Critical") == [239, 68, 68, 220]
    assert alert_to_ring_color("High") == [249, 115, 22, 220]
    assert alert_to_ring_color("Medium") == [0, 0, 0, 0]
    assert alert_to_ring_color(None) == [0, 0, 0, 0]


def test_grid_cell_alert_level():
    from pipeline.dashboard_data import grid_cell_alert_level

    # 4 types, score 85 → Critical
    assert grid_cell_alert_level(85, 4) == "Critical"
    # 3 types, score 72 → Critical
    assert grid_cell_alert_level(72, 3) == "Critical"
    # 2 types, score 55 → High
    assert grid_cell_alert_level(55, 2) == "High"
    # 2 types, score 20 → Medium
    assert grid_cell_alert_level(20, 2) == "Medium"


def test_fetch_dashboard_hotspots_returns_expected_columns(fake_conn):
    from pipeline.dashboard_data import fetch_dashboard_hotspots

    rows = fetch_dashboard_hotspots(fake_conn, limit=5)
    assert rows[0]["hotspot_id"] == 1
    assert {
        "latitude",
        "longitude",
        "conf_score",
        "summary_text",
        "convergence_score",
        "alert_level",
    } <= set(rows[0].keys())
    assert rows[0]["convergence_score"] == 62.0
    assert rows[0]["alert_level"] == "High"
