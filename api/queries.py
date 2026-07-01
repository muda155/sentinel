"""DB read queries for the REST API. Mirrors pipeline.dashboard_data joins so
REST and the (deprecated) dashboard return the same numbers."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


def fetch_grid_cells(conn, *, min_convergence=1.0) -> list[dict]:
    q = """
        SELECT cell_id, ST_Y(ST_Centroid(cell_geom)) lat, ST_X(ST_Centroid(cell_geom)) lon,
               COALESCE(convergence_score,0) convergence_score,
               CASE
                 WHEN event_type_count >= 3 AND convergence_score >= 70 THEN 'Critical'
                 WHEN convergence_score >= 50 THEN 'High'
                 ELSE 'Medium'
               END AS alert_level,
               COALESCE(total_events,0) total_events
        FROM grid_cells
        WHERE COALESCE(convergence_score,0) >= %s
        ORDER BY convergence_score DESC
        LIMIT 2000
    """
    with conn.cursor() as cur:
        cur.execute(q, (min_convergence,))
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def fetch_hotspots(conn, *, limit=50, min_conf=0.0, min_convergence=0.0,
                   alert_level=None) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 200))   # spec: max 200
    q = """
        SELECT h.hotspot_id, ST_Y(h.centroid_geom) lat, ST_X(h.centroid_geom) lon,
               h.name, h.end_window, h.created_at,
               COALESCE(h.conf_score,0) conf_score, h.event_count,
               COALESCE(g.convergence_score,h.convergence_score,0) convergence_score,
               COALESCE(h.alert_level,'Medium') alert_level
        FROM hotspots h LEFT JOIN grid_cells g ON h.cell_id = g.cell_id
        WHERE COALESCE(h.conf_score,0) >= %s
          AND COALESCE(g.convergence_score,h.convergence_score,0) >= %s
          AND (%s IS NULL OR h.alert_level = %s)
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
               COALESCE(h.conf_score,0) conf_score,
               COALESCE(g.convergence_score,h.convergence_score,0) convergence_score
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


def fetch_hotspot_by_id(conn, hotspot_id: int) -> dict | None:
    """Fetch a single hotspot by ID with full enrichment (lat, lon, conf, convergence, alert)."""
    q = """
        SELECT h.hotspot_id, ST_Y(h.centroid_geom) lat, ST_X(h.centroid_geom) lon,
               h.name, h.end_window, h.created_at,
               COALESCE(h.conf_score,0) conf_score, h.event_count,
               COALESCE(g.convergence_score,h.convergence_score,0) convergence_score,
               COALESCE(h.alert_level,'Medium') alert_level
        FROM hotspots h LEFT JOIN grid_cells g ON h.cell_id = g.cell_id
        WHERE h.hotspot_id = %s
    """
    with conn.cursor() as cur:
        cur.execute(q, (hotspot_id,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [c[0] for c in cur.description]
        return dict(zip(cols, row))


def fetch_sources(conn) -> list[dict]:
    q = """
        SELECT source_id, domain, trust_tier, country_code, country_name
        FROM sources
        ORDER BY source_id ASC
        LIMIT 1000
    """
    with conn.cursor() as cur:
        cur.execute(q)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


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


_HOTSPOT_SELECT = """
    SELECT h.hotspot_id, h.name, ST_Y(h.centroid_geom) lat, ST_X(h.centroid_geom) lon,
           h.end_window, h.created_at,
           COALESCE(h.conf_score,0) conf_score, h.event_count,
           COALESCE(g.convergence_score,h.convergence_score,0) convergence_score,
           COALESCE(h.alert_level,'Medium') alert_level
    FROM hotspots h LEFT JOIN grid_cells g ON h.cell_id = g.cell_id
"""


def _rows_to_dicts(cur) -> list[dict]:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def fetch_search(conn, q: str) -> dict[str, list]:
    """Grouped search (FR-15): hotspot names, article titles (FTS), source domains."""
    q = (q or "").strip()
    if len(q) < 2:
        return {"hotspots": [], "events": [], "sources": []}
    pattern = f"%{q}%"
    with conn.cursor() as cur:
        cur.execute(
            _HOTSPOT_SELECT + """
            WHERE h.name ILIKE %s
            ORDER BY h.conf_score DESC NULLS LAST, h.hotspot_id DESC
            LIMIT 10
            """,
            (pattern,),
        )
        hotspots = _rows_to_dicts(cur)

        cur.execute(
            """
            SELECT e.event_id, e.title, e.url, e.event_date,
                   h.hotspot_id, h.name, ST_Y(h.centroid_geom) h_lat,
                   ST_X(h.centroid_geom) h_lon, COALESCE(h.conf_score,0) h_conf,
                   h.event_count h_event_count,
                   COALESCE(g.convergence_score,h.convergence_score,0) h_convergence,
                   COALESCE(h.alert_level,'Medium') h_alert
            FROM events e
            JOIN event_hotspot eh ON eh.event_id = e.event_id
            JOIN hotspots h ON h.hotspot_id = eh.hotspot_id
            LEFT JOIN grid_cells g ON h.cell_id = g.cell_id
            WHERE e.title_tsv @@ websearch_to_tsquery('english', %s)
            ORDER BY e.event_date DESC, e.event_id DESC
            LIMIT 10
            """,
            (q,),
        )
        events = [
            {
                "event_id": r["event_id"], "title": r["title"], "url": r["url"],
                "domain": _domain(r["url"]), "event_date": r["event_date"],
                "hotspot": {
                    "hotspot_id": r["hotspot_id"], "name": r["name"],
                    "lat": r["h_lat"], "lon": r["h_lon"], "conf_score": r["h_conf"],
                    "convergence_score": r["h_convergence"],
                    "alert_level": r["h_alert"], "event_count": r["h_event_count"],
                },
            }
            for r in _rows_to_dicts(cur)
        ]

        cur.execute(
            """
            SELECT s.source_id, s.domain, s.trust_tier
            FROM sources s
            WHERE s.domain ILIKE %s
            ORDER BY s.source_id
            LIMIT 5
            """,
            (pattern,),
        )
        sources = _rows_to_dicts(cur)
        for src in sources:
            cur.execute(
                _HOTSPOT_SELECT + """
                WHERE h.hotspot_id IN (
                    SELECT DISTINCT eh.hotspot_id
                    FROM events e JOIN event_hotspot eh ON eh.event_id = e.event_id
                    WHERE e.source_id = %s
                )
                ORDER BY h.conf_score DESC NULLS LAST
                LIMIT 5
                """,
                (src["source_id"],),
            )
            src["hotspots"] = _rows_to_dicts(cur)

    return {"hotspots": hotspots, "events": events, "sources": sources}


def _domain(url: str | None) -> str:
    if not url:
        return ""
    return urlparse(url).netloc.lower()


def assign_citation_indices(rows: list[dict]) -> list[dict]:
    """1-based citation_index for url-bearing rows, in input order."""
    n = 0
    for row in rows:
        row["domain"] = _domain(row.get("url"))
        if row.get("url"):
            n += 1
            row["citation_index"] = n
        else:
            row["citation_index"] = None
    return rows


def fetch_hotspot_events(conn, hotspot_id: int) -> list[dict] | None:
    """Linked events for a hotspot; None if the hotspot does not exist.
    ORDER BY must stay in lockstep with LLMRepository.fetch_hotspot_articles."""
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM hotspots WHERE hotspot_id = %s", (hotspot_id,))
        if cur.fetchone() is None:
            return None
        cur.execute(
            """
            SELECT e.event_id, e.title, e.url, e.source_system, e.event_date,
                   CASE
                     WHEN e.source_system = 'GDELT' THEN 'military_conflict'
                     WHEN lower(e.cameo_code) IN
                          ('armed_conflict','civilian_violence','civil_unrest')
                       THEN lower(e.cameo_code)
                     ELSE 'unknown'
                   END AS event_type_label,
                   s.trust_tier, COALESCE(s.trust_score, 0.4) AS trust_score
            FROM event_hotspot eh
            JOIN events e ON e.event_id = eh.event_id
            LEFT JOIN sources s ON e.source_id = s.source_id
            WHERE eh.hotspot_id = %s
            ORDER BY (e.url IS NULL OR e.url = ''),
                     e.event_date DESC, e.event_id DESC
            """,
            (hotspot_id,),
        )
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return assign_citation_indices(rows)
