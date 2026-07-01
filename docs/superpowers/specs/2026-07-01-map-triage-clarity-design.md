# Analyst Triage & Map Clarity — Design (M5)

**Date:** 2026-07-01
**Status:** Approved (brainstorm) — pending implementation
**Spec FRs:** FR-18, FR-19, FR-20 (specs.md §4.7)
**Owning DOX:** `frontend-next/AGENTS.md`, `api/AGENTS.md`

## Problem

Sentinel cuts noise *upstream* (the convergence gate) but gives the analyst **no way to triage downstream**. The dashboard is a single view — a map of hotspot markers — where every marker looks equally worth investigating. There is no filtering, no recency, no legend, and no "what changed." Analysts still scan an undifferentiated field of dots.

## Reference: World Monitor clarity techniques (adapted, not copied)

Approach credited to World Monitor (`koala73/worldmonitor`, AGPL-3.0); no code or data copied verbatim. Relevant techniques:

1. **Show less by default, on purpose** — only high-severity events get map markers; the rest stay scored/exported but off the map.
2. **Time is a first-class filter** — persistent `1h/6h/24h/48h/7d` control narrows to recent activity.
3. **"What's new" is visually distinct** — NEW tags / glow separate fresh signal from background.
4. **Explain the encoding** — a legend so color/severity is decodable at a glance.

## Scope

Center of gravity: **filter + de-clutter the map**, phased. Delivered as three independent phases; each stands alone and ships value.

- **Phase 1 (FR-18)** — Filter panel + legend + "showing X of Y" counter.
- **Phase 2 (FR-19)** — Default noise floor + optional marker clustering.
- **Phase 3 (FR-20)** — "What's new" highlighting since last visit.

Non-goals (this milestone): a separate list/table view, server-side filtering, keyword watchlists, anomaly/baseline deviation, source-muting modal, region theater panels. Captured as possible follow-ons.

## Architecture

### Data / API changes (small, shared by all phases)

The `Hotspot` payload currently lacks any timestamp. Two fields are added from the existing `hotspots` table (no migration needed — columns already exist):

- `end_window` (timestamptz) — latest event time in the cluster's window; the recency signal for the time filter (FR-18) .
- `created_at` (timestamptz) — row creation time; the "new since last visit" signal (FR-20).

Touch points:
- `api/queries.py` — add `h.end_window`, `h.created_at` to `fetch_hotspots`, `fetch_hotspot_by_id`, and the shared `_HOTSPOT_SELECT`.
- `api/schemas.py` — add `end_window: datetime` and `created_at: datetime` to `HotspotOut`.
- `frontend-next/lib/api.ts` — add `end_window: string; created_at: string;` to the `Hotspot` type.

Filtering stays **client-side** (data is bounded at limit 200). No new query params.

### Frontend refactor (enabling change)

`MapView` currently fetches hotspots and handles SSE internally, so nothing else can see or filter the list. Extract that into a hook:

- **`lib/useHotspots.ts`** — `useHotspots(token)` returns `{ hotspots }`; owns the initial fetch + SSE re-fetch (moved verbatim from `MapView`).
- **`app/page.tsx`** — calls `useHotspots`, holds filter state, computes the filtered list + counts, passes results down.
- **`MapView`** — becomes presentational: receives `hotspots` (already filtered) as a prop instead of fetching. `focus`, `extraLayers`, `onSelect` unchanged.

This gives each unit one job: hook = data, page = filter state + orchestration, MapView = render.

### Pure logic modules (TDD — tests first)

- **`lib/filters.ts`**
  - `type HotspotFilters = { minConf: number; alertLevels: Set<AlertLevel>; window: TimeWindow }`
  - `DEFAULT_FILTERS` — `minConf: 40`, all alert levels, `window: "all"` (the Phase-2 noise floor; see below).
  - `TIME_WINDOWS` — `["6h","24h","48h","7d","all"]` with hour values.
  - `passesFilter(h, filters, now): boolean` — AND of: `conf_score >= minConf`, `alertLevels.has(alert_level)`, and `window === "all" || Date(end_window) >= now - windowHours`.
  - `applyFilters(hotspots, filters, now)` → filtered array.
- **`lib/whatsnew.ts`**
  - `isNew(h, lastSeenISO): boolean` — `!lastSeen || Date(h.created_at) > Date(lastSeen)`.
  - `countNew(hotspots, lastSeenISO): number`.
  - `LAST_SEEN_KEY = "sentinel_hotspots_last_seen"`.

### Components

- **`components/FilterPanel.tsx`** — collapsible panel over the map (near existing toggles). Confidence slider (0–100, step 5), three alert-level checkboxes, time-window `<select>`, and a "Showing **X** of **Y**" counter. All strings via `useT()`; controlled by props from `page.tsx`. Includes a "Reset" affordance.
- **`components/Legend.tsx`** — decodes FR-13: three fill swatches (green >70 / yellow 40–70 / grey <40) labelled Confidence tiers, and two ring swatches (red = Critical, orange = High) labelled Alert level. Swatch colors come from `lib/colors.ts` (single source of truth). Collapsible; can share the FilterPanel container.

## Phase detail

### Phase 1 — Filter panel + legend (FR-18)

Filters applied in `page.tsx` via `applyFilters`. `MapView` renders the filtered list. Counter reflects `filtered.length` / `hotspots.length`. Legend always available. i18n keys added to `en.ts`/`vi.ts` (parity test enforced).

Acceptance: dragging confidence to 80 removes yellow/grey markers and updates the counter; unchecking "Medium" hides ringless markers; selecting "24h" hides hotspots whose `end_window` is older than 24h; the legend visibly matches marker colors.

### Phase 2 — Default noise floor + clustering (FR-19)

- **Noise floor:** `DEFAULT_FILTERS.minConf = 40` — grey (<40) markers are hidden on load, revealed by dragging the slider to 0. Deliberate, adjustable "show less on purpose." (A future refinement — always showing Critical/High regardless of confidence — is noted but out of scope; keeps the predicate a clean AND.)
- **Clustering (separable sub-step):** at low zoom, group nearby markers into a count badge that expands on zoom-in and, on click, zooms toward the cluster. Implemented with `supercluster` feeding a `ScatterplotLayer` (cluster circles) + `TextLayer` (counts) alongside the individual-hotspot layer. If clustering proves too heavy, Phase 2 still ships value via the noise floor + existing z-ordering — clustering can be deferred without breaking the phase.

Acceptance: first load shows no grey markers and the counter reflects the hidden count; at world zoom, dense regions collapse to labelled cluster badges that expand on zoom-in.

### Phase 3 — What's new (FR-20)

- On mount, read `LAST_SEEN_KEY`; compute the "new" set via `whatsnew.ts`; then write `now()` back so the next visit compares against this one. SSE-added hotspots (created after mount) also count as new within the session.
- Visual: a translucent highlight `ScatterplotLayer` (larger radius, low opacity) rendered *under* the main markers for new hotspots, plus a "**N** new" chip in the FilterPanel. Optional "Mark all seen" clears the highlight.

Acceptance: a hotspot with `created_at` after the stored timestamp renders with the highlight and increments the "N new" chip; reloading after viewing clears it.

## Error handling

- Missing/invalid `end_window` or `created_at` → treat as "always passes time filter" / "not new" (never crash; fail open toward visibility).
- `localStorage` unavailable → `whatsnew` degrades to "nothing is new" (no highlight), no error.
- Filters that exclude everything → map is empty but the "Showing 0 of Y" counter makes it obvious; Reset restores defaults.

## Testing

- `lib/filters.ts` — vitest: default floor hides grey; slider/alert/window predicates; window boundary; malformed dates fail open.
- `lib/whatsnew.ts` — vitest: null lastSeen → all new; boundary equality; count.
- i18n parity — existing test covers new keys automatically.
- Backend — extend the `/hotspots` API test to assert `end_window` and `created_at` are present and ISO-formatted.

## DOX obligations

- Update `frontend-next/AGENTS.md`: new `useHotspots` hook, `filters.ts`/`whatsnew.ts`, `FilterPanel`/`Legend`, MapView now presentational, new `Hotspot` fields, `localStorage` key.
- Update `api/AGENTS.md`: `/hotspots` payload now includes `end_window`/`created_at`.
- Bump `specs.md` version and add the §4.7 FRs + revision-history row.
