# M9 — Temporal Window Comparison & Score Literacy

**Status:** design approved, implementation pending
**Date:** 2026-08-10
**Proposed FRs:** FR-27 (score literacy), FR-28 (windowed comparison), FR-29 (window report export)
**Requires:** `specs.md` version bump to 1.13.0 with the three FRs written into §4

## Motivation

Two problems, one origin.

**Scores are unreadable.** `HotspotDetail` prints DB column names as values —
`conf_score: 82.5`, `convergence_score: 27.0`, `consistency_score: 2.2`. The human
label already sits above each one (`detail.confidence` = "Confidence (source
reliability)"), so the identifier adds nothing and costs comprehension. Nothing on
screen tells an analyst how to act on a 27, or that low confidence means thinly
sourced rather than false.

**Sentinel cannot answer "is this escalating?"** Scores are recomputed and
overwritten on every pipeline run. No history is retained anywhere: `hotspots`
holds current values only, and there is no snapshot table. The dashboard shows a
frozen present tense. For an OSINT tool, change over time is the question that
matters most, and it is the one question the product cannot address.

A UI prototype (`ui-prototype.html`, supplied by the user) proposed an A-vs-B
comparison between two *different* hotspots. That was redirected during
brainstorming to comparison between two *time windows of the same hotspot*, which
is the question analysts actually ask.

## Key finding: no history table is needed

Every metric is recomputable for an arbitrary window from data the detail panel
**already fetches**. `GET /hotspots/{id}/events` is unpaginated and returns, per
event: `event_date`, `domain`, `trust_score`, `trust_tier`, `country_code`,
`event_type_label`, `fatalities`, `avg_tone`.

| Metric | Recomputable? | Inputs |
|---|---|---|
| `conf_score` | yes | `0.7·tanh(Σ trust over unique domains / 3) + 0.3·diversity` — all present |
| `convergence_score` | yes | `min(100, types·25 + min(25, events·2))` — all present |
| `consistency_score` | yes, with one migration | stored NLI judgments, see below |
| counts, fatalities, tone, domains, type mix | yes | trivially |

Consistency was initially assumed to require re-running NLI. It does not. The
judgments are **persisted**: `claim_evidence` stores one row per claim×event pair
(`relation`, `probability`), and `GET /hotspots/{id}/claims` already returns them
with `event_id` and `domain`. Everything downstream of the NLI model is arithmetic
over stored rows (`pipeline/consistency.py:336-391`):

1. Per domain, the strongest judgment wins; drop `probability < SENTINEL_NLI_MIN_PROB` and `relation == "neutral"`
2. `support` = Σ trust×prob over supporters (excluding origin domains), `dispute` = Σ over contradictors
3. `disputed` if contradictors and `dispute ≥ ratio·support`; `corroborated` if ≥2 supporters; else `uncorroborated`
4. `weight = max(support+dispute, 0.1)`; score = `100 · Σ(w·v)/Σw` where v ∈ {1.0, 0.5, 0.0}

Windowing means filtering the evidence rows by their event's date and re-running
steps 1–4.

## The gap: origin domains are not persisted

Step 2 excludes domains that *asserted* a claim from counting as its supporters —
a source cannot corroborate itself. Those come from `ExtractedClaim.source_indices`,
which is **dropped** before persistence: `ClaimVerdict`
(`pipeline/consistency.py:278`) has no such field, so `ConsistencyRepository.save`
never writes it. A client recomputation without it counts origin domains as
independent supporters and **inflates corroboration**.

**Migration `023_claim_origin_domains.sql`:**

```sql
ALTER TABLE claims ADD COLUMN IF NOT EXISTS origin_domains TEXT[];
```

Store resolved **domains**, not `source_indices`. Citation indices are recomputed
on every fetch (`assign_citation_indices` inside `fetch_hotspot_events`), so
persisted indices would silently re-point at different events as the event set
shifts. `consensus()` already resolves indices → domains at compute time
(`consistency.py:346`); persisting that resolved set is stable by construction.

Threading required:
- `ClaimVerdict` gains `origin_domains: list[str]`
- `consensus()` passes the `origin_domains` set it already computes
- `ConsistencyRepository.save` writes the column
- `fetch_hotspot_claims` returns it, **plus `consensus_weight`** (stored since
  migration 020, never exposed; surfacing it makes the published score exactly
  reconstructible)
- `api/schemas.py:Claim` gains both fields

Pre-migration rows have `origin_domains` NULL. NULL means **"cannot verify"**, not
"empty set" — the client must skip those claims rather than treat every domain as
independent.

## Architecture

### 1. Pure client modules (`frontend-next/lib/`, TDD, no new dependencies)

- **`window-metrics.ts`** — `(events, window) → {conf, convergence, eventCount, maxFatalities, meanTone, uniqueDomains, typeMix}`. Reuses the existing formulas; no duplication of `lib/score-breakdown.ts` constants.
- **`window-consistency.ts`** — `(claims, events, window) → {score, perClaimStatus, counts}` via steps 1–4 above. Skips claims with null `origin_domains`.
- **`compare.ts`** — two window results → delta rows `{label, valueA, direction, valueB, delta}`.

### 2. Self-validation (load-bearing, not a nicety)

`SENTINEL_NLI_MIN_PROB` (0.6) and `SENTINEL_CONSISTENCY_DISPUTE_RATIO` (0.5) are
server-side env vars the client cannot read, exactly like the conf weights. Each
module therefore recomputes over the **full** range and compares against the
published `conf_score` / `consistency_score`:

- **Match within tolerance** → the client's constants and origin-domain handling
  are correct; windowed numbers are trustworthy.
- **Miss** → degrade that metric to counts without a score, reusing the
  `mode: "raw"` fallback pattern already established in `lib/score-breakdown.ts`
  for env-overridable weights.

This makes a silent constants drift impossible to mistake for a real trend.

### 3. Semantics (must be stated in the UI)

Claims were extracted by the LLM over the **full** event set. Evaluating them
against a day 1–5 window answers *"how well did that window's evidence support the
claims we know about today"* — retrospective and defensible. It is **not** "what
the system would have said on day 5." The comparison UI labels every recomputed
figure **"recomputed over this window"**; without that, a windowed confidence
sitting next to the panel's published `conf_score` reads as two contradictory
confidence numbers.

### 4. UI

- **`components/CompareDialog.tsx`** — opened from a Compare button in the score
  section header of `HotspotDetail`. Two window pickers reusing
  `TIME_WINDOW_HOURS`, defaulting to **last 24h vs the preceding 24h**. Renders the
  delta table (the prototype's table, no emoji). Consistency shows per-claim
  statuses beside its score — a score alone hides that a specific claim flipped to
  disputed, which is the informative part.
- **Score literacy** — drop the `conf_score:` / `convergence_score:` /
  `consistency_score:` identifiers for the human names already in
  `lib/locales/`. Each score name gains a `?` affordance opening a help popover
  with definition, how to read the number, and the trap (low confidence = thinly
  sourced, not false; convergence caps event volume at 25 so a single-type cell
  cannot exceed 50). Reuses the existing `Legend` pattern (`aria-expanded`,
  `role="tooltip"`, Escape closes). All strings via `useT()`, key parity across
  `lib/locales/` enforced by the existing test.

### 5. Export

Three artifacts from one dialog:

- **CSV + JSON** — client-side `Blob` download of the delta table and both window
  metric sets. Zero dependencies. JSON is consumable by the `eval/` harnesses.
- **Narrative report (Markdown + print stylesheet)** — a prose intelligence report
  for the window, LLM-generated. Markdown downloads as `.md`; a `@media print`
  view renders the same content for browser print-to-PDF. Text-first, no charts.

### 6. New endpoint: `GET /hotspots/{id}/report`

**This is the first user-triggered LLM call in the API.** Every existing LLM call
runs inside the pipeline scheduler, never inside a request. That difference drives
the entire design of this endpoint.

Query params: `from`, `to` (ISO timestamps). Response:
`{narrative: str, citations: [...], model: str, cached: bool}`.

Flow: fetch window events → build prompt → `call_llm_raw` → `validate_citations()`
→ return.

Non-negotiable constraints:

- **Dedicated rate limiter.** The shared 60 req/min bucket (`api/ratelimit.py:52`)
  is a cost and DoS hole in front of an LLM. New `SENTINEL_REPORT_RATE_PER_MIN`
  (default **4**) on its own `TokenBucket`.
- **Caching.** Key on `(hotspot_id, from, to, max_event_id_in_window)`. The
  `max_event_id` term invalidates automatically when new events land in the window,
  so re-opening an unchanged report never re-bills. Redis, matching the ACLED cache
  pattern.
- **Interactive timeout.** `call_llm_raw` defaults to 3 retries plus an Ollama
  fallback, which can hold a request worker for minutes. This endpoint passes
  `retries=1` and a dedicated `SENTINEL_REPORT_TIMEOUT_S` (default 30).
- **Graceful absence.** No NIM/Ollama credentials → **503** with a typed error.
  CSV/JSON export must remain fully functional; the narrative is the only casualty.
- **FR-11/FR-12 enforcement.** `validate_citations()` must pass or the report is
  rejected — retry once, then surface a clear failure. An uncited narrative export
  would violate the citation contract the rest of the system is built on.
- **Prompt scoping.** The prompt states the window bounds explicitly and is given
  only the window's events, so the model cannot narrate activity from outside it.

## Explicitly out of scope

- **Timeline scrubber.** The prototype's bottom histogram with play/pause/reset.
  Reframed as a brushable window picker it is the natural companion to this work,
  but the comparison is complete and defensible with plain window selectors.
  Deferred until this lands.
- **Hotspot A vs hotspot B.** Superseded by the temporal axis.
- **Prototype layout regressions.** The prototype's absolutely-positioned detail
  panel (removed deliberately — it created a ~370×713px click dead zone that
  swallowed marker clicks) and its always-visible legend/filter cards (moved into
  popovers deliberately — as cards they permanently occupy the top-left map
  quadrant). Neither is ported.
- **Emoji.** Present throughout the prototype; excluded per project convention.

## Testing

- `window-metrics`, `window-consistency`, `compare` — pure-function tests in
  `frontend-next/__tests__/`, including the self-validation fallback paths.
- Consistency parity test: recompute over the full range against a seeded fixture
  and assert equality with the pipeline's own `hotspot_consistency_score`.
- `origin_domains` round-trip: `consensus()` → `save` → `fetch_hotspot_claims`.
- Null `origin_domains` (pre-migration rows) skip rather than inflate.
- `CompareDialog` component tests mocking `@/lib/api`, `@/lib/auth`, `@/lib/i18n`.
- Endpoint tests: cache hit/miss, 503 without credentials, rate-limit rejection,
  citation-validation failure path.
- `pytest tests/` and `cd frontend-next && npm run build && npx vitest run`.

## Risks

| Risk | Mitigation |
|---|---|
| Windowed conf read as contradicting the published `conf_score` | "Recomputed over this window" label on every figure; self-validation degrades rather than guesses |
| Client constants drift from server env | Full-range reconstruction check with `mode: "raw"` fallback |
| LLM call blocks a request worker | `retries=1`, dedicated 30s timeout, dedicated rate limiter, Redis cache |
| LLM cost per export | Cache keyed on `max_event_id`; 4 req/min ceiling |
| Pre-migration claims inflate corroboration | NULL `origin_domains` means "cannot verify" — claim skipped, never assumed independent |
| Retrospective semantics mistaken for point-in-time replay | Stated in the UI, not only in this doc |
