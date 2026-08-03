# Ops — duplicate-URL collapse rollout (Phase 3)

GDELT emits one `events` row per extracted actor pair, so one article URL
becomes several rows. Before Phase 3 those rows each got their own FR-16
citation number, so a single report was cited several times and read as
independent corroboration.

`pipeline.citations.collapse_duplicate_urls` now collapses them. Stored
SITREPs generated before the change were numbered over the longer list, so
their `[N]` markers no longer resolve.

## Rollout, in order

1. Deploy the code (`docker compose up -d --build api frontend-next` plus the
   pipeline workers).
2. Dry run: `python -m scripts.invalidate_stale_sitreps`
3. Apply: `python -m scripts.invalidate_stale_sitreps --apply`
4. Wait one `SENTINEL_POLL_INTERVAL_S` cycle (default 900s). `llm_worker`
   picks the cleared hotspots up via `candidate_hotspots`, which gates on
   `NOT EXISTS` against `llm_summaries`, and `generate_sitrep` reruns the
   consistency engine (6a) and the SITREP (6b).
5. Spot-check a hotspot in the UI: the Sources list should show each article
   once, with an "N reports" badge where rows were collapsed, and every
   `[N]` in the SITREP should resolve to a list entry.

## Running it out of order

Applying the script **before** deploying the code is harmless but pointless —
the pipeline regenerates the same inflated numbering. Deploying without
running the script leaves 93% of stored SITREPs with dead citation links
until each hotspot naturally churns.
