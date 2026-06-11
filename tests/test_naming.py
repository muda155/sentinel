from pipeline.naming import CURATED_PLACES, TYPE_LABELS, resolve_place


def test_curated_place_hit_inside_radius():
    # Donetsk city coordinates -> Donbas conflict zone (300 km radius)
    place = resolve_place(48.0, 37.8)
    assert place is not None
    assert place["name"] == "Donbas"
    assert place["kind"] == "conflict_zone"


def test_waterway_hit():
    place = resolve_place(26.6, 56.3)  # Strait of Hormuz
    assert place is not None
    assert place["name"] == "Strait of Hormuz"


def test_miss_outside_all_radii():
    assert resolve_place(-45.0, -150.0) is None  # South Pacific


def test_nearest_wins_within_kind():
    # A point between two strategic cities resolves to the nearer one.
    place = resolve_place(50.45, 30.52)  # Kyiv exactly
    assert place is not None
    assert place["name"] == "Kyiv"


def test_conflict_zone_priority_over_city():
    # Donetsk is within both Donbas zone and (hypothetically) city radii;
    # conflict_zone kind must win.
    place = resolve_place(48.0, 37.8)
    assert place["kind"] == "conflict_zone"


def test_type_labels_complete():
    assert set(TYPE_LABELS) == {
        "military_conflict", "armed_conflict", "civilian_violence",
        "civil_unrest", "unknown",
    }


def test_all_curated_places_have_valid_fields():
    for p in CURATED_PLACES:
        assert p["kind"] in ("conflict_zone", "waterway", "strategic_city")
        assert -90 <= p["lat"] <= 90 and -180 <= p["lon"] <= 180
        assert p["radius_km"] > 0 and p["name"]


# ── name_hotspot() tests ──────────────────────────────────────────────

import pipeline.naming as naming


class _FakeConn:  # never actually used by the stubbed geocoder
    pass


def test_name_hotspot_place_and_country(monkeypatch):
    monkeypatch.setattr(naming, "reverse_geocode_country",
                        lambda conn, lat, lon: ("UKR", "Ukraine"))
    assert naming.name_hotspot(_FakeConn(), 48.0, 37.8) == "Donbas, Ukraine"


def test_name_hotspot_place_equals_country_no_duplication(monkeypatch):
    monkeypatch.setattr(naming, "reverse_geocode_country",
                        lambda conn, lat, lon: ("SDN", "Sudan"))
    assert naming.name_hotspot(_FakeConn(), 15.5, 32.5) == "Sudan"


def test_name_hotspot_country_fallback(monkeypatch):
    monkeypatch.setattr(naming, "reverse_geocode_country",
                        lambda conn, lat, lon: ("BRA", "Brazil"))
    # Amazon interior: no curated place
    assert naming.name_hotspot(_FakeConn(), -4.0, -63.0) == "Brazil"


def test_name_hotspot_coordinate_fallback(monkeypatch):
    monkeypatch.setattr(naming, "reverse_geocode_country",
                        lambda conn, lat, lon: None)
    assert naming.name_hotspot(_FakeConn(), -45.0, -150.0) == "-45.0°, -150.0°"


def test_name_hotspot_never_raises(monkeypatch):
    def boom(conn, lat, lon):
        raise RuntimeError("db down")
    monkeypatch.setattr(naming, "reverse_geocode_country", boom)
    # Geocode failure inside a curated zone: still get the place name.
    assert naming.name_hotspot(_FakeConn(), 48.0, 37.8) == "Donbas"
    # Geocode failure outside any zone: degrade to coordinates.
    assert naming.name_hotspot(_FakeConn(), -45.0, -150.0) == "-45.0°, -150.0°"
