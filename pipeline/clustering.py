from __future__ import annotations

import argparse
import math
import os
from urllib.parse import urlparse

import numpy as np
import pandas as pd
from psycopg2.extras import execute_values
from sklearn.cluster import DBSCAN

from pipeline.db import get_pooled_connection
from pipeline.llm_verifier import verify_hotspots_with_llm
from pipeline.naming import name_hotspot
from pipeline.scoring import ScoringRepository

EARTH_RADIUS_KM = 6371.0088


# ---------------------------------------------------------------------------
# Grid-cell assignment (moved from ingestion.py per spec Section 6.1.2)
# ---------------------------------------------------------------------------

def assign_grid_cell(lat: float, lon: float, grid_size: float = 1.0) -> str:
    """Assign a 1x1 degree grid cell ID based on lat/lon coordinates.

    Cell ID format: '1x1_LAT{floor_lat}_LON{floor_lon}'
    Example: assign_grid_cell(48.85, 2.35) -> '1x1_LAT48_LON2'

    Args:
        lat: Latitude in decimal degrees.
        lon: Longitude in decimal degrees.
        grid_size: Grid cell size in degrees (default 1.0).

    Returns:
        Grid cell ID string.
    """
    grid_lat = int(math.floor(lat / grid_size) * grid_size)
    grid_lon = int(math.floor(lon / grid_size) * grid_size)
    return f"1x1_LAT{grid_lat}_LON{grid_lon}"


# ---------------------------------------------------------------------------
# Event type classification (FR-WM-CONVERGENCE)
# ---------------------------------------------------------------------------

def classify_event_type(row) -> str:
    """Classify an event row into a World Monitor event type label.

    Mapping (spec FR-WM-CONVERGENCE):
      - GDELT CAMEO 14-19  -> military_conflict
      - ACLED Battles / Explosions -> armed_conflict
      - ACLED Violence against civilians -> civilian_violence
      - ACLED Protests -> civil_unrest

    Args:
        row: A dict-like row (pd.Series, dict, or mapping) with at least
             'source_system'. If GDELT, 'cameo_code' is used. If ACLED,
             an 'event_type' key is consulted when available.

    Returns:
        One of 'military_conflict', 'armed_conflict', 'civilian_violence',
        'civil_unrest', or 'unknown'.
    """
    source = str(row.get("source_system", "")).upper()

    if source == "GDELT":
        cameo = row.get("cameo_code")
        if cameo is not None:
            try:
                code = int(cameo)
                if 14 <= code <= 19:
                    return "military_conflict"
            except (ValueError, TypeError):
                pass

    elif source == "ACLED":
        # ACLED ingestion stores the normalised Sentinel label in cameo_code
        # (see ingestion._map_acled_event_type); live API rows may instead carry
        # a raw 'event_type' string. Consult the stored label first.
        known = {"armed_conflict", "civilian_violence", "civil_unrest"}
        label = str(row.get("cameo_code", "")).strip().lower()
        if label in known:
            return label
        event_type = str(row.get("event_type", "")).lower()
        if "battle" in event_type or "explosion" in event_type:
            return "armed_conflict"
        if "violence against civilians" in event_type or "civilian" in event_type:
            return "civilian_violence"
        if "protest" in event_type or "riot" in event_type:
            return "civil_unrest"

    return "unknown"


# ---------------------------------------------------------------------------
# World Monitor convergence scoring formula (FR-WM-CONVERGENCE)
# ---------------------------------------------------------------------------

def compute_convergence_score(event_type_count: int, total_events: int) -> float:
    """Compute World Monitor convergence score.

    Formula (exact World Monitor):
        type_score  = unique_event_types * 25
        count_boost = min(25, total_events * 2)
        convergence_score = min(100, type_score + count_boost)

    Args:
        event_type_count: Number of distinct event types in the cell.
        total_events: Total number of events in the cell.

    Returns:
        Convergence score as a float (0-100).
    """
    type_score = event_type_count * 25
    count_boost = min(25, total_events * 2)
    return min(100.0, float(type_score + count_boost))


def classify_alert_level(convergence_score: float, unique_types: int) -> str | None:
    """Classify alert level from convergence score and unique type count.

    Thresholds (spec FR-WM-CONVERGENCE):
      - 4 types, 80-100  -> Critical
      - 3 types, 70-100  -> Critical
      - 2-3 types, 50-80 -> High
      - 2 types, 25-55   -> Medium

    Args:
        convergence_score: The computed convergence score (0-100).
        unique_types: Number of distinct event types.

    Returns:
        'Critical', 'High', 'Medium', or None if score is too low.
    """
    if unique_types >= 4 and convergence_score >= 80:
        return "Critical"
    if unique_types >= 3 and convergence_score >= 70:
        return "Critical"
    if unique_types >= 2 and convergence_score >= 50:
        return "High"
    if unique_types >= 2 and convergence_score >= 25:
        return "Medium"
    return None


def bin_to_grid(events_df: pd.DataFrame) -> dict:
    """Bin events into 1x1 degree grid cells.

    Each event is classified by event type and assigned to a grid cell.
    Cells with 2+ distinct event types become Convergence Zones.

    Args:
        events_df: DataFrame with at least event_id, lat, lon, source_system,
                   and optionally grid_cell_id and cameo_code columns.

    Returns:
        Dict mapping cell_id -> {
            'type_counts': {type_label: count},
            'unique_types': int,
            'total_events': int,
            'event_ids': [int],
        }
    """
    binned: dict = {}
    for _, row in events_df.iterrows():
        cell_id = row.get("grid_cell_id")
        if not cell_id or pd.isna(cell_id) or str(cell_id).strip() == "":
            lat = float(row["lat"])
            lon = float(row["lon"])
            cell_id = assign_grid_cell(lat, lon)

        event_type = classify_event_type(row)

        if cell_id not in binned:
            binned[cell_id] = {
                "type_counts": {},
                "total_events": 0,
                "event_ids": [],
            }

        cell = binned[cell_id]
        cell["type_counts"][event_type] = cell["type_counts"].get(event_type, 0) + 1
        cell["total_events"] += 1
        cell["event_ids"].append(int(row["event_id"]))

    return binned


# ---------------------------------------------------------------------------
# GridCellRepository -- upserts rows into grid_cells table
# ---------------------------------------------------------------------------

class GridCellRepository:
    """Repository for grid_cells table operations.

    Handles upserting grid-cell convergence statistics with PostGIS
    polygon geometry (ST_MakeEnvelope).
    """

    def __init__(self, conn) -> None:
        self._conn = conn
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Ensure alert_level column exists on grid_cells (idempotent)."""
        with self._conn.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE grid_cells ADD COLUMN IF NOT EXISTS alert_level TEXT"
            )
            cursor.execute(
                "ALTER TABLE event_hotspot ADD COLUMN IF NOT EXISTS is_noise BOOLEAN DEFAULT false"
            )
        self._conn.commit()

    @staticmethod
    def _parse_cell_id(cell_id: str) -> tuple[int, int]:
        """Extract floor lat/lon from cell_id string.

        '1x1_LAT48_LON2' -> (48, 2)
        '1x1_LAT-5_LON-30' -> (-5, -30)
        """
        parts = cell_id.split("_")
        lat = int(parts[1].replace("LAT", ""))
        lon = int(parts[2].replace("LON", ""))
        return lat, lon

    def upsert_cells(self, binned: dict) -> int:
        """Upsert grid_cells rows from binned data.

        Uses ST_MakeEnvelope(lon, lat, lon+1, lat+1, 4326) for cell_geom.
        ON CONFLICT (cell_id) DO UPDATE refreshes counts, scores, and alert_level.

        Args:
            binned: Output from bin_to_grid().

        Returns:
            Number of cells upserted.
        """
        with self._conn.cursor() as cursor:
            count = 0
            for cell_id, data in binned.items():
                lat, lon = self._parse_cell_id(cell_id)
                unique_types = len(data["type_counts"])
                total_events = data["total_events"]
                conv_score = compute_convergence_score(unique_types, total_events)
                alert_level = classify_alert_level(conv_score, unique_types)

                cursor.execute(
                    """
                    INSERT INTO grid_cells (
                        cell_id, cell_geom, event_type_count, total_events,
                        convergence_score, alert_level, updated_at
                    ) VALUES (
                        %s, ST_MakeEnvelope(%s, %s, %s, %s, 4326),
                        %s, %s, %s, %s, NOW()
                    )
                    ON CONFLICT (cell_id) DO UPDATE SET
                        event_type_count = EXCLUDED.event_type_count,
                        total_events = EXCLUDED.total_events,
                        convergence_score = EXCLUDED.convergence_score,
                        alert_level = EXCLUDED.alert_level,
                        updated_at = NOW()
                    """,
                    (
                        cell_id, lon, lat, lon + 1, lat + 1,
                        unique_types, total_events, conv_score, alert_level,
                    ),
                )
                count += 1
        self._conn.commit()
        return count

    def get_active_cells(self, min_score: float = 1.0) -> list[str]:
        """Return cell_ids that have convergence_score >= threshold.

        Args:
            min_score: Minimum convergence score to consider active.

        Returns:
            List of active cell_id strings.
        """
        with self._conn.cursor() as cursor:
            cursor.execute(
                "SELECT cell_id FROM grid_cells WHERE convergence_score >= %s",
                (min_score,),
            )
            return [row[0] for row in cursor.fetchall()]


# ---------------------------------------------------------------------------
# Haversine distance & DBSCAN helpers
# ---------------------------------------------------------------------------

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = lat2_rad - lat1_rad
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def build_distance_matrix(events_df: pd.DataFrame, max_time_diff_h: float = 1) -> np.ndarray:
    event_count = len(events_df)
    matrix = np.full((event_count, event_count), np.inf, dtype=float)
    np.fill_diagonal(matrix, 0.0)
    if event_count == 0:
        return matrix

    times = pd.to_datetime(events_df["event_date"], utc=True)
    lats = events_df["ActionGeo_Lat"].astype(float).to_numpy()
    lons = events_df["ActionGeo_Long"].astype(float).to_numpy()

    for i in range(event_count):
        for j in range(i + 1, event_count):
            dt_hours = abs((times.iloc[i] - times.iloc[j]).total_seconds()) / 3600.0
            if dt_hours > max_time_diff_h:
                continue
            distance = haversine_km(lats[i], lons[i], lats[j], lons[j])
            matrix[i, j] = distance
            matrix[j, i] = distance
    return matrix


def cluster_dbscan(
    dist_matrix: np.ndarray, eps_km: float = 50, min_samples: int = 3
) -> np.ndarray:
    matrix = np.array(dist_matrix, dtype=float, copy=True)
    if matrix.size == 0:
        return np.array([], dtype=int)
    finite_max = np.nanmax(matrix[np.isfinite(matrix)]) if np.isfinite(matrix).any() else 0
    matrix[~np.isfinite(matrix)] = max(finite_max + eps_km + 1.0, eps_km * 10)
    model = DBSCAN(eps=eps_km, min_samples=min_samples, metric="precomputed")
    return model.fit_predict(matrix)


# ---------------------------------------------------------------------------
# ClusterRepository -- persists hotspots and event-hotspot links
# ---------------------------------------------------------------------------

class ClusterRepository:
    def __init__(self, conn) -> None:
        self._conn = conn

    def save_clusters(
        self,
        events_df: pd.DataFrame,
        labels: np.ndarray,
        cell_id: str | None = None,
    ) -> dict[str, int]:
        """Persist clusters as hotspots with event links.

        When cell_id is provided (new per-cell DBSCAN mode):
          - Centroid computed via PostGIS ST_Centroid(ST_Collect(point_geom))
          - cell_id FK included in INSERT
          - unique_event_types derived from classify_event_type
          - Noise points inserted into event_hotspot with is_noise=true
          - convergence_score and alert_level NOT stored (in grid_cells only)

        When cell_id is None (backward-compat single-stage mode):
          - Centroid computed as Python mean of member coordinates
          - No cell_id FK, no unique_event_types, no noise handling

        Args:
            events_df: DataFrame with event_id, ActionGeo_Lat, ActionGeo_Long,
                       event_date, SOURCEURL, source_system, cameo_code columns.
            labels: Cluster labels from DBSCAN (-1 = noise).
            cell_id: Optional grid cell ID FK (new per-cell mode).

        Returns:
            Dict with hotspot_count and linked_events counts.
        """
        if len(events_df) != len(labels):
            raise ValueError("events_df and labels length mismatch")

        working_df = events_df.copy()
        working_df["cluster_label"] = labels
        clustered = working_df[working_df["cluster_label"] >= 0]
        if clustered.empty:
            return {"hotspot_count": 0, "linked_events": 0}

        hotspot_count = 0
        linked_rows = 0
        hotspot_ids: list[int] = []

        with self._conn.cursor() as cursor:
            for label, group in clustered.groupby("cluster_label"):
                group_event_ids = [int(eid) for eid in group["event_id"].tolist()]

                if cell_id is not None:
                    # -- Per-cell DBSCAN mode: PostGIS centroid --
                    centroid_lon, centroid_lat = self._compute_postgis_centroid(
                        cursor, group_event_ids
                    )
                    unique_event_types = len({
                        classify_event_type(row)
                        for _, row in group.iterrows()
                    })
                else:
                    # -- Backward-compat: Python mean centroid --
                    centroid_lat = float(group["ActionGeo_Lat"].astype(float).mean())
                    centroid_lon = float(group["ActionGeo_Long"].astype(float).mean())
                    unique_event_types = 0

                hotspot_name = name_hotspot(self._conn, centroid_lat, centroid_lon)
                radius_km = max(
                    haversine_km(
                        centroid_lat,
                        centroid_lon,
                        float(row["ActionGeo_Lat"]),
                        float(row["ActionGeo_Long"]),
                    )
                    for _, row in group.iterrows()
                )
                unique_sources = len(
                    {
                        _source_key(value)
                        for value in group.get("SOURCEURL", pd.Series(dtype=object))
                        if pd.notna(value)
                    }
                )
                start_window = pd.to_datetime(group["event_date"], utc=True).min().to_pydatetime()
                end_window = pd.to_datetime(group["event_date"], utc=True).max().to_pydatetime()

                # Build INSERT with or without cell_id
                columns = [
                    "centroid_geom",
                    "radius_km",
                    "start_window",
                    "end_window",
                    "event_count",
                    "unique_sources",
                    "unique_event_types",
                    "name",
                ]
                values = [
                    centroid_lon,
                    centroid_lat,
                    radius_km,
                    start_window,
                    end_window,
                    int(len(group)),
                    int(unique_sources),
                    unique_event_types,
                    hotspot_name,
                ]
                placeholders = [
                    "ST_SetSRID(ST_MakePoint(%s, %s), 4326)",
                    "%s",
                    "%s",
                    "%s",
                    "%s",
                    "%s",
                    "%s",
                    "%s",
                ]

                if cell_id is not None:
                    columns.append("cell_id")
                    values.append(cell_id)
                    placeholders.append("%s")

                columns_sql = ", ".join(columns)
                values_sql = ", ".join(placeholders)

                cursor.execute(
                    f"""
                    INSERT INTO hotspots ({columns_sql})
                    VALUES ({values_sql})
                    RETURNING hotspot_id
                    """,
                    values,
                )
                hotspot_id = cursor.fetchone()[0]
                hotspot_ids.append(int(hotspot_id))
                # Event-hotspot links (non-noise)
                event_links = [(int(event_id), int(hotspot_id)) for event_id in group_event_ids]
                execute_values(
                    cursor,
                    """
                    INSERT INTO event_hotspot (event_id, hotspot_id)
                    VALUES %s
                    ON CONFLICT (event_id, hotspot_id) DO NOTHING
                    """,
                    event_links,
                )
                linked_rows += len(event_links)
                hotspot_count += 1

            # Noise handling (per-cell DBSCAN mode only)
            if cell_id is not None:
                noise = working_df[working_df["cluster_label"] == -1]
                if not noise.empty:
                    # Get a hotspot_id for noise points -- use the first hotspot
                    # created in this cell, or create a placeholder. Per spec,
                    # noise points are associated to the hotspot with is_noise=true.
                    # We re-query the latest hotspot for this cell.
                    cursor.execute(
                        "SELECT hotspot_id FROM hotspots WHERE cell_id = %s ORDER BY hotspot_id DESC LIMIT 1",
                        (cell_id,),
                    )
                    row = cursor.fetchone()
                    if row:
                        noise_hotspot_id = row[0]
                        noise_links = [
                            (int(eid), int(noise_hotspot_id), True)
                            for eid in noise["event_id"].tolist()
                        ]
                        execute_values(
                            cursor,
                            """
                            INSERT INTO event_hotspot (event_id, hotspot_id, is_noise)
                            VALUES %s
                            ON CONFLICT (event_id, hotspot_id) DO NOTHING
                            """,
                            noise_links,
                        )

        self._conn.commit()
        return {"hotspot_count": hotspot_count, "linked_events": linked_rows, "hotspot_ids": hotspot_ids}

    @staticmethod
    def _compute_postgis_centroid(cursor, event_ids: list[int]) -> tuple[float, float]:
        """Compute centroid via PostGIS ST_Centroid(ST_Collect(point_geom)).

        Ensures correctness near antimeridian and polar regions,
        where a Python coordinate mean would produce incorrect results.

        Args:
            cursor: Database cursor.
            event_ids: List of event IDs in the cluster.

        Returns:
            Tuple of (centroid_lon, centroid_lat) as floats.
        """
        cursor.execute(
            """
            SELECT ST_X(ST_Centroid(ST_Collect(point_geom))),
                   ST_Y(ST_Centroid(ST_Collect(point_geom)))
            FROM events
            WHERE event_id = ANY(%s)
            """,
            (event_ids,),
        )
        row = cursor.fetchone()
        if row is None or row[0] is None or row[1] is None:
            return (0.0, 0.0)
        return (float(row[0]), float(row[1]))


def _source_key(source_url: str) -> str:
    parsed = urlparse(str(source_url))
    return parsed.netloc.lower() if parsed.netloc else str(source_url).lower()


# ---------------------------------------------------------------------------
# Data-loading helpers
# ---------------------------------------------------------------------------

def load_recent_events(conn, lookback_hours: int | None = None) -> pd.DataFrame:
    """Load events from the DBSCAN window for clustering.

    Args:
        conn: Database connection.
        lookback_hours: Look-back window in hours. Defaults to
                        SENTINEL_DBSCAN_WINDOW_HOURS env var (or 2).

    Returns:
        DataFrame with event_id, ActionGeo_Lat, ActionGeo_Long, event_date,
        SOURCEURL, plus source_system and cameo_code for type classification.
    """
    if lookback_hours is None:
        lookback_hours = int(os.getenv("SENTINEL_DBSCAN_WINDOW_HOURS", "2"))

    query = """
        SELECT
            event_id,
            ST_Y(point_geom) AS "ActionGeo_Lat",
            ST_X(point_geom) AS "ActionGeo_Long",
            event_date,
            url AS "SOURCEURL",
            source_system,
            cameo_code
        FROM events
        -- GDELT event_date is day-granular (midnight UTC), so current-day
        -- events can be nominally ahead of NOW(); allow a 1-day tolerance on
        -- the upper bound while still excluding far-future records.
        WHERE event_date < NOW() + INTERVAL '1 day'
          AND event_date >= NOW() - (%s || ' hours')::interval
        ORDER BY event_date DESC
    """
    events_df = pd.read_sql_query(query, conn, params=[int(lookback_hours)])
    if events_df.empty:
        return events_df
    deduped = events_df.drop_duplicates(subset=["event_id"])
    deduped["event_date"] = pd.to_datetime(deduped["event_date"], utc=True)
    return deduped.reset_index(drop=True)


def load_events_for_convergence(conn, lookback_hours: int | None = None) -> pd.DataFrame:
    """Load events from the convergence look-back window for grid-cell binning.

    Args:
        conn: Database connection.
        lookback_hours: Look-back window in hours. Defaults to
                        SENTINEL_LOOKBACK_HOURS env var (or 24).

    Returns:
        DataFrame with event_id, lat, lon, event_date, source_system,
        cameo_code, grid_cell_id columns.
    """
    if lookback_hours is None:
        lookback_hours = int(os.getenv("SENTINEL_LOOKBACK_HOURS", "24"))

    query = """
        SELECT
            event_id,
            ST_Y(point_geom) AS lat,
            ST_X(point_geom) AS lon,
            event_date,
            source_system,
            cameo_code,
            grid_cell_id
        FROM events
        -- GDELT event_date is day-granular (midnight UTC), so current-day
        -- events can be nominally ahead of NOW(); allow a 1-day tolerance on
        -- the upper bound while still excluding far-future records.
        WHERE event_date < NOW() + INTERVAL '1 day'
          AND event_date >= NOW() - (%s || ' hours')::interval
        ORDER BY event_date DESC
    """
    events_df = pd.read_sql_query(query, conn, params=[int(lookback_hours)])
    if events_df.empty:
        return events_df
    deduped = events_df.drop_duplicates(subset=["event_id"])
    deduped["event_date"] = pd.to_datetime(deduped["event_date"], utc=True)
    return deduped.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------

def run_clustering_pipeline(
    events_df: pd.DataFrame | None = None,
    conn=None,
    *,
    repository: ClusterRepository | None = None,
    eps_km: float = 50,
    min_samples: int = 3,
    max_time_diff_h: float = 1,
    lookback_hours: int | None = None,
    dbscan_window_hours: int | None = None,
) -> dict[str, int]:
    """Run the clustering pipeline.

    Two modes:

    1. Two-stage grid-cell convergence + per-cell DBSCAN (new):
       Call with conn=... (and events_df=None). Runs:
       Stage 1: Load 24h events -> bin_to_grid -> GridCellRepository upsert
                 -> identify active cells (convergence_score >= 1)
       Stage 2: For each active cell, load 2h events -> build_distance_matrix
                 -> cluster_dbscan -> ClusterRepository.save_clusters(cell_id=...)

    2. Single-stage global DBSCAN (backward compat):
       Call with events_df=... (and conn=None). Runs single-stage DBSCAN
       with the provided repository.

    Args:
        events_df: Events DataFrame for backward-compat single-stage mode.
        conn: Database connection for new two-stage mode.
        repository: ClusterRepository for backward-compat mode.
        eps_km: DBSCAN spatial epsilon in km.
        min_samples: DBSCAN minimum points per cluster.
        max_time_diff_h: Temporal penalty threshold in hours.
        lookback_hours: Convergence look-back window (default from env).
        dbscan_window_hours: DBSCAN micro-clustering window (default from env).

    Returns:
        Summary dict with hotspot_count, linked_events, noise_count, cells_processed.
    """
    # -- Two-stage grid-cell convergence + per-cell DBSCAN (new mode) --
    if conn is not None and events_df is None:
        if lookback_hours is None:
            lookback_hours = int(os.getenv("SENTINEL_LOOKBACK_HOURS", "24"))
        if dbscan_window_hours is None:
            dbscan_window_hours = int(os.getenv("SENTINEL_DBSCAN_WINDOW_HOURS", "2"))

        # Stage 1: Grid-cell convergence detection
        convergence_df = load_events_for_convergence(conn, lookback_hours=lookback_hours)
        if convergence_df.empty:
            return {
                "hotspot_count": 0,
                "linked_events": 0,
                "noise_count": 0,
                "cells_processed": 0,
            }

        binned = bin_to_grid(convergence_df)
        grid_repo = GridCellRepository(conn)
        cells_upserted = grid_repo.upsert_cells(binned)
        active_cells = grid_repo.get_active_cells(min_score=1.0)

        # Stage 2: Per-cell DBSCAN micro-clustering
        cluster_repo = ClusterRepository(conn)
        total_hotspots = 0
        total_linked = 0
        total_noise = 0

        for cell_id in active_cells:
            cell_events = _load_cell_events(conn, cell_id, lookback_hours=dbscan_window_hours)
            if len(cell_events) < min_samples:
                continue

            cell_events["ActionGeo_Lat"] = cell_events["lat"].astype(float)
            cell_events["ActionGeo_Long"] = cell_events["lon"].astype(float)
            cell_events["SOURCEURL"] = cell_events.get("url", pd.Series(dtype=object))

            dist_matrix = build_distance_matrix(cell_events, max_time_diff_h=max_time_diff_h)
            labels = cluster_dbscan(dist_matrix, eps_km=eps_km, min_samples=min_samples)
            cell_noise = int((labels == -1).sum())
            total_noise += cell_noise

            persisted = cluster_repo.save_clusters(cell_events, labels, cell_id=cell_id)
            total_hotspots += persisted.get("hotspot_count", 0)
            total_linked += persisted.get("linked_events", 0)

        return {
            "hotspot_count": total_hotspots,
            "linked_events": total_linked,
            "noise_count": total_noise,
            "cells_processed": cells_upserted,
        }

    # -- Single-stage global DBSCAN (backward compat mode) --
    if events_df is not None:
        if events_df.empty:
            return {"hotspot_count": 0, "linked_events": 0, "noise_count": 0}

        distance_matrix = build_distance_matrix(events_df, max_time_diff_h=max_time_diff_h)
        labels = cluster_dbscan(distance_matrix, eps_km=eps_km, min_samples=min_samples)
        noise_count = int((labels == -1).sum())

        summary = {"hotspot_count": 0, "linked_events": 0, "noise_count": noise_count}
        if repository is not None:
            persisted = repository.save_clusters(events_df, labels)
            summary["hotspot_count"] = int(persisted.get("hotspot_count", 0))
            summary["linked_events"] = int(persisted.get("linked_events", 0))
        return summary

    return {"hotspot_count": 0, "linked_events": 0, "noise_count": 0}


def cluster_single_cell(conn, cell_id: str, *, dbscan_window_hours=None,
                        eps_km=None, min_samples=None, max_time_diff_h=None) -> list[int]:
    """Run DBSCAN for one grid cell, persist hotspots, return new hotspot_ids.
    Extracted from run_clustering_pipeline so the clustering worker and the
    monolith share one code path (returns the ids it created)."""
    import os

    import pandas as pd  # noqa: F811
    dbscan_window_hours = dbscan_window_hours or int(os.getenv("SENTINEL_DBSCAN_WINDOW_HOURS", "2"))
    eps_km = eps_km or float(os.getenv("SENTINEL_DBSCAN_EPS_KM", "50"))
    min_samples = min_samples or int(os.getenv("SENTINEL_DBSCAN_MIN_SAMPLES", "3"))
    max_time_diff_h = max_time_diff_h or float(os.getenv("SENTINEL_MAX_TIME_DIFF_H", "1"))

    cell_events = _load_cell_events(conn, cell_id, lookback_hours=dbscan_window_hours)
    if len(cell_events) < min_samples:
        return []
    cell_events["ActionGeo_Lat"] = cell_events["lat"].astype(float)
    cell_events["ActionGeo_Long"] = cell_events["lon"].astype(float)
    cell_events["SOURCEURL"] = cell_events.get("url", pd.Series(dtype=object))
    dist = build_distance_matrix(cell_events, max_time_diff_h=max_time_diff_h)
    labels = cluster_dbscan(dist, eps_km=eps_km, min_samples=min_samples)
    persisted = ClusterRepository(conn).save_clusters(cell_events, labels, cell_id=cell_id)
    conn.commit()
    return list(persisted.get("hotspot_ids", []))



def _load_cell_events(conn, cell_id: str, lookback_hours: int = 2) -> pd.DataFrame:
    """Load events for a specific grid cell within the DBSCAN window.

    Args:
        conn: Database connection.
        cell_id: The grid cell ID to filter by.
        lookback_hours: Look-back window in hours.

    Returns:
        DataFrame with event_id, lat, lon, event_date, source_system,
        cameo_code, url, and grid_cell_id columns.
    """
    query = """
        SELECT
            event_id,
            ST_Y(point_geom) AS lat,
            ST_X(point_geom) AS lon,
            event_date,
            source_system,
            cameo_code,
            url,
            grid_cell_id
        FROM events
        WHERE grid_cell_id = %s
          -- GDELT event_date is day-granular (midnight UTC), so current-day
          -- events can be nominally ahead of NOW(); allow a 1-day tolerance.
          AND event_date < NOW() + INTERVAL '1 day'
          AND event_date >= NOW() - (%s || ' hours')::interval
        ORDER BY event_date DESC
    """
    df = pd.read_sql_query(query, conn, params=[cell_id, int(lookback_hours)])
    if df.empty:
        return df
    deduped = df.drop_duplicates(subset=["event_id"])
    deduped["event_date"] = pd.to_datetime(deduped["event_date"], utc=True)
    return deduped.reset_index(drop=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cluster recent events into hotspots")
    parser.add_argument(
        "--lookback-hours",
        type=int,
        default=None,
        help="Convergence look-back window in hours (default: SENTINEL_LOOKBACK_HOURS or 24)",
    )
    parser.add_argument(
        "--dbscan-window-hours",
        type=int,
        default=None,
        help="DBSCAN micro-clustering window in hours (default: SENTINEL_DBSCAN_WINDOW_HOURS or 2)",
    )
    parser.add_argument("--eps-km", type=float, default=50.0)
    parser.add_argument("--min-samples", type=int, default=3)
    parser.add_argument("--max-time-diff-h", type=float, default=1.0)
    parser.add_argument("--run-scoring", action="store_true")
    parser.add_argument("--run-llm", action="store_true")
    parser.add_argument("--llm-threshold", type=float, default=40.0)
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Use legacy single-stage global DBSCAN (without grid-cell convergence)",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    conn, pool = get_pooled_connection()
    try:
        if args.legacy:
            # Backward-compat: single-stage global DBSCAN
            events_df = load_recent_events(
                conn,
                lookback_hours=args.dbscan_window_hours,
            )
            repo = ClusterRepository(conn)
            summary = run_clustering_pipeline(
                events_df,
                repository=repo,
                eps_km=args.eps_km,
                min_samples=args.min_samples,
                max_time_diff_h=args.max_time_diff_h,
            )
        else:
            # New: two-stage grid-cell convergence + per-cell DBSCAN
            summary = run_clustering_pipeline(
                conn=conn,
                eps_km=args.eps_km,
                min_samples=args.min_samples,
                max_time_diff_h=args.max_time_diff_h,
                lookback_hours=args.lookback_hours,
                dbscan_window_hours=args.dbscan_window_hours,
            )

        scored = 0
        llm_processed = 0
        if args.run_scoring:
            scored = len(ScoringRepository(conn).score_all_hotspots())
        if args.run_llm:
            endpoint = os.getenv("NVIDIA_NIM_ENDPOINT", "")
            api_key = os.getenv("NVIDIA_NIM_API_KEY", "")
            model = os.getenv("NVIDIA_NIM_MODEL", "meta/llama-3.1-70b-instruct")
            if not endpoint or not api_key:
                raise RuntimeError("NVIDIA_NIM_ENDPOINT and NVIDIA_NIM_API_KEY are required")
            llm_result = verify_hotspots_with_llm(
                conn=conn,
                endpoint=endpoint,
                api_key=api_key,
                model=model,
                threshold=args.llm_threshold,
            )
            llm_processed = llm_result["processed"]
    finally:
        pool.return_connection(conn)

    print(
        "Hotspots: {hotspot_count}, linked events: {linked_events}, noise: {noise_count}".format(
            **summary
        )
    )
    if "cells_processed" in summary:
        print(f"Cells processed: {summary['cells_processed']}")
    if args.run_scoring:
        print(f"Scored hotspots: {scored}")
    if args.run_llm:
        print(f"LLM verified hotspots: {llm_processed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
