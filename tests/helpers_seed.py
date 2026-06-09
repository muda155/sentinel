"""Deterministic event seeding + a monolith hotspot 'signature' for equivalence
checks. seed_demo_events inserts a fixed set of multi-type, co-located military
events guaranteed to fire convergence + DBSCAN."""

from __future__ import annotations


def seed_demo_events(conn) -> list[int]:
    # Convergence (FR-WM-CONVERGENCE) fires on 2+ *distinct event types* in a
    # cell. All GDELT CAMEO 14-19 collapse to a single 'military_conflict' type,
    # so a realistic convergent cell mixes GDELT military events with ACLED
    # events (which carry distinct armed_conflict / civilian_violence labels).
    # All co-located in the same 1x1 cell (lat 31, lon 34) and DBSCAN window.
    rows = [
        # (source, gdelt_id, ext_id, cameo_or_label, lat, lon)
        ("GDELT", 9001, "9001", "19", 31.50, 34.45),
        ("GDELT", 9002, "9002", "18", 31.52, 34.47),
        ("GDELT", 9003, "9003", "14", 31.49, 34.46),
        ("ACLED", None, "A9004", "armed_conflict", 31.51, 34.44),
        ("ACLED", None, "A9005", "civilian_violence", 31.50, 34.45),
    ]
    ids: list[int] = []
    with conn.cursor() as cur:
        for source, gid, ext, cameo, lat, lon in rows:
            cur.execute(
                """
                INSERT INTO events (source_system, gdelt_global_event_id, external_event_id,
                    event_date, cameo_code, country_code, url, title, point_geom, grid_cell_id)
                VALUES (%s, %s, %s, NOW(), %s, 'IL', %s, 'seed',
                        ST_SetSRID(ST_MakePoint(%s,%s),4326),
                        '1x1_LAT31_LON34')
                ON CONFLICT (source_system, external_event_id, event_date) DO NOTHING
                RETURNING event_id
                """,
                (source, gid, ext, str(cameo), f"https://seed/{ext}", lon, lat),
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
