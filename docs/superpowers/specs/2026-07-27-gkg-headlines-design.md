# Real Article Headlines via GDELT GKG — Design (M7)

**Date:** 2026-07-27
**Status:** Approved (brainstorm) — pending implementation
**Spec FR:** new FR-25 (GKG headline enrichment) — to be added to specs.md §4.9
**Owning DOX:** `pipeline/AGENTS.md` (primary), `tests/AGENTS.md`

## Problem

`events.title` stores GDELT's `Actor1Name`, not the article headline. A real evidence row rendered by the M6 consistency engine reads:

```
"THE US. Reported: THE US vs IRAN; Goldstein -7.2; tone -8.38; 1 reports."
```

There is no proposition there to corroborate or contradict. Measured consequence on live hotspot 24802 (2026-07-27): claim extraction produced zero valid claims, the engine skipped, and `consistency_score` stayed NULL. The M6 engine is correct — it honestly reports "not evaluated" — but it cannot do its job until evidence text contains actual statements. The same defect makes the dashboard's source list read `THE US`, `MILITARY OFFICIAL`, `IRAN`, and makes FR-15 full-text search index actor names instead of headlines.

## Source selection (measured, not assumed)

Two candidate sources were tested against live data before this design was written:

| Candidate | Result | Verdict |
|---|---|---|
| GDELT **DOC 2.0 API** (`api.gdeltproject.org/api/v2/doc/doc`) | Returns real headlines, but for a *different* slice of the corpus: **0/15 (0%)** of our stored URLs matched. Rate-limited to 1 req/5 s; 2 of 4 test queries returned HTTP errors. | **Rejected** |
| GDELT **GKG 2.1 bulk files** (`data.gdeltproject.org/gdeltv2/<TS>.gkg.csv.zip`) | Every row carries `<PAGE_TITLE>`. Same-timestamp join to the export file: **149/149 export URLs (100%)**, **40/40 military-event (CAMEO 14–19) URLs (100%)**. | **Adopted** |

GKG is GDELT's own published dataset on the same 15-minute cadence as the export file, listed in the same `lastupdate.txt`. It requires no API key, no subscription, and no rate limiting, and it is **not scraping** — a hard constraint from the M6 design (see `2026-07-27-consistency-engine-design.md`, Non-goals). ACLED remains unavailable (no subscription), so GKG is the only path to propositional evidence text on the current feed.

Sample headline for a military-coded event, versus what we store today:

- today: `"SOUTH KOREAN"`
- GKG: `"South Korea closely monitoring Russia's reported preparation for more North Korean troops"`

## Decisions taken (brainstorm outcomes)

1. **Overwrite `events.title`** with the headline rather than adding a column. FR-21 already stores actor names in `actor1_name`/`actor2_name`, so nothing is lost, and every existing consumer (evidence text, source list, search) improves with no code change.
2. **Same-tick paired download**: the ingestor fetches the GKG file for the timestamp it just fetched the export file for and sets `title` at INSERT time. No row is ever written with an actor-name title when GKG is available.
3. **Backfill the recent window** via CLI (default 7 days) so current hotspots become usable immediately.
4. **Headlines only.** Relevance filtering is deliberately out of scope pending measurement (see Non-goals).

## Architecture

No migration. `events.title` already exists; `events.title_tsv` is a `GENERATED ALWAYS ... STORED` column derived from `title` (migration 015), so overwriting a title automatically reindexes FR-15 search.

```
lastupdate.txt ──┬─> <TS>.export.CSV.zip ──> events (as today)
                 └─> <TS>.gkg.csv.zip ─────> {url: headline} ──> events.title at INSERT
```

### Component 1 — `pipeline/gkg.py` (new)

Single responsibility: turn a GDELT timestamp into a `{url: headline}` map. No DB access, no knowledge of events.

- `gkg_url_for(export_url: str) -> str` — replaces the `.export.CSV.zip` suffix with `.gkg.csv.zip` on the same timestamped path. Raises `ValueError` on a URL that is not a GDELT export URL.
- `parse_headlines(csv_text: str) -> dict[str, str]` — GKG 2.1 is tab-delimited with 27 columns; column index **4** is `DocumentIdentifier` (the URL) and column index **26** is `V2EXTRASXML`, which contains `<PAGE_TITLE>…</PAGE_TITLE>`. Rows without a parseable title are skipped, never raised on.
- `clean_headline(raw: str) -> str` — `html.unescape` (live data contains `&#x2013;`), collapse whitespace, strip a trailing site-name suffix matching `\s+[-–—|]\s+[^-–—|]{1,40}$` (observed: `" – Winnipeg Free Press"`), truncate to 300 characters. Applied per row by `parse_headlines`.
- `fetch_headlines(export_url: str, *, timeout: int | None = None) -> dict[str, str]` — derives the GKG URL, downloads, unzips in memory, parses. **Returns `{}` on any failure** (404/lag, timeout, bad zip, malformed CSV) after logging a warning; it never raises. Timeout from `SENTINEL_GKG_TIMEOUT_S` (default 120).
- Module CLI: `python -m pipeline.gkg --backfill --days 7` (see Component 3).

`csv.field_size_limit` must be raised — GKG `V2EXTRASXML` fields exceed Python's default field limit.

### Component 2 — `pipeline/ingestion.py` (modified)

`GDELT2Ingestor` gains an optional headline map threaded from fetch to insert:

- `run_once()` (and the `--insert-db` CLI path) calls `fetch_headlines(export_url)` after resolving the export URL, and stores the result on the ingestor instance.
- `_augment_records(records, url_to_source_id, headlines=None)` sets the title field to `headlines.get(url) or record[5]` where `record[5]` is `Actor1Name`. The `actor1_name` column continues to receive `record[5]` unchanged.
- `insert_to_db` / `insert_to_db_returning_ids` pass the map through. Signatures gain a keyword-only `headlines: dict[str, str] | None = None` defaulting to `None`, so every existing caller and test keeps working and falls back to actor-name titles.

Enrichment is opt-out via `SENTINEL_GKG_ENABLED` (default `true`) so a GKG outage can be switched off without a redeploy.

### Component 3 — Backfill CLI

`python -m pipeline.gkg --backfill --days N` (default 7, `--dry-run` supported):

1. Select distinct `url` from `events` where `source_system='GDELT'`, `event_date >= now() - N days`, and the row is **un-enriched**, defined as `(title IS NULL OR title !~ '[a-z]')` — GDELT actor names are ALL-CAPS, real headlines contain lowercase. This needs no schema change and is naturally idempotent: once a headline is written it contains lowercase and is never reprocessed.

   *Measured on live data (2026-07-27, 1,036 recent GDELT rows): the lowercase marker identifies **960** un-enriched rows with **0** false positives. The obvious alternative, `title = actor1_name`, finds only **253** — it misses the 783 rows ingested before FR-21 added `actor1_name`, which are exactly the rows most in need of backfill. Do not use it.*
2. Walk GKG files backwards from now in 15-minute steps over the window, building the map incrementally and `UPDATE events SET title = %s WHERE url = %s AND (title IS NULL OR title !~ '[a-z]')` in batches.
3. Report counts: files fetched, URLs matched, rows updated.

Uses `get_pooled_connection()` / `pool.return_connection(conn)` in a `finally` block per the root contract. A GKG file that 404s is skipped with a warning, not fatal.

### Error handling

| Failure | Behavior |
|---|---|
| GKG file lags/404s (observed: newest file served 0 bytes) | warn, `{}` map, titles fall back to `Actor1Name` — exactly today's behavior; ingestion completes |
| GKG download timeout or bad zip | same fallback |
| Row missing `<PAGE_TITLE>` or malformed | that row skipped; other rows still mapped |
| URL in export but not in GKG | falls back to `Actor1Name` for that row only |
| `SENTINEL_GKG_ENABLED=false` | GKG never fetched; pure pre-M7 behavior |

The invariant: **GKG enrichment can only improve a title, never block or fail an ingestion tick.**

### New environment variables

`SENTINEL_GKG_ENABLED` (default `true`), `SENTINEL_GKG_TIMEOUT_S` (default 120), `SENTINEL_GKG_BACKFILL_DAYS` (default 7). All added to `sentinel.env.example`.

## Downstream effects (no code changes required)

- **Consistency engine (FR-22)**: evidence text becomes `"South Korea closely monitoring Russia's reported preparation…"` instead of `"SOUTH KOREAN. Reported: …"`, so claim extraction and NLI judging finally have propositions to work with.
- **Dashboard (FR-16)**: the source list shows real headlines instead of `THE US`.
- **Search (FR-15)**: `title_tsv` regenerates automatically; search starts matching headline words.
- **SITREP (FR-11/FR-23)**: the headline-fallback prompt improves for free.

## Testing

- **Unit** (no network): `gkg_url_for` derivation and its `ValueError` on non-export URLs; `parse_headlines` on a fixture covering a normal row, an HTML-entity title, a row with no `PAGE_TITLE`, and a short/malformed row; `clean_headline` entity decoding, suffix stripping, whitespace collapse, truncation; `fetch_headlines` returning `{}` (not raising) when the download fails.
- **Ingestion**: `_augment_records` uses the headline when the map has the URL and falls back to `Actor1Name` when it does not; `insert_to_db` with a headline map writes the real title while `actor1_name` keeps the actor.
- **Regression**: the existing `tests/test_ingestion*.py` suite must pass **unchanged** — proving the default `headlines=None` path preserves current behavior.
- **Integration (live DB)**: backfill updates an un-enriched seeded row (ALL-CAPS title) and leaves an already-enriched row (headline containing lowercase) untouched, proving idempotency.
- **Verification (manual, recorded in the PR)**: run the backfill, re-run `python -m pipeline.consistency --hotspot-id <id>` on a live hotspot, and confirm claims are extracted and persisted where the same hotspot previously produced none.

## Non-goals (deliberate, revisit after measurement)

- **Relevance filtering.** GKG headlines expose that CAMEO 14–19 carries non-geopolitical noise (observed: *"rapper testifies in own rape trial"*, *"Newport man jailed after breaching begging ban outside Tesco"*) inside conflict hotspots, which can produce spurious contradictions. M7 ships headlines first and measures the impact; a filter is only justified by that measurement (candidate M8). Building it now would be a second unmeasured contribution and risks silently discarding real evidence.
- Article-body scraping / RAG over full text.
- ACLED ingestion changes (no subscription available).

## Risks

- **Bandwidth**: ~5 MB per 15-minute tick versus ~90 KB for the export file (~480 MB/day downloaded, parsed, and discarded — nothing extra is stored). Acceptable on the current single-host deployment; noted for any future metered deployment.
- **GKG lag**: the newest GKG file is occasionally unavailable when the export file is ready. Handled by fallback; a persistently lagging feed silently degrades to actor-name titles, which the backfill CLI can repair after the fact.
- **Suffix stripping is heuristic**: the regex may clip a legitimate trailing clause on rare headlines. Bounded to 40 characters after a dash/pipe to limit damage; truncation is preferred over leaving `" – Winnipeg Free Press"` noise in every NLI premise.
