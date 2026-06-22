# conf_score recalibration — design

Date: 2026-06-22
Status: approved (brainstorming → plan)

## Problem

`conf_score` systematically under-scores genuine hotspots. On live GDELT data
every hotspot scored 8–17 (all grey), and `geopolitical_diversity` was `0.000`
for **every** hotspot. As a result no hotspot ever clears the LLM gate
(`conf_score > 40`), and the dashboard shows only grey markers.

Investigation found two implementation bugs plus a calibration mismatch with the
real data distribution.

### Bug 1 — diversity reads the wrong column
`specs.md` FR-8 says compute Shannon entropy over country codes **"from the
`sources` table"** (which country's *outlet* is reporting — cross-national
corroboration). `pipeline/scoring.py` reads `e.country_code` from the **events**
table (the event's *location*). Every event in a geographic cluster shares one
location country, so `geopolitical_diversity = 0` always, zeroing 40% of the
formula on every hotspot.

### Bug 2 — source_density counts duplicate domains
FR-7 says `weighted_domains = Σ trust_weight` over **unique domains**. The code
sums over every event row, so N articles from one domain count N×.

### Calibration mismatch
The spec formula deliberately rewards *breadth of corroboration*: weights
`0.6·source_density + 0.4·diversity` with `source_density = tanh(Σtrust / 10)`.
But the operational reality is that **most hotspots are single-country reports**
— cross-national reporting only happens for power-on-power wars or globally
impactful events (e.g. Iran-scale). Putting 40% of the score on cross-national
diversity therefore caps almost every genuine hotspot at grey, and the `/10`
divisor needs ~20 unique trusted domains for a high score — far more than a
single 1°×1° / 2 h DBSCAN cluster ever has.

## Goal

Fix the two bugs, populate the data the formula needs, and re-tune so that:

- a single-country event corroborated by a few distinct reputable outlets reaches
  **yellow (40–70)** on source corroboration alone;
- **green (>70)** effectively requires cross-national reporting — which matches
  the domain model, since cross-national coverage is itself the signal of a
  significant/global event;
- thin or single-unknown-source hotspots stay grey.

## Design

### Formula

```
conf_score      = (0.7 · source_density + 0.3 · geopolitical_diversity) × 100
source_density  = tanh( Σ trust_weight(domain_i) / DIVISOR )   over UNIQUE domains
diversity       = Shannon-entropy(source country codes) / log2(N)   (0 if N ≤ 1)
```

Defaults: weight_density `0.7`, weight_diversity `0.3`, divisor `3`
(previously `0.6 / 0.4`, divisor `10`).

`source_density` is the primary signal — it measures within-country corroboration
(trust-weighted count of distinct reporting outlets). `geopolitical_diversity` is
the 30-point bonus that lifts the rare cross-national event into green.

### 1. Fix the two bugs (`pipeline/scoring.py`)
- `_fetch_hotspot_events` JOINs `sources` and selects `s.country_code` for the
  diversity input (FR-8), not `e.country_code`.
- Dedupe by domain before summing trust weights for `source_density` (FR-7). The
  trust weight per domain is taken once.

### 2. Populate source countries
- New `domain → ISO-A3` resolver: ccTLD rules (`.uk`→`GBR`, `.ru`→`RUS`, …) plus a
  curated map of major generic-TLD outlets (`reuters.com`→`GBR`,
  `aljazeera.net`→`QAT`, `cnn.com`→`USA`, …). Unknown → `NULL`.
- One-time backfill of existing `sources.country_code`.
- Wire the resolver into source creation in `pipeline/ingestion.py` so new GDELT
  domains get a country going forward.
- Unknown-country sources are excluded from the diversity entropy (as today).

### 3. Re-tune & make configurable
- New env vars read in `scoring.py`, defaulting to the values above:
  - `SENTINEL_CONF_W_DENSITY` (default `0.7`)
  - `SENTINEL_CONF_W_DIVERSITY` (default `0.3`)
  - `SENTINEL_CONF_DENSITY_DIVISOR` (default `3`)
- This makes future re-calibration a config change, not a code+spec edit.

### Calibration targets

| Hotspot | unique domains (Σtrust) | countries | conf | band |
|---|---|---|---|---|
| Single-country, 3 mid-tier outlets | 3 (~1.6) | 1 | ~34 | grey |
| Single-country, 3 reputable | 3 (~2.0) | 1 | ~41 | yellow |
| Single-country, 5 outlets | 5 (~3.0) | 1 | ~53 | yellow |
| Major single-country, 7 outlets | 7 (~4.5) | 1 | ~63 | high yellow |
| Cross-national event | 4 (~2.6) | 2 | ~77 | green |
| Global (Iran-scale) | 8 (~5.0) | 4 | ~95 | green |
| Thin / 1 unknown source | 1 (0.4) | 1 | ~9 | grey |

### 4. Spec, DOX, tests
- Amend `specs.md`: FR-7 (divisor + acceptance examples), FR-8 (clarify country
  comes from the `sources` table), FR-9 (weights). Bump Document Version.
- Update DOX: root `AGENTS.md` and `pipeline/AGENTS.md` both cite
  `0.6 × source_density + 0.4 × geopolitical_diversity` and `tanh(.../10)` — update
  to the new defaults and document the new env vars. Update `CLAUDE.md` scoring
  notes.
- Document new env vars in `sentinel.env` and `sentinel.env.example`.
- Tests (TDD):
  - unique-domain dedup for `source_density`;
  - diversity computed over source country codes;
  - configurable weights/divisor honoured, with the calibration anchors above;
  - resolver: ccTLD, curated outlet, unknown → NULL;
  - backfill idempotency;
  - update existing FR-7/8/9 tests to the new constants.

## Scope / non-goals
- The LLM threshold stays `40` — genuine hotspots will now clear it on their own.
- No DB migration: `conf_score`, `source_density`, `geopolitical_diversity`,
  `sources.country_code` columns already exist. Existing hotspots re-score on the
  next scoring pass.
- No change to `convergence_score` or clustering.
- Resolver covers ccTLDs + a curated major-outlet list; exhaustive
  domain→country mapping is out of scope (unknown stays NULL, excluded from
  diversity).

## Risks
- Divisor `3` saturates `tanh` quickly; if real GDELT clusters skew to many
  low-trust domains, scores could read high. Mitigated by env-configurability —
  tune `SENTINEL_CONF_DENSITY_DIVISOR` against live data after rollout.
- Curated outlet map is necessarily partial; cross-national diversity only
  improves for domains we can resolve. Acceptable — green is meant to be rare.
