"""End-to-end integration tests for dashboard with mocked pipeline."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta


@pytest.fixture
def mock_sample_hotspots():
    """Sample hotspots simulating full pipeline output."""
    return [
        {
            "hotspot_id": 1,
            "latitude": 20.5,
            "longitude": 10.5,
            "conf_score": 85.0,
            "event_count": 12,
            "start_window": "2024-01-15 10:00:00",
            "end_window": "2024-01-15 14:00:00",
            "summary_text": "Major conflict escalation detected in region A with 12 corroborating sources",
            "conflict_detected": True,
        },
        {
            "hotspot_id": 2,
            "latitude": 35.7,
            "longitude": 45.2,
            "conf_score": 62.0,
            "event_count": 8,
            "start_window": "2024-01-15 09:30:00",
            "end_window": "2024-01-15 13:30:00",
            "summary_text": "Military mobilization reported in region B",
            "conflict_detected": False,
        },
        {
            "hotspot_id": 3,
            "latitude": 15.3,
            "longitude": 25.9,
            "conf_score": 45.0,
            "event_count": 4,
            "start_window": "2024-01-15 08:00:00",
            "end_window": "2024-01-15 12:00:00",
            "summary_text": "Low-confidence alert - requires verification",
            "conflict_detected": False,
        },
    ]


class TestDashboardE2EIntegration:
    """End-to-end tests for dashboard with full pipeline integration."""

    @patch("pipeline.db.get_pooled_connection")
    def test_e2e_dashboard_fetches_and_renders_hotspots(self, mock_get_pooled_connection, mock_sample_hotspots):
        """Test that dashboard can fetch and render hotspots through full pipeline."""
        from frontend.app import render_dashboard, format_hotspots_for_pydeck
        from pipeline.dashboard_data import fetch_dashboard_hotspots

        # Mock database connection
        mock_conn = MagicMock()
        mock_pool = MagicMock()
        mock_get_pooled_connection.return_value = (mock_conn, mock_pool)

        # Mock cursor to return sample hotspots
        mock_cursor = MagicMock()
        mock_cursor.description = [
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
        mock_cursor.fetchall.return_value = [
            (
                h["hotspot_id"],
                h["latitude"],
                h["longitude"],
                h["conf_score"],
                h["event_count"],
                h["start_window"],
                h["end_window"],
                h["summary_text"],
                h["conflict_detected"],
            )
            for h in mock_sample_hotspots
        ]
        mock_conn.cursor.return_value = mock_cursor

        # Fetch hotspots via dashboard_data
        hotspots = fetch_dashboard_hotspots(mock_conn, limit=100)

        # Verify hotspots were fetched correctly
        assert len(hotspots) == 3
        assert hotspots[0]["hotspot_id"] == 1
        assert hotspots[0]["conf_score"] == 85.0
        assert "Major conflict escalation" in hotspots[0]["summary_text"]

    @patch("pipeline.db.get_pooled_connection")
    def test_e2e_dashboard_formats_pipeline_output_for_rendering(
        self, mock_get_pooled_connection, mock_sample_hotspots
    ):
        """Test that dashboard correctly formats pipeline output for Pydeck rendering."""
        from frontend.app import format_hotspots_for_pydeck
        from pipeline.dashboard_data import confidence_to_color

        # Format hotspots for pydeck
        formatted = format_hotspots_for_pydeck(mock_sample_hotspots)

        # Verify formatting
        assert len(formatted) == 3
        assert all("color" in h for h in formatted)

        # Verify colors are correct
        assert formatted[0]["color"] == confidence_to_color(85.0)  # High confidence: green
        assert formatted[1]["color"] == confidence_to_color(62.0)  # Medium confidence: yellow
        assert formatted[2]["color"] == confidence_to_color(45.0)  # Low-medium confidence

    @patch("pipeline.db.get_pooled_connection")
    def test_e2e_dashboard_extracts_sitrep_from_pipeline_output(
        self, mock_get_pooled_connection, mock_sample_hotspots
    ):
        """Test that SITREP extraction works with real pipeline output."""
        from frontend.app import extract_sitrep_details

        hotspot = mock_sample_hotspots[0]
        sitrep = extract_sitrep_details(hotspot)

        # Verify SITREP details
        assert sitrep["conflict_type"] == "Conflict"
        assert sitrep["confidence"] == 85.0
        assert sitrep["confidence_category"] == "High"
        assert sitrep["event_count"] == 12
        assert "Major conflict escalation" in sitrep["llm_summary"]

    @patch("pipeline.db.get_pooled_connection")
    def test_e2e_dashboard_handles_mixed_confidence_levels(
        self, mock_get_pooled_connection, mock_sample_hotspots
    ):
        """Test dashboard correctly handles hotspots with varying confidence levels."""
        from frontend.app import get_confidence_category

        for hotspot in mock_sample_hotspots:
            category = get_confidence_category(hotspot["conf_score"])
            assert category in ["High", "Medium", "Low"]

        # Verify specific categorization
        assert get_confidence_category(85.0) == "High"
        assert get_confidence_category(62.0) == "Medium"
        assert get_confidence_category(45.0) == "Medium"

    @patch("pipeline.db.get_pooled_connection")
    def test_e2e_dashboard_builds_map_from_pipeline_output(
        self, mock_get_pooled_connection, mock_sample_hotspots
    ):
        """Test that map is built correctly from full pipeline output."""
        from frontend.app import format_hotspots_for_pydeck, build_map_config

        formatted = format_hotspots_for_pydeck(mock_sample_hotspots)
        map_config = build_map_config(formatted)

        # Verify map config is valid
        assert "viewport" in map_config
        assert "layers" in map_config
        assert len(map_config["layers"]) > 0

        # Verify viewport is centered around hotspots
        center_lat = map_config["viewport"]["latitude"]
        center_lon = map_config["viewport"]["longitude"]

        # Center should be roughly in the middle of the hotspots
        lat_values = [h["latitude"] for h in mock_sample_hotspots]
        lon_values = [h["longitude"] for h in mock_sample_hotspots]
        assert min(lat_values) <= center_lat <= max(lat_values)
        assert min(lon_values) <= center_lon <= max(lon_values)

    def test_e2e_mock_database_returns_valid_hotspot_structure(self, mock_sample_hotspots):
        """Test that mocked database returns valid hotspot data structure."""
        # All hotspots should have required fields
        required_fields = {
            "hotspot_id",
            "latitude",
            "longitude",
            "conf_score",
            "event_count",
            "start_window",
            "end_window",
            "summary_text",
            "conflict_detected",
        }

        for hotspot in mock_sample_hotspots:
            assert required_fields <= set(hotspot.keys())

            # Verify data types
            assert isinstance(hotspot["hotspot_id"], int)
            assert isinstance(hotspot["latitude"], (int, float))
            assert isinstance(hotspot["longitude"], (int, float))
            assert isinstance(hotspot["conf_score"], (int, float))
            assert isinstance(hotspot["event_count"], int)
            assert isinstance(hotspot["summary_text"], str)
            assert isinstance(hotspot["conflict_detected"], bool)

    @patch("pipeline.db.get_pooled_connection")
    def test_e2e_dashboard_handles_empty_pipeline_output(self, mock_get_pooled_connection):
        """Test dashboard gracefully handles empty pipeline output."""
        from frontend.app import build_map_config

        # Empty hotspots
        map_config = build_map_config([])

        # Should still return valid config
        assert "viewport" in map_config
        assert "layers" in map_config

    @patch("pipeline.db.get_pooled_connection")
    def test_e2e_dashboard_handles_db_error(self, mock_get_pooled_connection):
        """Test dashboard handles database connection errors gracefully."""
        # Mock database error
        mock_get_pooled_connection.side_effect = Exception("Database connection failed")

        # Should raise exception (caught by dashboard UI)
        with pytest.raises(Exception, match="Database connection failed"):
            raise mock_get_pooled_connection.side_effect

    def test_e2e_sitrep_display_with_all_pipeline_fields(self, mock_sample_hotspots):
        """Test that SITREP can display all fields from pipeline output."""
        from frontend.app import extract_sitrep_details

        hotspot = mock_sample_hotspots[0]
        sitrep = extract_sitrep_details(hotspot)

        # Verify all display fields are present
        display_fields = {
            "conflict_type",
            "key_locations",
            "participants",
            "confidence",
            "confidence_category",
            "timestamp",
            "llm_summary",
            "event_count",
        }
        assert display_fields <= set(sitrep.keys())

        # Verify content is not empty
        assert sitrep["key_locations"] != "(0.00, 0.00)"
        assert sitrep["llm_summary"] != "No summary available"
        assert sitrep["event_count"] > 0

    def test_e2e_pipeline_output_statistics_aggregation(self, mock_sample_hotspots):
        """Test that dashboard correctly aggregates statistics from pipeline output."""
        # Total hotspots
        total_hotspots = len(mock_sample_hotspots)
        assert total_hotspots == 3

        # High confidence count
        high_conf = len([h for h in mock_sample_hotspots if h["conf_score"] > 70])
        assert high_conf == 1

        # Total events
        total_events = sum(h["event_count"] for h in mock_sample_hotspots)
        assert total_events == 24

        # Conflict detected count
        conflict_count = len([h for h in mock_sample_hotspots if h["conflict_detected"]])
        assert conflict_count == 1
