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
- Globe.gl 3D view is a toggleable alternative to the flat map.
- All API calls go through `lib/api.ts` typed client — never raw `fetch` to the API base.
- Color mapping lives in `lib/colors.ts` — the single source of truth for FR-13 colors.
- i18n: all UI strings via `useT()` from `lib/i18n.tsx`; dictionaries in `lib/locales/` (vi default, key parity enforced by test). Place names, titles, SITREPs stay English.
- `SearchBar` (Cmd+K) calls `GET /search` via `api.search`; selection flies the map (`focus` prop on `MapView`) and opens `HotspotDetail`.
- `HotspotDetail` header uses `hotspot.name` (fallback `Hotspot #N`); sources list numbers match SITREP `[N]` via `citation_index` from `GET /hotspots/{id}/events`. When the summary text is empty, `lib/sitrep.ts:sitrepState()` decides the message: `below_threshold` (conf_score ≤ `LLM_THRESHOLD`, won't generate) vs `pending` (conf_score > threshold, awaiting LLM). `LLM_THRESHOLD` (40) mirrors `SENTINEL_LLM_THRESHOLD` and the `> threshold` gate in `pipeline/llm_verifier.py`.
- SSE stream handling lives in `lib/sse.ts` with exponential backoff (1s→30s, ±500ms jitter).
- Auth context in `lib/auth.tsx` wraps the app; `useAuth()` exposes `token`, `user`, `login()`, `logout()`, `isAdmin`.
- Login page at `/login`; unauthenticated users are redirected there from `/`.
- SSE stream in `MapView` uses `connectHotspotStream` with the Bearer token; re-fetches hotspots on push events.
- `TrustTierEditor` (admin-only) lists sources with dropdowns to PATCH `/sources/{id}` trust_tier.
- `api.ts` provides typed `sources()` and `updateTrustTier()` methods; all api methods accept `string | null` token.
- SITREP citation parsing in `lib/citations.ts` renders `[N]` markers as superscript links.
- SITREP citation parsing in `lib/citations.ts` renders `[N]` markers as superscript links.
- **FR-18**: `lib/filters.ts` provides `HotspotFilters`, `DEFAULT_FILTERS` (minConf=40), `passesFilter()`, `applyFilters()` — client-side filtering. `components/FilterPanel.tsx` renders confidence slider, alert-level checkboxes, time-window selector, showing-X-of-Y counter, reset button. `components/Legend.tsx` renders FR-13 color swatches.
- **FR-19**: `lib/clustering.ts` wraps supercluster (radius=60, maxZoom=12); `lib/useCluster.ts` hook returns `{clusters, leaves}` for current zoom. `MapView` renders cluster circles with count labels at zoom < 7 via `TextLayer`, individual markers via `ScatterplotLayer` at all zooms.
- **FR-20**: `lib/whatsnew.ts` provides `isNew()`, `countNew()`, `markSeen()`, `getLastSeen()` (localStorage key `sentinel_hotspots_last_seen`). `MapView` accepts `newHotspots` prop to render translucent highlight layer. `FilterPanel` accepts `newCount` prop to display "N new" chip + "Mark seen" button.
- Containerized via `Dockerfile` + `.dockerignore` for Docker Compose deployment.

## Work Guidance

- All new components go in `components/` as `"use client"` if they use browser APIs.
- Pure-logic modules go in `lib/` with corresponding tests in `__tests__/` (TDD).
- Map-related components must be imported via `dynamic(..., { ssr: false })`.
- Do not import from `api/` (backend) — the frontend talks exclusively through the REST API.

## Verification

```bash
cd frontend-next && npm run build && npx vitest run
```
