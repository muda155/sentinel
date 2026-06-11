from pipeline.naming import CURATED_PLACES, TYPE_LABELS, resolve_place

import pipeline.naming as naming  # noqa: E402


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


class _BackfillCursor:
    """Captures executed SQL; serves one unnamed hotspot row."""
    def __init__(self):
        self.executed: list[tuple[str, tuple | None]] = []
        self._rows = [(7, 48.0, 37.8)]  # hotspot_id, lat, lon

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _BackfillConn:
    def __init__(self):
        self.cursor_obj = _BackfillCursor()
        self.committed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True


def test_backfill_names_updates_null_rows(monkeypatch):
    monkeypatch.setattr(naming, "name_hotspot",
                        lambda conn, lat, lon: "Donbas, Ukraine")
    conn = _BackfillConn()
    updated = naming.backfill_names(conn)
    assert updated == 1
    select_sql = conn.cursor_obj.executed[0][0]
    assert "WHERE name IS NULL" in select_sql
    update_sql, update_params = conn.cursor_obj.executed[1]
    assert "UPDATE hotspots SET name = %s WHERE hotspot_id = %s" in update_sql
    assert update_params == ("Donbas, Ukraine", 7)
    assert conn.committed
