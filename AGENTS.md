# DOX framework — Sentinel root

- DOX is the binding work contract for this repository
- All agents must read the applicable DOX chain before editing any file

## Core Contract

- AGENTS.md files are binding work contracts for their subtrees
- Work products, source materials, instructions, records, and durable docs must stay understandable from the nearest applicable AGENTS.md plus every parent AGENTS.md above it

## Read Before Editing

1. Read this root AGENTS.md
2. Identify every file or folder you expect to touch
3. Walk from the repository root to each target path
4. Read every AGENTS.md found along each route
5. Use the nearest AGENTS.md as the local contract; use parent docs for repo-wide rules
6. If docs conflict, the closer doc controls local details; no child doc may weaken DOX

Do not rely on memory. Re-read the applicable DOX chain in the current session before editing.

## Update After Editing

Every meaningful change requires a DOX pass before the task is done.

Update the closest owning AGENTS.md when a change affects:
- purpose, scope, ownership, or responsibilities
- durable structure, contracts, workflows, or operating rules
- required inputs, outputs, permissions, constraints, side effects, or artifacts
- user preferences about behavior, communication, process, organization, or quality
- AGENTS.md creation, deletion, move, rename, or index contents

Remove stale or contradictory text immediately.

## Hierarchy

- This root AGENTS.md is the DOX rail: project-wide rules, global preferences, and the Child DOX Index
- Child AGENTS.md files own domain-specific instructions and their own Child DOX Index
- Each parent explains what its direct children cover and what stays owned by the parent
- The closer a doc is to the work, the more specific and practical it must be

## Project-Wide Rules

### Architecture
- Pipeline flow: ingest → cluster → score → verify → visualize (6 steps, `pipeline/pipeline.py`)
- Always use `get_pooled_connection()` and return with `pool.return_connection(conn)` in a `finally` block — never open raw DB connections
- Schema migrations live in `db/init/` and are applied in numeric order; never modify already-applied migrations

### Spec Compliance
- `specs.md` is the authoritative design doc (v1.13.1 — verify against its Document Version header) — check it before implementing new features
- FR-WM-CONVERGENCE: a grid cell becomes an active Convergence Zone on **`convergence_score ≥ 1`** (≥1 classified event); 2+ distinct types raise the alert level but are not required to activate (single-type GDELT-only cells must still produce hotspots). GDELT classification reads the **2-digit CAMEO root** of the 3–4 digit `EventCode`. This is grid-cell binning, not DBSCAN density alone.
- FR-7/FR-8/FR-9: `conf_score` formula must match exactly: `0.7 × source_density + 0.3 × geopolitical_diversity`, where `source_density = tanh(Σ trust over unique domains / 3)` (env-configurable via `SENTINEL_CONF_W_DENSITY`, `SENTINEL_CONF_W_DIVERSITY`, `SENTINEL_CONF_DENSITY_DIVISOR`)
- FR-11/FR-12: LLM citations must be validated with `validate_citations()` — every sentence must end with `[N]` (FR-23 adds one relaxation: dispute sentences may end with exactly two indices `[i][j]`)
- FR-21..FR-24 (M6 Consistency Engine, specs §4.8): implemented — engine in `pipeline/consistency.py` + `pipeline/nli.py`, claims API, Evidence panel; `conf_score` untouched; migration 020

### Code Quality
- Run `ruff check` before committing; config is in `ruff.toml`
- All new features need tests in `tests/`
- No raw SQL outside `pipeline/db.py`, `api/queries.py`, or migration files

### Environment
- All config via env vars; `sentinel.env` is the live config, `sentinel.env.example` is the template
- Never hard-code credentials or endpoints

## Closeout

1. Re-check changed paths against the DOX chain
2. Update nearest owning docs and any affected parents or children
3. Refresh every affected Child DOX Index
4. Remove stale or contradictory text
5. Run `pytest tests/` and `ruff check` when relevant
6. Report any docs intentionally left unchanged and why

## User Preferences

- Terse responses; no trailing summaries after diffs
- No emojis unless explicitly requested
- No comments unless the WHY is non-obvious

## Root-Owned Directories

Directories with no child AGENTS.md are owned directly by this root doc:
- `scripts/` — ops scripts: partition create/cleanup (`create_partitions.py`, `cleanup_old_partitions.py`), polygon loader (`load_country_polygons.py`), stale-SITREP invalidation (`invalidate_stale_sitreps.py`, one-shot for the Phase-3 duplicate-URL collapse — runbook in `docs/ops/phase3-duplicate-collapse.md`)
- `load/` — load testing (`sse_locust.py` Locust suite against the SSE/API layer)
- `docker/` — container build (`Dockerfile`)
- `docs/` — ops runbooks (`ops/`), implementation plans (`superpowers/`), analyses, World Monitor reference archive (`world_monitor_archive/`), thesis-defence cheatsheets (`cheatsheets/`)
  - `docs/cheatsheets/` — Vietnamese study notes for the M8/FR-26 relevance gate (index in `cheatsheets/README.md`): why MNLI mislabels off-topic pairs, the gate design and its three thresholds, `all-MiniLM-L6-v2`, and the five-step sentence-to-vector path. Explanatory material for the defence, not API or ops docs. Every technical detail must match current code (`pipeline/relevance.py`, `pipeline/consistency.py`, `pipeline/nli.py`, migrations 022/023) or the final report; code wins on conflict. The pre-gate baseline is **32 disputed / 31 uncorroborated / 0 corroborated over 63 claims (2026-07-28)** — the earlier 5/31/67 figure was measured on a DB corrupted by a faulty M7 backfill and is retracted; never reintroduce it.
- `eval/` — thesis evaluation harnesses (`eval/consistency/`: gold-set export/scoring, contradiction injection, weighting backtest). The injection harness reports `planted_premise_detected` alongside `detection_rate`; a `detection_rate` quoted without it is not evidence, because a premise the NLI does not read as contradicting makes every counted dispute come from unrelated evidence. Changing `contradiction_premise` requires re-measuring both. `snapshot.py` + `weight_backtest.py` compare `consistency_score` weighting formulas offline from stored `claim_evidence` (no LLM/NLI/GPU): dump a `REPEATABLE READ` snapshot first and score every variant against that one directory, since the pipeline rewrites these tables every tick. `old_formula_reproduces_published_score` must match `hotspots.consistency_score` exactly or nothing else in the report is meaningful. Claims with `origin_domains IS NULL` — and every hotspot holding one — are excluded per migration 023. `score_correlations.py` produces the report's §4.5 coefficients from one capture and **recomputes** `consistency_score` rather than reading the column (stored rows carry whichever formula shipped when they were last scored); it joins `convergence_score` from `grid_cells`, because `hotspots.convergence_score` is NULL on every live row and reading it directly yields an empty sample.

## Child DOX Index

- [pipeline/AGENTS.md](pipeline/AGENTS.md) — ingestion, clustering, scoring, LLM verification, scheduler, connection pool
- [frontend/AGENTS.md](frontend/AGENTS.md) — Streamlit dashboard, Pydeck map, auto-refresh logic
- [api/AGENTS.md](api/AGENTS.md) — FastAPI REST + SSE layer, rate limiting, metrics
- [frontend-next/AGENTS.md](frontend-next/AGENTS.md) — Next.js dual-map frontend (deck.gl/MapLibre/globe.gl), FR-13 visual contract, auth/SSE/citation contracts
- [tests/AGENTS.md](tests/AGENTS.md) — pytest suite, integration test patterns, seeding helpers
- [db/AGENTS.md](db/AGENTS.md) — schema migrations, PostGIS setup, table contracts
