import pytest


@pytest.fixture
def fake_conn():
    """Mock connection that returns test data."""
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
            ]
        
        def execute(self, query, params):
            pass
        
        def fetchall(self):
            return [
                (1, 10.5, 20.5, 75.0, 5, "2024-01-01", "2024-01-02", "Test summary", False),
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


def test_fetch_dashboard_hotspots_returns_expected_columns(fake_conn):
    from pipeline.dashboard_data import fetch_dashboard_hotspots
    rows = fetch_dashboard_hotspots(fake_conn, limit=5)
    assert rows[0]["hotspot_id"] == 1
    assert {"latitude", "longitude", "conf_score", "summary_text"} <= set(rows[0].keys())
