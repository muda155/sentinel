# Note: dashboard_data.py functions take a connection object as parameter
# to maintain flexibility. Callers are responsible for managing the connection.


def confidence_to_color(conf_score: float | None) -> list[int]:
    """Map consensus confidence score to pydeck RGBA color (FR-13)."""
    score = float(conf_score or 0)
    if score > 70:
        return [34, 197, 94, 180]   # green
    if score >= 40:
        return [234, 179, 8, 180]   # yellow
    return [107, 114, 128, 180]     # grey


def alert_to_ring_color(alert_level: str | None) -> list[int]:
    """Map alert_level to pydeck stroke RGBA color (FR-13).

    Critical → red ring, High → orange ring, Medium/unset → transparent.
    """
    level = (alert_level or "").strip()
    if level == "Critical":
        return [239, 68, 68, 220]    # red
    if level == "High":
        return [249, 115, 22, 220]   # orange
    return [0, 0, 0, 0]             # transparent (no ring)


def grid_cell_alert_color(alert_level: str | None) -> list[int]:
    """Map alert_level to pydeck polygon fill RGBA color for grid-cell overlay."""
    level = (alert_level or "").strip()
    if level == "Critical":
        return [239, 68, 68, 60]     # red, low opacity
    if level == "High":
        return [249, 115, 22, 60]    # orange, low opacity
    return [234, 179, 8, 30]         # yellow, very low opacity


from pipeline.clustering import classify_alert_level as grid_cell_alert_level


def fetch_dashboard_hotspots(conn, limit: int = 100) -> list[dict]:
    """Fetch hotspots with confidence, convergence, and alert data (FR-13).

    JOINs grid_cells via cell_id to retrieve convergence_score.
    Falls back to hotspots.convergence_score and hotspots.alert_level when
    the JOIN produces NULL (e.g. for hotspots created before grid-cell data).
    """
    query = """
    SELECT h.hotspot_id,
           ST_Y(h.centroid_geom) AS latitude,
           ST_X(h.centroid_geom) AS longitude,
           COALESCE(h.conf_score, 0) AS conf_score,
           h.event_count,
           h.start_window,
           h.end_window,
           COALESCE(ls.summary_text, '') AS summary_text,
           COALESCE(ls.conflict_detected, false) AS conflict_detected,
           COALESCE(g.convergence_score, 0) AS convergence_score,
           COALESCE(g.alert_level, 'Medium') AS alert_level
    FROM hotspots h
    LEFT JOIN llm_summaries ls ON ls.hotspot_id = h.hotspot_id
    LEFT JOIN grid_cells g ON h.cell_id = g.cell_id
    ORDER BY h.conf_score DESC NULLS LAST, h.hotspot_id DESC
    LIMIT %s
    """
    cursor = conn.cursor()
    cursor.execute(query, (limit,))
    rows = cursor.fetchall()
    return [dict(zip([col[0] for col in cursor.description], row)) for row in rows]


def fetch_grid_cells_for_overlay(conn, min_convergence: float = 1.0) -> list[dict]:
    """Fetch grid cells for the convergence heatmap overlay.

    Returns cells with convergence_score above the threshold, including
    cell geometry as GeoJSON and a derived alert_level.

    Args:
        conn: Database connection.
        min_convergence: Minimum convergence_score to include (default 1.0).

    Returns:
        List of dicts with cell_id, geometry (GeoJSON), convergence_score,
        event_type_count, total_events, and alert_level.
    """
    query = """
    SELECT cell_id,
           ST_AsGeoJSON(cell_geom) AS geometry,
           convergence_score,
           event_type_count,
           total_events
    FROM grid_cells
    WHERE convergence_score >= %s
    ORDER BY convergence_score DESC
    LIMIT 500
    """
    cursor = conn.cursor()
    cursor.execute(query, (min_convergence,))
    rows = cursor.fetchall()
    cells = []
    for row in rows:
        d = dict(zip([col[0] for col in cursor.description], row))
        d["alert_level"] = grid_cell_alert_level(
            d.get("convergence_score", 0),
            d.get("event_type_count", 0),
        )
        cells.append(d)
    return cells
