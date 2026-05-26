from __future__ import annotations

import argparse
import math
from urllib.parse import urlparse

import numpy as np
import pandas as pd
from psycopg2.extras import execute_values
from sklearn.cluster import DBSCAN

from pipeline.db import get_pooled_connection
from pipeline.llm_verifier import verify_hotspots_with_llm
from pipeline.scoring import ScoringRepository


EARTH_RADIUS_KM = 6371.0088


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


class ClusterRepository:
    def __init__(self, conn) -> None:
        self._conn = conn

    def save_clusters(self, events_df: pd.DataFrame, labels: np.ndarray) -> dict[str, int]:
        if len(events_df) != len(labels):
            raise ValueError("events_df and labels length mismatch")

        working_df = events_df.copy()
        working_df["cluster_label"] = labels
        clustered = working_df[working_df["cluster_label"] >= 0]
        if clustered.empty:
            return {"hotspot_count": 0, "linked_events": 0}

        hotspot_count = 0
        linked_rows = 0

        with self._conn.cursor() as cursor:
            for label, group in clustered.groupby("cluster_label"):
                centroid_lat = float(group["ActionGeo_Lat"].astype(float).mean())
                centroid_lon = float(group["ActionGeo_Long"].astype(float).mean())
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

                cursor.execute(
                    """
                    INSERT INTO hotspots (
                        centroid_geom, radius_km, start_window, end_window, event_count, unique_sources
                    )
                    VALUES (ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s, %s, %s)
                    RETURNING hotspot_id
                    """,
                    (
                        centroid_lon,
                        centroid_lat,
                        radius_km,
                        start_window,
                        end_window,
                        int(len(group)),
                        int(unique_sources),
                    ),
                )
                hotspot_id = cursor.fetchone()[0]

                event_links = [(int(event_id), int(hotspot_id)) for event_id in group["event_id"].tolist()]
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

        self._conn.commit()
        return {"hotspot_count": hotspot_count, "linked_events": linked_rows}


def _source_key(source_url: str) -> str:
    parsed = urlparse(str(source_url))
    return parsed.netloc.lower() if parsed.netloc else str(source_url).lower()


def load_recent_events(conn, lookback_hours: int = 2) -> pd.DataFrame:
    query = """
        SELECT
            event_id,
            ST_Y(point_geom) AS "ActionGeo_Lat",
            ST_X(point_geom) AS "ActionGeo_Long",
            event_date,
            url AS "SOURCEURL"
        FROM events
        WHERE event_date <= NOW()
          AND event_date >= NOW() - (%s || ' hours')::interval
        ORDER BY event_date DESC
    """
    events_df = pd.read_sql_query(query, conn, params=[int(lookback_hours)])
    if events_df.empty:
        return events_df
    deduped = events_df.drop_duplicates(subset=["event_id"])
    deduped["event_date"] = pd.to_datetime(deduped["event_date"], utc=True)
    return deduped.reset_index(drop=True)


def run_clustering_pipeline(
    events_df: pd.DataFrame,
    repository: ClusterRepository | None = None,
    eps_km: float = 50,
    min_samples: int = 3,
    max_time_diff_h: float = 1,
) -> dict[str, int]:
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cluster recent events into hotspots")
    parser.add_argument("--lookback-hours", type=int, default=2)
    parser.add_argument("--eps-km", type=float, default=50.0)
    parser.add_argument("--min-samples", type=int, default=3)
    parser.add_argument("--max-time-diff-h", type=float, default=1.0)
    parser.add_argument("--run-scoring", action="store_true")
    parser.add_argument("--run-llm", action="store_true")
    parser.add_argument("--llm-threshold", type=float, default=40.0)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    conn, pool = get_pooled_connection()
    try:
        events_df = load_recent_events(conn, lookback_hours=args.lookback_hours)
        repo = ClusterRepository(conn)
        summary = run_clustering_pipeline(
            events_df,
            repository=repo,
            eps_km=args.eps_km,
            min_samples=args.min_samples,
            max_time_diff_h=args.max_time_diff_h,
        )
        scored = 0
        llm_processed = 0
        if args.run_scoring:
            scored = len(ScoringRepository(conn).score_all_hotspots())
        if args.run_llm:
            import os

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
    if args.run_scoring:
        print(f"Scored hotspots: {scored}")
    if args.run_llm:
        print(f"LLM verified hotspots: {llm_processed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
