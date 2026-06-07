"""PostGIS reverse-geocoding of coordinates to ISO country codes (M1, Sprint 6)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def reverse_geocode_country(conn, lat: float, lon: float) -> tuple[str, str] | None:
    """Return (iso_a3, name) for the country containing (lat, lon), or None."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT iso_a3, name FROM country_polygons "
            "WHERE ST_Contains(geom, ST_SetSRID(ST_MakePoint(%s, %s), 4326)) "
            "LIMIT 1",
            (lon, lat),  # ST_MakePoint is (lon, lat)
        )
        row = cur.fetchone()
    return (row[0], row[1]) if row else None


def backfill_source_countries(conn) -> int:
    """Populate sources.country_code/country_name for rows still missing a code.

    A source's country is inferred from the most recent event published by it.
    Returns the number of sources updated.
    """
    updated = 0
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.source_id,
                   ST_Y(e.point_geom) AS lat,
                   ST_X(e.point_geom) AS lon
            FROM sources s
            JOIN LATERAL (
                SELECT point_geom FROM events e
                WHERE e.source_id = s.source_id AND e.point_geom IS NOT NULL
                ORDER BY e.event_date DESC LIMIT 1
            ) e ON true
            WHERE s.country_code IS NULL
            """
        )
        targets = cur.fetchall()

    for source_id, lat, lon in targets:
        match = reverse_geocode_country(conn, lat, lon)
        if match is None:
            continue
        iso, name = match
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sources SET country_code = %s, country_name = %s, "
                "last_verified_at = now() WHERE source_id = %s",
                (iso, name, source_id),
            )
        updated += 1
    conn.commit()
    logger.info("Reverse-geocoded %d sources", updated)
    return updated