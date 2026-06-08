"""Deterministic event seeding + a monolith hotspot 'signature' for equivalence
checks. seed_demo_events inserts a fixed set of multi-type, co-located military
events guaranteed to fire convergence + DBSCAN."""

from __future__ import annotations


def seed_demo_events(conn) -> list[int]:
    rows = [
        # (gdelt_id, ext_id, cameo_root, lat, lon)  -- 4 distinct cameo root codes (14-19)
        # in the same 1x1 cell (lat 31, lon 34) so convergence fires
        (9001, "9001", 14, 31.50, 34.45),
        (9002, "9002", 15, 31.52, 34.47),
        (9003, "9003", 18, 31.49, 34.46),
        (9004, "9004", 19, 31.51, 34.44),
        (9005, "9005", 14, 31.50, 34.45),
    ]
    ids: list[int] = []
    with conn.cursor() as cur:
        for gid, ext, cameo, lat, lon in rows:
            cur.execute(
                """
                INSERT INTO events (source_system, gdelt_global_event_id, external_event_id,
                    event_date, cameo_code, country_code, url, title, point_geom, grid_cell_id)
                VALUES ('GDELT', %s, %s, NOW(), %s, 'IL', %s, 'seed',
                        ST_SetSRID(ST_MakePoint(%s,%s),4326),
                        '1x1_LAT31_LON34')
                ON CONFLICT (source_system, external_event_id, event_date) DO NOTHING
                RETURNING event_id
                """,
                (gid, ext, str(cameo), f"https://seed/{ext}", lon, lat),
            )
            r = cur.fetchone()
            if r:
                ids.append(r[0])
    conn.commit()
    return ids


def monolith_hotspot_signature(conn) -> tuple[int, list[float]]:
    """A comparable signature of current hotspots: (count, sorted rounded conf_scores)."""
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(ROUND(conf_score::numeric,1),0) FROM hotspots ORDER BY 1")
        scores = [float(r[0]) for r in cur.fetchall()]
    return (len(scores), scores)
