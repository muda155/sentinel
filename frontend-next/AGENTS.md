# DOX — frontend-next/

## Purpose

Next.js dual-map frontend (deck.gl + MapLibre GL + globe.gl) for the Sentinel OSINT dashboard. Replaces the deprecated Streamlit dashboard. Consumes FastAPI REST + SSE endpoints.

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
- SSE stream handling lives in `lib/sse.ts` (Sprint 11) with exponential backoff (1s→30s, ±500ms jitter).
- Auth context in `lib/auth.tsx` (Sprint 11) wraps the app; Bearer token passed via `api.*(token)`.
- SITREP citation parsing in `lib/citations.ts` (Sprint 11) renders `[N]` markers as superscript links.
- Auth context in `lib/auth.tsx` (Sprint 11) wraps the app; `useAuth()` exposes `token`, `user`, `login()`, `logout()`, `isAdmin`.
- Login page at `/login` (Sprint 11); unauthenticated users are redirected there from `/`.
- SSE stream in `MapView` (Sprint 11) uses `connectHotspotStream` with the Bearer token; re-fetches hotspots on push events.
- `TrustTierEditor` (Sprint 11, admin-only) lists sources with dropdowns to PATCH `/sources/{id}` trust_tier.
- GET `/sources` endpoint returns source list with `trust_tier` for the admin editor.
- `api.ts` adds `sources()` and `updateTrustTier()` methods + accepts `string | null` token throughout.

## Work Guidance

- All new components go in `components/` as `"use client"` if they use browser APIs.
- Pure-logic modules go in `lib/` with corresponding tests in `__tests__/` (TDD).
- Map-related components must be imported via `dynamic(..., { ssr: false })`.
- Do not import from `api/` (backend) — the frontend talks exclusively through the REST API.

## Verification

```bash
cd frontend-next && npm run build && npx vitest run
```
