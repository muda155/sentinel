# Note: dashboard_data.py functions take a connection object as parameter
# to maintain flexibility. Callers are responsible for managing the connection.


def confidence_to_color(conf_score: float | None) -> list[int]:
    score = float(conf_score or 0)
    if score > 70:
        return [34, 197, 94, 180]  # green
    if score >= 40:
        return [234, 179, 8, 180]  # yellow
    return [107, 114, 128, 180]  # grey


def fetch_dashboard_hotspots(conn, limit: int = 100) -> list[dict]:
    query = """
    SELECT h.hotspot_id,
           ST_Y(h.centroid_geom) AS latitude,
           ST_X(h.centroid_geom) AS longitude,
           COALESCE(h.conf_score, 0) AS conf_score,
           h.event_count,
           h.start_window,
           h.end_window,
           COALESCE(ls.summary_text, '') AS summary_text,
           COALESCE(ls.conflict_detected, false) AS conflict_detected
    FROM hotspots h
    LEFT JOIN llm_summaries ls ON ls.hotspot_id = h.hotspot_id
    ORDER BY h.conf_score DESC NULLS LAST, h.hotspot_id DESC
    LIMIT %s
    """
    cursor = conn.cursor()
    cursor.execute(query, (limit,))
    rows = cursor.fetchall()
    return [dict(zip([col[0] for col in cursor.description], row)) for row in rows]
