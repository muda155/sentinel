"""Hotspot naming: curated places -> country polygon -> coordinates (FR-14).

Approach adapted from World Monitor's getLocationName() layered lookup
(koala73/worldmonitor, src/services/geo-convergence.ts, AGPL-3.0) —
re-implemented from scratch; entries below are our own.
"""
from __future__ import annotations

import logging
import math

from pipeline.geocode import reverse_geocode_country

logger = logging.getLogger(__name__)

# Display labels for classify_event_type() keys. The API ships the raw key;
# the frontend translates it (lib/locales/*: "eventType.<key>").
TYPE_LABELS: dict[str, str] = {
    "military_conflict": "military conflict",
    "armed_conflict": "armed clashes",
    "civilian_violence": "violence against civilians",
    "civil_unrest": "protests",
    "unknown": "unclassified",
}

# kind -> default radius_km: conflict_zone 300, waterway 200, strategic_city 150
CURATED_PLACES: list[dict] = [
    # --- conflict zones (radius 300 km) ---
    {"id": "donbas", "name": "Donbas", "lat": 48.0, "lon": 37.8, "radius_km": 300, "kind": "conflict_zone"},
    {"id": "gaza", "name": "Gaza", "lat": 31.4, "lon": 34.4, "radius_km": 300, "kind": "conflict_zone"},
    {"id": "south-lebanon", "name": "Southern Lebanon", "lat": 33.3, "lon": 35.4, "radius_km": 300, "kind": "conflict_zone"},
    {"id": "sahel", "name": "Sahel", "lat": 14.0, "lon": -1.0, "radius_km": 300, "kind": "conflict_zone"},
    {"id": "sudan", "name": "Sudan", "lat": 15.5, "lon": 32.5, "radius_km": 300, "kind": "conflict_zone"},
    {"id": "drc-east", "name": "Eastern DRC", "lat": -1.7, "lon": 29.2, "radius_km": 300, "kind": "conflict_zone"},
    {"id": "myanmar", "name": "Myanmar", "lat": 21.9, "lon": 96.1, "radius_km": 300, "kind": "conflict_zone"},
    {"id": "yemen", "name": "Yemen", "lat": 15.4, "lon": 44.2, "radius_km": 300, "kind": "conflict_zone"},
    {"id": "somalia", "name": "Somalia", "lat": 2.0, "lon": 45.3, "radius_km": 300, "kind": "conflict_zone"},
    {"id": "syria", "name": "Syria", "lat": 35.0, "lon": 38.0, "radius_km": 300, "kind": "conflict_zone"},
    {"id": "haiti", "name": "Haiti", "lat": 18.5, "lon": -72.3, "radius_km": 300, "kind": "conflict_zone"},
    {"id": "west-bank", "name": "West Bank", "lat": 32.0, "lon": 35.3, "radius_km": 300, "kind": "conflict_zone"},
    # --- strategic waterways (radius 200 km) ---
    {"id": "hormuz", "name": "Strait of Hormuz", "lat": 26.6, "lon": 56.3, "radius_km": 200, "kind": "waterway"},
    {"id": "bab-el-mandeb", "name": "Bab el-Mandeb", "lat": 12.6, "lon": 43.3, "radius_km": 200, "kind": "waterway"},
    {"id": "taiwan-strait", "name": "Taiwan Strait", "lat": 24.0, "lon": 119.0, "radius_km": 200, "kind": "waterway"},
    {"id": "suez", "name": "Suez Canal", "lat": 30.5, "lon": 32.4, "radius_km": 200, "kind": "waterway"},
    {"id": "bosphorus", "name": "Bosphorus", "lat": 41.1, "lon": 29.1, "radius_km": 200, "kind": "waterway"},
    {"id": "malacca", "name": "Strait of Malacca", "lat": 2.5, "lon": 101.0, "radius_km": 200, "kind": "waterway"},
    {"id": "south-china-sea", "name": "South China Sea", "lat": 12.0, "lon": 113.0, "radius_km": 200, "kind": "waterway"},
    # --- strategic cities (radius 150 km) ---
    {"id": "kyiv", "name": "Kyiv", "lat": 50.45, "lon": 30.52, "radius_km": 150, "kind": "strategic_city"},
    {"id": "kharkiv", "name": "Kharkiv", "lat": 49.99, "lon": 36.23, "radius_km": 150, "kind": "strategic_city"},
    {"id": "odesa", "name": "Odesa", "lat": 46.48, "lon": 30.73, "radius_km": 150, "kind": "strategic_city"},
    {"id": "tehran", "name": "Tehran", "lat": 35.7, "lon": 51.4, "radius_km": 150, "kind": "strategic_city"},
    {"id": "baghdad", "name": "Baghdad", "lat": 33.3, "lon": 44.4, "radius_km": 150, "kind": "strategic_city"},
    {"id": "kabul", "name": "Kabul", "lat": 34.5, "lon": 69.2, "radius_km": 150, "kind": "strategic_city"},
    {"id": "tripoli", "name": "Tripoli", "lat": 32.9, "lon": 13.2, "radius_km": 150, "kind": "strategic_city"},
    {"id": "caracas", "name": "Caracas", "lat": 10.5, "lon": -66.9, "radius_km": 150, "kind": "strategic_city"},
    {"id": "islamabad", "name": "Islamabad", "lat": 33.7, "lon": 73.0, "radius_km": 150, "kind": "strategic_city"},
    {"id": "seoul", "name": "Seoul", "lat": 37.6, "lon": 127.0, "radius_km": 150, "kind": "strategic_city"},
    {"id": "taipei", "name": "Taipei", "lat": 25.0, "lon": 121.6, "radius_km": 150, "kind": "strategic_city"},
]

_KIND_ORDER = ("conflict_zone", "waterway", "strategic_city")


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two lat/lon points."""
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def resolve_place(lat: float, lon: float) -> dict | None:
    """Nearest curated place containing (lat, lon), checked kind by kind.

    Priority order: conflict_zone > waterway > strategic_city.
    Within each kind the nearest place within its radius wins.
    Returns the matching CURATED_PLACES dict, or None if no place matches.
    """
    for kind in _KIND_ORDER:
        best: dict | None = None
        best_dist = float("inf")
        for place in CURATED_PLACES:
            if place["kind"] != kind:
                continue
            dist = _haversine_km(lat, lon, place["lat"], place["lon"])
            if dist <= place["radius_km"] and dist < best_dist:
                best, best_dist = place, dist
        if best is not None:
            return best
    return None


def name_hotspot(conn, lat: float, lon: float) -> str:
    """Best-effort display name. Never raises (FR-14)."""
    place = resolve_place(lat, lon)
    country_name: str | None = None
    try:
        geo = reverse_geocode_country(conn, lat, lon)
        country_name = geo[1] if geo else None
    except Exception:
        logger.warning("reverse geocode failed for (%s, %s)", lat, lon, exc_info=True)

    if place is not None:
        if country_name and country_name != place["name"]:
            return f"{place['name']}, {country_name}"
        return place["name"]
    if country_name:
        return country_name
    return f"{lat:.1f}°, {lon:.1f}°"


def backfill_names(conn) -> int:
    """Name hotspots where name IS NULL. Returns rows updated."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT hotspot_id, ST_Y(centroid_geom), ST_X(centroid_geom)
            FROM hotspots
            WHERE name IS NULL
            """
        )
        rows = cursor.fetchall()
        updated = 0
        for hotspot_id, lat, lon in rows:
            name = name_hotspot(conn, float(lat), float(lon))
            cursor.execute(
                "UPDATE hotspots SET name = %s WHERE hotspot_id = %s",
                (name, hotspot_id),
            )
            updated += 1
    conn.commit()
    logger.info("backfilled %d hotspot names", updated)
    return updated


def main() -> None:
    import argparse

    from pipeline.db import get_pooled_connection

    parser = argparse.ArgumentParser(description="Hotspot naming utilities (FR-14)")
    parser.add_argument("--backfill", action="store_true",
                        help="Name all hotspots where name IS NULL")
    args = parser.parse_args()
    if not args.backfill:
        parser.error("nothing to do: pass --backfill")
    conn, pool = get_pooled_connection()
    try:
        backfill_names(conn)
    finally:
        pool.return_connection(conn)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
