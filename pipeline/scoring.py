from __future__ import annotations

import argparse
import math
import os
from collections import Counter

import pandas as pd

from pipeline.db import get_pooled_connection


def _density_divisor() -> float:
    return float(os.getenv("SENTINEL_CONF_DENSITY_DIVISOR", "3"))


def compute_source_density(trust_weights: list[float], divisor: float | None = None) -> float:
    if not trust_weights:
        return 0.0
    d = divisor if divisor is not None else _density_divisor()
    return float(math.tanh(sum(trust_weights) / d))


def geopolitical_diversity(country_codes: list[str]) -> float:
    values = [str(c).upper() for c in country_codes if c and str(c).strip()]
    unique = set(values)
    if len(unique) <= 1:
        return 0.0
    counts = Counter(values)
    total = sum(counts.values())
    entropy = 0.0
    for count in counts.values():
        p = count / total
        entropy -= p * math.log2(p)
    return float(entropy / math.log2(len(unique)))


def compute_conf_score(source_density: float, diversity: float) -> float:
    return float((0.6 * source_density + 0.4 * diversity) * 100)


def score_hotspot_from_events(events_df: pd.DataFrame) -> dict[str, float]:
    df = events_df
    if "domain" in df.columns and not df.empty:
        df = df.dropna(subset=["domain"]).drop_duplicates(subset=["domain"])
    trust_weights = [float(w) for w in df.get("trust_score", pd.Series(dtype=object)).tolist() if pd.notna(w)]
    countries = [v for v in df.get("country_code", pd.Series(dtype=object)).tolist()]
    source_density = compute_source_density(trust_weights)
    diversity = geopolitical_diversity(countries)
    return {
        "source_density": source_density,
        "geopolitical_diversity": diversity,
        "conf_score": compute_conf_score(source_density, diversity),
    }


class ScoringRepository:
    def __init__(self, conn) -> None:
        self._conn = conn

    def _fetch_hotspot_events(self, hotspot_id: int) -> pd.DataFrame:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT e.url, e.country_code, COALESCE(s.trust_score, 0.4) as trust_score
                FROM event_hotspot eh
                JOIN events e ON e.event_id = eh.event_id
                LEFT JOIN sources s ON e.source_id = s.source_id
                WHERE eh.hotspot_id = %s
                """,
                (hotspot_id,),
            )
            rows = cursor.fetchall()
        return pd.DataFrame(rows, columns=["url", "country_code", "trust_score"])

    def score_hotspot(self, hotspot_id: int) -> dict[str, float]:
        events_df = self._fetch_hotspot_events(hotspot_id)
        metrics = score_hotspot_from_events(events_df)
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE hotspots
                SET source_density = %s,
                    geopolitical_diversity = %s,
                    conf_score = %s
                WHERE hotspot_id = %s
                """,
                (
                    metrics["source_density"],
                    metrics["geopolitical_diversity"],
                    metrics["conf_score"],
                    hotspot_id,
                ),
            )
        self._conn.commit()
        return {"hotspot_id": hotspot_id, **metrics}

    def score_all_hotspots(self) -> list[dict[str, float]]:
        with self._conn.cursor() as cursor:
            cursor.execute("SELECT hotspot_id FROM hotspots ORDER BY hotspot_id")
            hotspot_ids = [row[0] for row in cursor.fetchall()]
        return [self.score_hotspot(int(hid)) for hid in hotspot_ids]


def score_hotspot(conn, hotspot_id: int) -> float | None:
    """Compute and persist conf_score for a single hotspot.

    Thin wrapper around ScoringRepository.score_hotspot so worker code
    shares one code path with the monolith. Returns conf_score or None."""
    repo = ScoringRepository(conn)
    result = repo.score_hotspot(hotspot_id)
    return float(result.get("conf_score", 0)) if result else None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compute consensus scores for hotspots")
    parser.add_argument("--hotspot-id", type=int, default=None)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    conn, pool = get_pooled_connection()
    try:
        repo = ScoringRepository(conn)
        if args.hotspot_id is not None:
            result = repo.score_hotspot(args.hotspot_id)
            print(f"Scored hotspot {result['hotspot_id']} conf={result['conf_score']:.2f}")
            return 0
        results = repo.score_all_hotspots()
        print(f"Scored {len(results)} hotspots")
    finally:
        pool.return_connection(conn)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
