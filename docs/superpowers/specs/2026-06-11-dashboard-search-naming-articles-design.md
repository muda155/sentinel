# Dashboard Usability: Hotspot Naming, Search, and Source Articles

**Date:** 2026-06-11
**Status:** Approved design, pending implementation plan
**Prior art:** World Monitor (`koala73/worldmonitor`, AGPL-3.0) — naming approach in
`src/services/geo-convergence.ts`, search UX in `src/components/SearchModal.ts`.
Sentinel re-implements the *approach* (layered curated-place naming, grouped
search results); no World Monitor code or data is copied verbatim.

## Problem

The dashboard labels every hotspot "Hotspot #N" with no location context, offers
no search, and never surfaces the source articles that events already carry
(`events.title`, `events.url` are stored but unused by the UI).

## Goals

1. Every hotspot has a human-readable name, e.g. **"Donbas, Ukraine"**, with a
   sentence-style subtitle: *"armed clashes + military conflict — 23 events/24h"*.
2. A search box (always visible above the map, focusable with **Cmd+K / Ctrl+K**)
   finds hotspots by name/country, articles by full-text title match, and
   sources by domain.
3. The hotspot detail panel lists source articles, numbered to match the
   SITREP's `[N]` citations; clicking a citation highlights the article.
4. The UI is bilingual: **Vietnamese by default** with an EN/VI toggle. All
   dashboard chrome (labels, buttons, headings, event-type labels) is
   translated; place names, article titles, and SITREPs remain English.

Out of scope: place fly-to for arbitrary cities, fuzzy/trigram matching,
non-English full-text search, LLM-generated hotspot titles, Vietnamese
SITREPs, localized place names.

## Component 1 — Hotspot naming

### New module `pipeline/naming.py`

- `CURATED_PLACES`: a Python list of ~30–40 entries
  `{id, name, lat, lon, radius_km, kind}` where `kind` is `conflict_zone`
  (radius 300), `waterway` (radius 200), or `strategic_city` (radius 150).
  We author our own list scoped to CAMEO 14–19 relevance (active conflict
  zones, strategic straits, frequently-reported cities). World Monitor's
  category structure is credited in the thesis; entries are written fresh.
- `TYPE_LABELS`: `military_conflict → "military conflict"`,
  `armed_conflict → "armed clashes"`, `civilian_violence → "violence against
  civilians"`, `civil_unrest → "protests"`, `unknown → "unclassified"`.
- `name_hotspot(conn, lat, lon) -> str` — layered resolution:
  1. Nearest `CURATED_PLACES` entry whose `radius_km` contains the point
     (checked in kind order: conflict_zone, waterway, strategic_city).
  2. Existing `pipeline.geocode.reverse_geocode_country()` → country name.
  3. `f"{lat:.1f}°, {lon:.1f}°"` as last resort.
  When step 1 hits and step 2 returns a different country name, the stored
  name is `"<place>, <country>"`; otherwise just the single name.

### Persistence

- Migration `db/init/012_hotspot_names.sql`:
  `ALTER TABLE hotspots ADD COLUMN IF NOT EXISTS name text;`
  plus `CREATE INDEX IF NOT EXISTS idx_hotspots_name_lower ON hotspots (lower(name) text_pattern_ops);`
- The clustering write path (`ClusterRepository`) calls `name_hotspot()` when
  inserting/updating a hotspot. One-time backfill:
  `python -m pipeline.naming --backfill` updates rows where `name IS NULL`.
- `api/schemas.py` `Hotspot` gains `name: str | None`; `queries.fetch_hotspots`
  selects it. Frontend `lib/api.ts` `Hotspot` type gains `name`.

### Display

- `HotspotDetail` header becomes the name (falls back to `Hotspot #N` if null).
- Subtitle is derived client-side from the articles fetch (Component 3):
  distinct event-type labels joined with " + ", plus event count and window.

## Component 2 — Search

### API: `GET /search?q=<text>&limit=<n>` (auth + rate-limited like `/events`)

Returns `{"hotspots": [...], "events": [...], "sources": [...]}`:

- **hotspots** (≤10): `name ILIKE '%q%'` over `hotspots` (uses the
  `lower(name)` index for prefix queries; table is small). Each row: hotspot
  id, name, lat, lon, conf_score, alert_level.
- **events** (≤10): Postgres FTS. Migration `db/init/013_events_fts.sql` adds
  a stored generated column
  `title_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(title,''))) STORED`
  with a GIN index (PG15 supports this on partitioned tables). Query uses
  `websearch_to_tsquery('english', q)`; rows join `event_hotspot` to return
  the owning `hotspot_id` (events without a hotspot are excluded). Each row:
  event id, title, url, domain, event_date, hotspot_id.
- **sources** (≤5): `domain ILIKE '%q%'` over `sources`, each with trust_tier
  and a count + id-list of hotspots citing it (join `events → event_hotspot`).

Empty `q` or `q` shorter than 2 chars returns all-empty groups.

### Frontend: `components/SearchBar.tsx`

- Always-visible input rendered above the map (top-center). **Cmd+K / Ctrl+K**
  focuses it from anywhere; **Esc** blurs and closes the dropdown. A subtle
  `⌘K` hint is shown inside the input.
- 250 ms debounce, then one call to `api.search(q, token)` (new typed method
  in `lib/api.ts`). Results render in a dropdown grouped under "Hotspots",
  "Articles", "Sources" headers; ArrowUp/ArrowDown/Enter keyboard navigation
  across groups.
- Selection behavior:
  - Hotspot → map flies to its coordinates and opens `HotspotDetail`.
  - Article → flies to its owning hotspot, opens `HotspotDetail`, and
    highlights that article row in the sources list.
  - Source → expands inline to that source's hotspots; selecting one behaves
    like a hotspot result.
- "No results" row when all groups are empty.

## Component 3 — Source articles in the detail panel

### API: `GET /hotspots/{id}/events` (auth + rate-limited; 404 if unknown id)

Returns the hotspot's events via `event_hotspot`:
`{event_id, title, url, domain, source_system, event_type_label, event_date,
trust_tier, trust_score, citation_index}`.

**Citation alignment:** the LLM prompt numbers its articles by position in
`LLMRepository.fetch_hotspot_articles()` — URL-bearing linked events ordered
`event_date DESC`. The endpoint therefore mirrors that query exactly (same
join, same URL filter, same ordering) and assigns `citation_index = 1..N` by
position, so `[N]` markers align by construction. Both queries gain an
`event_id DESC` tiebreaker so ordering is deterministic for equal timestamps.
Events without a URL are appended after the cited rows with
`citation_index = null`.

### Frontend: sources list in `HotspotDetail`

- Below the SITREP: **"Sources (N)"** — each row shows the citation number,
  article title linking to `url` (`target="_blank" rel="noopener noreferrer"`),
  domain, a trust-tier badge (reusing `lib/colors.ts` conventions), and date.
- Clicking a `[N]` superscript in the SITREP scrolls to and briefly flashes
  row N (extends the existing `parseCitations` rendering — the `sup` elements
  become buttons).
- Events without titles render the domain as the link text.

## Component 4 — Internationalization (Vietnamese default, EN toggle)

- New `frontend-next/lib/i18n.tsx`: `Locale = "vi" | "en"`, a `LocaleProvider`
  React context with `useT()` returning `{ t, locale, setLocale }`. Locale
  persists to `localStorage` key `sentinel_locale`; default is `"vi"`.
- Dictionaries in `frontend-next/lib/locales/vi.ts` and `en.ts` as flat
  typed key maps (e.g. `"detail.confidence"`, `"search.placeholder"`,
  `"eventType.armed_conflict"`). The `en.ts` key set is the source of truth;
  `vi.ts` must declare the same keys (enforced by a vitest test).
- `components/LanguageToggle.tsx`: small EN/VI switch rendered in the page
  header next to the existing controls.
- Event-type labels are translated client-side from the stored English type
  keys (`armed_conflict` → "giao tranh vũ trang"), so the DB and API stay
  English-only.
- Place names (`hotspots.name`), article titles, and SITREP text are **not**
  translated.

## Error handling

- `name_hotspot()` failures (geocode miss, DB error) log a warning and leave
  `name` null; UI falls back to `Hotspot #N`. Naming must never fail the
  clustering pipeline.
- `/search` with FTS syntax errors from `websearch_to_tsquery` is not a
  concern (it never raises on arbitrary input, unlike `to_tsquery`).
- SearchBar surfaces API errors as a "Search unavailable" row; map keeps working.

## Testing

- `tests/test_naming.py` — curated-place hit (inside/outside radius, nearest
  wins), country fallback, coordinate fallback, `"place, country"` composition,
  backfill idempotency.
- `tests/test_api_search.py` — grouped results, short-query guard, FTS title
  match routed to owning hotspot, source hotspot counts, auth required.
- `tests/test_api_hotspot_events.py` — citation_index alignment with
  `sources_cited`, noise exclusion, 404, ordering without SITREP.
- `frontend-next/__tests__/` (vitest, TDD per repo convention) — SearchBar
  debounce + keyboard navigation + grouping; citation click → row highlight
  wiring; api client methods; i18n dictionary key parity (vi covers every en
  key) and locale persistence.
- Verification: `pytest tests/` and `cd frontend-next && npm run build && npx vitest run`.

## Implementation order

1. Migrations 012/013 + `pipeline/naming.py` + backfill (names visible in API).
2. `/hotspots/{id}/events` + detail-panel sources list + header rename.
3. `/search` + SearchBar with Cmd+K.
4. i18n provider + dictionaries + LanguageToggle, then translate the chrome
   introduced in steps 2–3 alongside the existing UI.

Each step is independently shippable and demoable.
