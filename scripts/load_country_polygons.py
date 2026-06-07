"""Load Natural Earth admin-0 country polygons into country_polygons.

Usage:
    python scripts/load_country_polygons.py path/to/ne_110m_admin_0_countries.geojson

Download (once, where internet is available):
    https://www.naturalearthdata.com/downloads/110m-cultural-vectors/
    (the 110m "Admin 0 - Countries" GeoJSON; 50m for finer borders)

Idempotent: upserts by iso_a3.
"""

from __future__ import annotations

import json
import os
import sys

import psycopg2


def _connect():
    return psycopg2.connect(
        host=os.getenv("PGHOST", "127.0.0.1"),
        port=int(os.getenv("PGPORT", "6432")),
        dbname=os.getenv("PGDATABASE", "sentinel"),
        user=os.getenv("PGUSER", "sentinel_user"),
        password=os.getenv("PGPASSWORD", "sentinel_pass"),
    )


def load(geojson_path: str) -> int:
    with open(geojson_path, encoding="utf-8") as fh:
        data = json.load(fh)

    rows = 0
    conn = _connect()
    try:
        with conn.cursor() as cur:
            for feature in data["features"]:
                props = feature.get("properties", {})
                iso = (props.get("ISO_A3") or props.get("iso_a3") or "").strip()
                name = (props.get("NAME") or props.get("name") or "").strip()
                if not iso or iso == "-99" or not name:
                    continue  # Natural Earth uses -99 for disputed/unmapped
                geom_json = json.dumps(feature["geometry"])
                cur.execute(
                    """
                    INSERT INTO country_polygons (iso_a3, name, geom)
                    VALUES (%s, %s,
                            ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)))
                    ON CONFLICT (iso_a3) DO UPDATE
                        SET name = EXCLUDED.name, geom = EXCLUDED.geom
                    """,
                    (iso[:3], name, geom_json),
                )
                rows += 1
        conn.commit()
    finally:
        conn.close()
    return rows


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    count = load(sys.argv[1])
    print(f"Loaded {count} country polygons.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())