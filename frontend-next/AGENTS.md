# DOX — frontend-next/

## Purpose

Next.js dual-map frontend (deck.gl + MapLibre GL + globe.gl) for the Sentinel OSINT dashboard. Replaces the deprecated Streamlit dashboard (`frontend/`). Consumes FastAPI REST + SSE endpoints.

## Ownership

All files in `frontend-next/`, including `lib/`, `components/`, `app/`, `__tests__/`, `e2e/`.

## Local Contracts

- **FR-13 visual contract:**
  - Hotspot marker fill encodes `conf_score`: **green > 70**, **yellow 40–70**, **grey < 40**.
  - Hotspot marker ring encodes `alert_level`: **red ring = Critical**, **orange ring = High**, **no ring = Medium**.
  - Clicking a marker shows both `conf_score` and `convergence_score` under **distinct labels** (Confidence = source reliability; Convergence = cross-domain co-occurrence).
- Grid-cell convergence heatmap is a toggleable overlay (`HeatmapLayer`).
- Globe.gl 3D view is a toggleable alternative to the flat map. `GlobeToggle.tsx` receives `hotspots` + `onSelect` props from `app/page.tsx` (never fetches); the earth texture is bundled at `public/textures/earth-night.jpg`; unmount disposes renderer/controls/GL context. FR-13 on globe = fill color for `conf_score`, altitude + radius for `alert_level` (`lib/globe-encoding.ts`); browsers without WebGL get a fallback message.
- All API calls go through `lib/api.ts` typed client — never raw `fetch` to the API base.
- Color mapping lives in `lib/colors.ts` — the single source of truth for FR-13 colors.
- i18n: all UI strings via `useT()` from `lib/i18n.tsx`; dictionaries in `lib/locales/` (vi default, key parity enforced by test). Place names, titles, SITREPs stay English.
- `SearchBar` (Cmd+K) calls `GET /search` via `api.search`; selection flies the map (`focus` prop on `MapView`) and opens `HotspotDetail`.
- `HotspotDetail` header uses `hotspot.name` (fallback `Hotspot #N`); sources list numbers match SITREP `[N]` via `citation_index` from `GET /hotspots/{id}/events`. When the summary text is empty, `lib/sitrep.ts:sitrepState()` decides the message: `below_threshold` (conf_score ≤ `LLM_THRESHOLD`, won't generate) vs `pending` (conf_score > threshold, awaiting LLM). `LLM_THRESHOLD` (40) mirrors `SENTINEL_LLM_THRESHOLD` and the `> threshold` gate in `pipeline/llm_verifier.py`.
- Detail panel error contract: summary/events fetch failures show `detail.error` + a retry button that re-fetches only the failed resource; every fetch result is guarded by its own per-resource generation counter (a single shared counter would invalidate earlier in-flight fetches on every load) so a stale response can never populate the panel (the panel is also remounted per hotspot via `key={hotspot_id}`); claims failures stay fail-hidden because `claims === null` also means "not evaluated".
- SSE stream handling lives in `lib/sse.ts` with exponential backoff (1s→30s, ±500ms jitter).
- Auth context in `lib/auth.tsx` wraps the app; `useAuth()` exposes `token`, `user`, `login()`, `logout()`, `isAdmin`.
- Login page at `/login`; unauthenticated users are redirected there from `/`.
- SSE lives in `lib/useHotspots.ts` (called from `app/page.tsx`), not in `MapView` — `connectHotspotStream` with the Bearer token, re-fetching hotspots on push events. It is page-level on purpose: toggling 2D/globe must not tear down the stream.
- Layout: `app/page.tsx` is a flex row — a `position:relative; flex:1; minWidth:0` map container (all overlay controls anchor to it) with `HotspotDetail` as a flex **sibling** column (340px, full height). The detail panel must never absolutely overlay the map: an overlay panel created a ~370×713px click dead zone that swallowed marker clicks and hid `FilterPanel`. First paint renders a dark loading skeleton while auth hydrates; `html, body` background is `#0d1117` so the pre-hydration and redirect gaps never flash white.
- `lib/useHotspots.ts` wraps SSE refetches in `trailingDebounce(fn, 3000)` (`lib/debounce.ts`, returns a `DebouncedFn` with `.cancel()`) — one refetch per burst, or `/hotspots` (60 req/min) 429s during pipeline ticks; the effect cleanup calls `.cancel()` so no refetch fires after unmount/token change.
- `TrustTierEditor` (admin-only) lists sources with dropdowns to PATCH `/sources/{id}` trust_tier.
- `api.ts` provides typed `sources()` and `updateTrustTier()` methods; all api methods accept `string | null` token.
- **FR-24**: Evidence & Consistency section in `HotspotDetail` (helpers in `lib/claims.ts`, hidden when `consistency_score` null and no claims; claim citation sups reuse `jumpTo`)
- SITREP citation parsing in `lib/citations.ts` renders `[N]` markers as superscript links.
- **FR-18**: `lib/filters.ts` provides `HotspotFilters`, `DEFAULT_FILTERS` (minConf=40), `passesFilter()`, `applyFilters()` — client-side filtering. `components/FilterPanel.tsx` renders confidence slider, alert-level checkboxes, and a time-window selector (`24h` / `3d` / `7d` / `30d`, default `7d`; `TIME_WINDOW_HOURS`/`TIME_WINDOW_LABEL` in `lib/filters.ts`). The server caps `/hotspots` at 30 days (`max_age_hours`), so the widest client window matches the server ceiling. `components/Legend.tsx` renders FR-13 color swatches inside a hover/focus tooltip behind a `?` affordance (i18n section labels `legend.fill`/`legend.ring`, `legend.title` on the button); `aria-expanded` + `role="tooltip"` for a11y.
- **FR-19**: `lib/clustering.ts` wraps supercluster (radius=60, maxZoom=12) behind `createClusterIndex()`/`getClusterData()`/`getExpansionZoom()` (supercluster type never leaks past this module — `HotspotClusterIndex`). `lib/useCluster.ts` hook returns `{clusters, leaves, getExpansionZoom}` for the current zoom and rebuilds the index only when the `hotspots` reference changes, so callers must pass a memoized array (`app/page.tsx` memoizes `applyFilters`). `MapView` renders cluster circles + `TextLayer` counts at zoom < 7, individual markers via `ScatterplotLayer` at all zooms, and clicking a cluster flies to its `getExpansionZoom()` level. Default basemap is Carto dark-matter via the `NEXT_PUBLIC_MAP_STYLE` override; fly-to zoom `FOCUS_ZOOM=6`, cluster expansion capped at `MAX_CLUSTER_ZOOM=10` (`docker-compose.yml` passes the same Carto URL as a build arg, so containerized builds match the dev default).
- **FR-20**: `lib/whatsnew.ts` provides `isNew()`, `countNew()`, `markSeen()`, `getLastSeen()` (localStorage key `sentinel_hotspots_last_seen`). `MapView` accepts `newHotspots` prop to render translucent highlight layer. `FilterPanel` accepts `newCount` prop to display "N new" chip + "Mark seen" button.
- **FR-24**: `lib/claims.ts` provides `orderClaims` (disputed first), `statusColor`, `statusLabelKey`, and `splitEvidence` (cited supporting vs contradicting). `HotspotDetail`'s "Evidence & Consistency" section names the disagreement per claim — "supported by [i] · contradicted by [j]" — with contradicting citations in red; hidden when `consistency_score` is null and there are no claims. `lib/clustering.ts` carries `consistency_score` through supercluster props so clustered markers keep it (hardcoding null hid the score at low zoom).
- Detail panel surfaces the data the payload already carries: per-event badges via `lib/severity.ts` (`source_system`/`event_type_label` only when the hotspot's events differ in them, `fatalities` when > 0, `num_sources` only when > 1, plus `goldstein_scale` intensity and `avg_tone`), a header aggregate (max fatalities labelled as a max, mean tone, and a `start_window`→`end_window` lifespan that collapses to a single date when both fall on the same day), NLI `probability` inline beside **contradicting** citations only (the title tooltip keeps it on all), and a 14-day activity sparkline (`lib/sparkline.ts` + `components/Sparkline.tsx`, inline SVG, no new dependency) shown only when events span more than one day. Severity styling must not reuse the FR-13 alert palette — `lib/colors.ts` stays the only source of alert/confidence colour. A leading "N reports" badge appears when `duplicate_count > 1` — GDELT emits one row per extracted actor pair, so the collapse is shown rather than applied silently. The search dropdown carries the same signal as `report_count` in the sublabel.
- Containerized via `Dockerfile` + `.dockerignore` for Docker Compose deployment.

## Work Guidance

- All new components go in `components/` as `"use client"` if they use browser APIs.
- Pure-logic modules go in `lib/` with corresponding tests in `__tests__/` (TDD).
- Component tests in `__tests__/` mock `@/lib/api`, `@/lib/auth`, `@/lib/i18n`, and `TrustTierEditor`; assert through the imported vi dict (`viLocale["detail.retry"]`) so copy edits in `lib/locales/` don't break assertions, and keep `@/lib/auth`'s token in a `vi.hoisted` object so a test can supersede an in-flight fetch (generation counter).
- Map-related components must be imported via `dynamic(..., { ssr: false })`.
- Do not import from `api/` (backend) — the frontend talks exclusively through the REST API.

## Verification

```bash
cd frontend-next && npm run build && npx vitest run
```
