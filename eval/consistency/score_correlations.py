"""Pearson/Spearman between the three scores, from one atomic snapshot (§4.5).

The thesis argues each score carries information the others do not, and proves
it with correlation coefficients. Those coefficients must come from a SINGLE
snapshot: the pipeline rewrites hotspots and claims every tick, so measuring
conf/convergence at one moment and conf/consistency at another compares two
different populations and the pair no longer supports the argument.

consistency_score is RECOMPUTED here rather than read from the column. Stored
values were written by whichever formula shipped when the row was last scored,
so a column read after a formula change mixes old and new arithmetic. The
recomputation is checked against pipeline.consistency.hotspot_consistency_score
on every hotspot, so what is reported is what the shipped code produces.

    python3 -m eval.consistency.score_correlations --snapshot <dir>
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from eval.consistency.weight_backtest import (
    SHIPPED_VARIANT,
    build_outcomes,
    hotspot_score,
    load_snapshot,
    pearson,
    spearman,
)
from pipeline.consistency import ClaimVerdict, hotspot_consistency_score


def _as_verdict(outcome) -> ClaimVerdict:
    """Outcome -> the ClaimVerdict the engine would have built for it."""
    return ClaimVerdict(
        text=outcome.text, status=outcome.status, support=outcome.support,
        dispute=outcome.dispute, weight=max(outcome.support + outcome.dispute, 0.1),
        evidence=[],
    )


def recompute(by_hotspot: dict) -> tuple[dict[int, float], int]:
    """consistency_score per hotspot, cross-checked against the shipped function.

    Returns the scores and the number of hotspots where the harness variant and
    pipeline.consistency disagree. That count must be 0 — a non-zero value means
    the harness has drifted from the code and no number below can be quoted."""
    scores: dict[int, float] = {}
    drift = 0
    for hotspot_id, outcomes in by_hotspot.items():
        harness = hotspot_score(outcomes, SHIPPED_VARIANT)
        shipped = hotspot_consistency_score([_as_verdict(o) for o in outcomes])
        if harness is None or shipped is None:
            continue
        if abs(harness - shipped) > 1e-9:
            drift += 1
        scores[hotspot_id] = shipped
    return scores, drift


def _pair(xs: list[float], ys: list[float]) -> dict:
    return {"pearson": pearson(xs, ys), "spearman": spearman(xs, ys), "n": len(xs)}


def _stored_pairs(hotspots: dict) -> tuple[list[float], list[float]]:
    """The published figure's filter: every row with both columns non-NULL.

    Mixes formulas after a change (each row carries whatever shipped when it was
    last scored) and includes claims with NULL origin_domains, so it is a
    provenance note, never the number to quote."""
    xs, ys = [], []
    for row in hotspots.values():
        if row["conf_score"] is not None and row["consistency_score"] is not None:
            xs.append(float(row["conf_score"]))
            ys.append(float(row["consistency_score"]))
    return xs, ys


def run(snapshot: Path) -> dict:
    snap = load_snapshot(snapshot)
    by_hotspot, diagnostics = build_outcomes(snap)
    scores, drift = recompute(by_hotspot)

    hotspots = snap["hotspots"]  # already keyed by hotspot_id

    # hotspots.convergence_score is NULL on every row; the live value is on the
    # grid cell the hotspot belongs to. Prefer the denormalised copy if it is
    # ever populated again, fall back to the cell.
    conf_conv_x, conf_conv_y = [], []
    for row in hotspots.values():
        convergence = row["convergence_score"]
        if convergence is None:
            convergence = row.get("cell_convergence_score")
        if row["conf_score"] is not None and convergence is not None:
            conf_conv_x.append(float(row["conf_score"]))
            conf_conv_y.append(float(convergence))

    conf_cons_x, conf_cons_y = [], []
    for hotspot_id, score in scores.items():
        row = hotspots.get(hotspot_id)
        if row is not None and row["conf_score"] is not None:
            conf_cons_x.append(float(row["conf_score"]))
            conf_cons_y.append(score)

    # The disagreement counts (§4.5) must come from this same snapshot as the
    # coefficients: they describe the same population, and a table pairing
    # counts from one tick with a coefficient from another contradicts itself.
    high_conv_low_conf = sum(
        1 for c, v in zip(conf_conv_x, conf_conv_y) if v >= 50.0 and c < 40.0)
    low_conv_high_conf = sum(
        1 for c, v in zip(conf_conv_x, conf_conv_y) if v < 50.0 and c >= 40.0)

    values = sorted(scores.values())
    landmarks = {
        str(h): (round(scores[h], 4) if h in scores else "not in snapshot")
        for h in (24795, 24783, 24874)
    }

    return {
        "snapshot": str(snapshot),
        "captured_at": snap["meta"]["captured_at"],
        "variant": SHIPPED_VARIANT,
        "harness_vs_shipped_disagreements": drift,
        "diagnostics": diagnostics,
        "conf_vs_convergence": _pair(conf_conv_x, conf_conv_y),
        "conf_vs_consistency": _pair(conf_cons_x, conf_cons_y),
        "disagreement_cases": {
            "convergence_high_conf_low": high_conv_low_conf,
            "convergence_low_conf_high": low_conv_high_conf,
            "comparable_hotspots": len(conf_conv_x),
            "conf_score_range": [round(min(conf_conv_x), 2), round(max(conf_conv_x), 2)]
                                if conf_conv_x else None,
            "convergence_range": [round(min(conf_conv_y), 2), round(max(conf_conv_y), 2)]
                                 if conf_conv_y else None,
        },
        # The published figure used a looser filter (any row with a stored
        # consistency_score), which admits hotspots this harness cannot
        # reproduce because their claims predate migration 023. Reported so the
        # two sample sizes are visibly different criteria, not a discrepancy.
        "conf_vs_consistency_stored_column_looser_filter": _pair(*_stored_pairs(hotspots)),
        "consistency_distribution": {
            "n": len(values),
            "min": round(min(values), 4) if values else None,
            "median": round(statistics.median(values), 4) if values else None,
            "mean": round(statistics.fmean(values), 4) if values else None,
            "max": round(max(values), 4) if values else None,
            "exactly_50": sum(1 for v in values if abs(v - 50.0) < 1e-9),
            "exactly_0": sum(1 for v in values if abs(v) < 1e-9),
        },
        "landmarks": landmarks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    report = run(args.snapshot)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 1 if report["harness_vs_shipped_disagreements"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
