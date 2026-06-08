"""Clustering worker: convergence_zone_detected -> per-cell DBSCAN -> hotspot_created.
Reuses pipeline.clustering.cluster_single_cell (shared with the monolith)."""

from __future__ import annotations

from datetime import datetime, timezone

from pipeline.clustering import cluster_single_cell
from pipeline.db import get_pooled_connection
from pipeline.workers.base import Worker


class ClusteringWorker(Worker):
    in_stream = "sentinel:convergence_zone_detected"
    group = "cg:clustering"
    out_stream = "sentinel:hotspot_created"

    def handle(self, msg_id, data):
        cell_id = data["cell_id"]
        conn, pool = get_pooled_connection()
        try:
            hotspot_ids = cluster_single_cell(conn, cell_id)
            out = []
            for hid in hotspot_ids:
                row = self._hotspot_centroid(conn, hid)
                out.append({
                    "hotspot_id": hid, "cell_id": cell_id,
                    "lat": row[0], "lon": row[1],
                    "ts": datetime.now(timezone.utc).isoformat(),
                })
            return out
        finally:
            pool.return_connection(conn)

    @staticmethod
    def _hotspot_centroid(conn, hotspot_id: int):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ST_Y(centroid_geom), ST_X(centroid_geom) FROM hotspots WHERE hotspot_id=%s",
                (hotspot_id,),
            )
            return cur.fetchone()


def main() -> int:  # pragma: no cover
    ClusteringWorker().run_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
