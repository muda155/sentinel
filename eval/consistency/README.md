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
