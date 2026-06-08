"""DB read queries for the REST API. Mirrors pipeline.dashboard_data joins so
REST and the (deprecated) dashboard return the same numbers."""
from __future__ import annotations

from typing import Any


def fetch_hotspots(conn, *, limit=50, min_conf=0.0, min_convergence=0.0,
                   alert_level=None) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 200))   # spec: max 200
    q = """
        SELECT h.hotspot_id, ST_Y(h.centroid_geom) lat, ST_X(h.centroid_geom) lon,
               COALESCE(h.conf_score,0) conf_score, h.event_count,
               COALESCE(g.convergence_score,0) convergence_score,
               COALESCE(g.alert_level,'Medium') alert_level
        FROM hotspots h LEFT JOIN grid_cells g ON h.cell_id = g.cell_id
        WHERE COALESCE(h.conf_score,0) >= %s AND COALESCE(g.convergence_score,0) >= %s
          AND (%s IS NULL OR g.alert_level = %s)
        ORDER BY h.conf_score DESC NULLS LAST, h.hotspot_id DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(q, (min_conf, min_convergence, alert_level, alert_level, limit))
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def fetch_hotspot_summary(conn, hotspot_id: int) -> dict | None:
    q = """
        SELECT COALESCE(ls.summary_text,'') summary, COALESCE(ls.conflict_detected,false) conflict_detected,
               COALESCE(ls.sources_cited,'[]'::jsonb) sources_cited,
               COALESCE(h.conf_score,0) conf_score, COALESCE(g.convergence_score,0) convergence_score
        FROM hotspots h LEFT JOIN llm_summaries ls ON ls.hotspot_id=h.hotspot_id
                        LEFT JOIN grid_cells g ON h.cell_id=g.cell_id
        WHERE h.hotspot_id=%s
    """
    with conn.cursor() as cur:
        cur.execute(q, (hotspot_id,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [c[0] for c in cur.description]
        return dict(zip(cols, row))


def fetch_events_bbox(conn, *, sw_lat, sw_lon, ne_lat, ne_lon, start, end,
                      cursor=0, page_size=100) -> list[dict]:
    page_size = max(1, min(int(page_size), 1000))   # spec: max 1000
    q = """
        SELECT event_id, ST_Y(point_geom) lat, ST_X(point_geom) lon,
               event_date, cameo_code, country_code, url, title
        FROM events
        WHERE point_geom && ST_MakeEnvelope(%s,%s,%s,%s,4326)
          AND event_date BETWEEN %s AND %s AND event_id > %s
        ORDER BY event_id ASC LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(q, (sw_lon, sw_lat, ne_lon, ne_lat, start, end, cursor, page_size))
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
