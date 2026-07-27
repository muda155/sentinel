Evaluation harness for the M6 Consistency Engine (specs.md 4.8, thesis chapter).

1. Run the pipeline until hotspots have claims.
2. `python -m eval.consistency.export_gold --limit 200 > gold.jsonl`
3. Hand-label `label_claim_ok` (claim faithful + atomic?) and `label_status_ok`
   (verdict correct?) for ~50 hotspots' worth of claims.
4. `python -m eval.consistency.score_gold gold.jsonl` -> extraction precision +
   verdict accuracy.
5. `python -m eval.consistency.inject` -> synthetic contradiction detection rate
   (requires the local NLI model).
