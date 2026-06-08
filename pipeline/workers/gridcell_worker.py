"""Grid-Cell worker: ingested_events -> upsert grid_cells -> convergence_zone_detected.
Reuses pipeline.clustering.bin_to_grid + GridCellRepository (monolith Step 3)."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from pipeline.clustering import (
    bin_to_grid,
    classify_alert_level,
    compute_convergence_score,
    load_events_for_convergence,
    GridCellRepository,
)
from pipeline.db import get_pooled_connection
from pipeline.streams import StreamBus
from pipeline.workers.base import Worker


class GridCellWorker(Worker):
    in_stream = "sentinel:ingested_events"
    group = "cg:gridcell"
    out_stream = "sentinel:convergence_zone_detected"

    def handle(self, msg_id, data):
        lookback = int(os.getenv("SENTINEL_LOOKBACK_HOURS", "24"))
        conn, pool = get_pooled_connection()
        try:
            events_df = load_events_for_convergence(conn, lookback_hours=lookback)
            if events_df.empty:
                return []
            binned = bin_to_grid(events_df)
            GridCellRepository(conn).upsert_cells(binned)
            conn.commit()
        finally:
            pool.return_connection(conn)
        out = []
        for cell_id, cell in binned.items():
            unique_types = len(cell.get("type_counts", {}))
            total_events = cell.get("total_events", 0)
            score = compute_convergence_score(unique_types, total_events)
            if score >= 1:
                out.append({
                    "cell_id": cell_id,
                    "convergence_score": float(score),
                    "ts": datetime.now(timezone.utc).isoformat(),
                })
        return out


def main() -> int:  # pragma: no cover
    GridCellWorker().run_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
