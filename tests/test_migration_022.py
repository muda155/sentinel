"""FR-26: relevance gate statistics columns."""


def test_gate_stat_columns_exist(live_conn):
    with live_conn.cursor() as cur:
        cur.execute(
            """SELECT column_name, is_nullable, data_type
               FROM information_schema.columns
               WHERE table_name = 'hotspots'
                 AND column_name IN ('gated_pairs', 'vacuous_claims_dropped')
               ORDER BY column_name"""
        )
        rows = cur.fetchall()
    assert [r[0] for r in rows] == ["gated_pairs", "vacuous_claims_dropped"]
    assert all(r[1] == "YES" for r in rows)
    assert all(r[2] == "integer" for r in rows)


def test_repository_persists_gate_stats(live_conn):
    from pipeline.consistency import ClaimVerdict, ConsistencyRepository

    with live_conn.cursor() as cur:
        cur.execute(
            """INSERT INTO hotspots (centroid_geom, radius_km, event_count,
                                     unique_sources, conf_score,
                                     start_window, end_window)
               VALUES (ST_SetSRID(ST_MakePoint(0, 0), 4326), 10.0, 1,
                       1, 50.0, now(), now())
               RETURNING hotspot_id"""
        )
        hotspot_id = cur.fetchone()[0]
    live_conn.commit()
    try:
        verdict = ClaimVerdict(text="A specific claim was made.", status="uncorroborated",
                               support=0.0, dispute=0.0, weight=0.1, evidence=[])
        ConsistencyRepository(live_conn).save(
            hotspot_id, [verdict], 50.0, gated_pairs=7, vacuous_claims_dropped=2
        )
        with live_conn.cursor() as cur:
            cur.execute(
                "SELECT gated_pairs, vacuous_claims_dropped FROM hotspots WHERE hotspot_id = %s",
                (hotspot_id,),
            )
            assert cur.fetchone() == (7, 2)
    finally:
        with live_conn.cursor() as cur:
            cur.execute("DELETE FROM hotspots WHERE hotspot_id = %s", (hotspot_id,))
        live_conn.commit()
