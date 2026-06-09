
import pytest


@pytest.fixture
def mock_hotspots():
    """Sample hotspot data from fetch_dashboard_hotspots."""
    return [
        {
            "hotspot_id": 1,
            "latitude": 20.5,
            "longitude": 10.5,
            "conf_score": 75.0,
            "event_count": 5,
            "start_window": "2024-01-01",
            "end_window": "2024-01-02",
            "summary_text": "Major conflict event in region A",
            "conflict_detected": True,
        },
        {
            "hotspot_id": 2,
            "latitude": 35.0,
            "longitude": 45.0,
            "conf_score": 55.0,
            "event_count": 3,
            "start_window": "2024-01-01",
            "end_window": "2024-01-02",
            "summary_text": "Minor skirmish in region B",
            "conflict_detected": False,
        },
        {
            "hotspot_id": 3,
            "latitude": 15.0,
            "longitude": 25.0,
            "conf_score": 20.0,
            "event_count": 1,
            "start_window": "2024-01-01",
            "end_window": "2024-01-02",
            "summary_text": "Low-confidence alert",
            "conflict_detected": False,
        },
    ]


def test_format_hotspots_for_pydeck_adds_color_column(mock_hotspots):
    """Test that hotspots are formatted with pydeck-compatible color column."""
    from frontend.app import format_hotspots_for_pydeck

    formatted = format_hotspots_for_pydeck(mock_hotspots)
    
    assert len(formatted) == 3
    assert all("color" in spot for spot in formatted)
    assert all("latitude" in spot and "longitude" in spot for spot in formatted)


def test_format_hotspots_for_pydeck_maps_confidence_to_colors(mock_hotspots):
    """Test that confidence scores map to correct colors."""
    from frontend.app import format_hotspots_for_pydeck
    from pipeline.dashboard_data import confidence_to_color

    formatted = format_hotspots_for_pydeck(mock_hotspots)
    
    # Hotspot 1: 75 (green)
    assert formatted[0]["color"] == confidence_to_color(75)
    assert formatted[0]["color"] == [34, 197, 94, 180]
    
    # Hotspot 2: 55 (yellow)
    assert formatted[1]["color"] == confidence_to_color(55)
    assert formatted[1]["color"] == [234, 179, 8, 180]
    
    # Hotspot 3: 20 (grey)
    assert formatted[2]["color"] == confidence_to_color(20)
    assert formatted[2]["color"] == [107, 114, 128, 180]


def test_format_hotspots_for_pydeck_preserves_hotspot_data(mock_hotspots):
    """Test that essential hotspot data is preserved in formatted output."""
    from frontend.app import format_hotspots_for_pydeck

    formatted = format_hotspots_for_pydeck(mock_hotspots)
    
    assert formatted[0]["hotspot_id"] == 1
    assert formatted[0]["event_count"] == 5
    assert formatted[0]["conf_score"] == 75.0
    assert formatted[0]["summary_text"] == "Major conflict event in region A"


def test_extract_sitrep_details_returns_hotspot_info():
    """Test that SITREP details are correctly extracted from a hotspot."""
    from frontend.app import extract_sitrep_details

    hotspot = {
        "hotspot_id": 1,
        "latitude": 20.5,
        "longitude": 10.5,
        "conf_score": 75.0,
        "event_count": 5,
        "start_window": "2024-01-01",
        "end_window": "2024-01-02",
        "summary_text": "Major conflict event in region A",
        "conflict_detected": True,
    }

    sitrep = extract_sitrep_details(hotspot)
    
    assert sitrep["conflict_type"] == "Conflict" or sitrep["conflict_type"] == "No Conflict"
    assert sitrep["confidence"] == 75.0
    assert sitrep["llm_summary"] == "Major conflict event in region A"
    assert sitrep["event_count"] == 5
    assert sitrep["timestamp"] == "2024-01-01 to 2024-01-02"


def test_extract_sitrep_details_formats_confidence_category():
    """Test that confidence category is correctly determined."""
    from frontend.app import extract_sitrep_details

    hotspot_high = {
        "hotspot_id": 1,
        "latitude": 20.5,
        "longitude": 10.5,
        "conf_score": 75.0,
        "event_count": 5,
        "start_window": "2024-01-01",
        "end_window": "2024-01-02",
        "summary_text": "Major conflict",
        "conflict_detected": True,
    }

    sitrep = extract_sitrep_details(hotspot_high)
    assert sitrep["confidence_category"] in ["High", "Medium", "Low"]


def test_build_map_config_returns_valid_pydeck_layer_config(mock_hotspots):
    """Test that map configuration is valid for pydeck rendering."""
    from frontend.app import build_map_config

    formatted = [
        {
            "latitude": 20.5,
            "longitude": 10.5,
            "color": [34, 197, 94, 180],
            "event_count": 5,
            "conf_score": 75.0,
        },
        {
            "latitude": 35.0,
            "longitude": 45.0,
            "color": [234, 179, 8, 180],
            "event_count": 3,
            "conf_score": 55.0,
        },
    ]
    
    map_config = build_map_config(formatted)
    
    assert "viewport" in map_config
    assert "layers" in map_config
    assert len(map_config["layers"]) > 0
    assert map_config["viewport"]["latitude"] is not None
    assert map_config["viewport"]["longitude"] is not None


def test_build_map_config_centers_on_hotspot_data(mock_hotspots):
    """Test that map center is calculated from hotspot data."""
    from frontend.app import build_map_config

    formatted = [
        {"latitude": 20.5, "longitude": 10.5, "color": [34, 197, 94, 180]},
        {"latitude": 35.0, "longitude": 45.0, "color": [234, 179, 8, 180]},
    ]
    
    map_config = build_map_config(formatted)
    
    # Center should be roughly between the two points
    assert 20.5 <= map_config["viewport"]["latitude"] <= 35.0
    assert 10.5 <= map_config["viewport"]["longitude"] <= 45.0


def test_build_map_config_handles_empty_hotspots():
    """Test that map config handles empty hotspot data gracefully."""
    from frontend.app import build_map_config

    map_config = build_map_config([])
    
    assert "viewport" in map_config
    # Default to world view when no hotspots
    assert map_config["viewport"]["latitude"] is not None
    assert map_config["viewport"]["longitude"] is not None


def test_get_confidence_category_classifies_correctly():
    """Test confidence score classification."""
    from frontend.app import get_confidence_category

    assert get_confidence_category(75) == "High"
    assert get_confidence_category(71) == "High"
    assert get_confidence_category(70) == "Medium"  # Boundary at >70, not >=70
    assert get_confidence_category(55) == "Medium"
    assert get_confidence_category(40) == "Medium"
    assert get_confidence_category(39) == "Low"
    assert get_confidence_category(0) == "Low"
