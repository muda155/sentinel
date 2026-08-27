Evaluation harness for the M6 Consistency Engine (specs.md 4.8, thesis chapter).

1. Run the pipeline until hotspots have claims.
2. `python -m eval.consistency.export_gold --limit 200 > gold.jsonl`
3. Hand-label `label_claim_ok` (claim faithful + atomic?) and `label_status_ok`
   (verdict correct?) for ~50 hotspots' worth of claims.
4. `python -m eval.consistency.score_gold gold.jsonl` -> extraction precision +
   verdict accuracy.
5. `python -m eval.consistency.inject` -> synthetic contradiction detection rate
   (requires the local NLI model, and the FR-26 embedder when the gate is on).

   It prints `planted_premise_detected` beside `detection_rate`. **Read that
   first.** It is the fraction of planted premises the NLI itself calls a
   contradiction; below the 0.8 floor the run warns, because a premise the
   model does not read as contradicting means every dispute counted came from
   the *other* evidence and the detection rate is measuring noise rather than
   the consensus algorithm. This is how the pre-M8 wording went unnoticed. Both
   numbers move with whatever claims are in the DB — re-measure, don't quote
   old runs.

## Weighting backtest (`snapshot.py` + `weight_backtest.py`)

Compares candidate `consistency_score` weighting formulas **fully offline** —
no LLM call, no NLI model, no GPU. `claim_evidence` persists the whole NLI
judgment matrix (`neutral` rows and sub-`SENTINEL_NLI_MIN_PROB` pairs
included), so `support`/`dispute` are recomputable from stored rows alone.

```bash
python -m eval.consistency.snapshot --out /tmp/snap
python -m eval.consistency.weight_backtest --snapshot /tmp/snap --out /tmp/report.json
```

- **Snapshot first, always.** The pipeline writes to `claims`, `claim_evidence`
  and `hotspots` on every tick, so two formulas measured minutes apart are
  measured on two datasets and the difference between them is unattributable.
  `snapshot.py` reads everything inside one `REPEATABLE READ` transaction;
  every variant must then be scored against that one directory.
- **`reproduces_published_score` is the gate.** If neither replayed formula
  returns `hotspots.consistency_score` for every measured hotspot, the
  reconstruction is wrong and no other number in the report means anything.
  Check it before reading any comparison. It reports **two** variants because
  a snapshot spanning a redeploy legitimately holds rows written by either:
  `shipped` (`C_capped_k1`, live since 2026-08-20) and `pre_2026_08_20`
  (`old`). The two agree exactly on any claim with no dispute mass, so a
  snapshot where both match perfectly just means nothing in it was contested.
  Rows still matching only `pre_2026_08_20` are stale, not wrong — they were
  written before the change and are rewritten on the hotspot's next pass.
- **Claims with `origin_domains IS NULL` are excluded, and so is every hotspot
  holding one.** Migration 023 defines NULL as "written before 023, cannot be
  verified"; reading it as an empty set lets a source corroborate itself.
  Dropping the claim but keeping its siblings would move the denominator
  instead of the score, so the hotspot goes whole. The count is in
  `diagnostics`; quote it with any distribution.
- **Read `monotonicity_counterfactual`, not just `monotonicity_real_pairs`.**
  Real claims are never matched on support, so a pair test always carries a
  residual, and on live data almost every dispute-carrying claim is classified
  `disputed` (value 0), where weight cannot change the numerator — the pair
  test then reports a near-perfect score for the broken formula. The
  counterfactual re-scores each real claim with its dispute mass removed and
  status held fixed, which is the only comparison with no residual.
- **`w*v` alone is not "contribution".** Weight enters the denominator too, so
  a variant can shrink numerator and denominator together and move nothing.
  `reference_score` mixes the claim against one fixed neutral claim and is the
  number that says what it does to a hotspot.
- `dispute_sweep` is the formula-level proof and is asserted in
  `tests/test_weight_backtest.py`: a variant is admissible only when both
  `w(dispute)` and `v(dispute)` are non-increasing. Either one rising makes the
  score rise for some sibling set, whatever today's data shows.
- The backtest does **not** move `detection_rate`. `inject.detection_rate`
  reads `ClaimVerdict.status`, which comes from the classification rule, not
  from the weighting — only a change to `dispute >= ratio * support` can move
  it, and that must be measured as a separate change.

## Report correlations (`score_correlations.py`)

Produces the two coefficients in the report's §4.5 table from **one** snapshot.

```bash
python -m eval.consistency.snapshot --out /tmp/snap
python -m eval.consistency.score_correlations --snapshot /tmp/snap
```

- Both rows come from the same capture on purpose. The pipeline rewrites
  hotspots and claims every tick, so a `conf ↔ convergence` figure measured at
  one moment and a `conf ↔ consistency` figure measured at another describe two
  different populations and the pair stops supporting the argument built on it.
  Between two captures four hours apart on 2026-08-20 the measured population
  moved from 180 to 208 hotspots.
- `consistency_score` is **recomputed**, never read from the column. Stored
  values carry whichever formula shipped when the row was last scored, so a
  column read straight after a formula change silently mixes two arithmetics.
  `harness_vs_shipped_disagreements` cross-checks the recomputation against
  `pipeline.consistency.hotspot_consistency_score` on every hotspot and must be
  0; the exit status is non-zero otherwise.
- `convergence_score` is joined from `grid_cells`, not read off `hotspots`.
  The two-stage worker path writes it to the cell — `hotspots.convergence_score`
  was NULL on all 1321 rows on 2026-08-20 — and the API reads
  `COALESCE(g.convergence_score, h.convergence_score, 0)`. Reading the hotspot
  column alone gives an empty sample and a `None` correlation.
- `conf_vs_consistency` uses the strict filter (every claim verifiable per
  migration 023). `conf_vs_consistency_stored_column_looser_filter` reports the
  looser filter the earlier published figure used — any row with both columns
  non-NULL — purely so the two sample sizes read as different criteria rather
  than as a discrepancy. Quote the strict one.
