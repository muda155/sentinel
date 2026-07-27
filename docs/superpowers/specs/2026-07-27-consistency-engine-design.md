# Consistency & Consensus Verification Engine — Design (M6)

**Date:** 2026-07-27
**Status:** Approved (brainstorm) — pending implementation
**Spec FRs:** new FR-21 (ingestion enrichment), FR-22 (consistency engine), FR-23 (dispute-aware SITREP), FR-24 (claims API + Evidence panel) — to be added to specs.md §4.8
**Owning DOX:** `pipeline/AGENTS.md`, `api/AGENTS.md`, `frontend-next/AGENTS.md`, `db/AGENTS.md`, `tests/AGENTS.md`

## Problem

The project title promises "LLM Consistency Verification", but the LLM step today is a single hosted-API call: headlines in, a 3–4 sentence paraphrase and one `conflict_detected` boolean out. Progression-review feedback: *an API call is not an owned contribution and over-sells the "LLM analysis" claim.* The thesis needs a verification mechanism that belongs to Sentinel — an algorithm we designed, implemented, and measured — with the LLM demoted to a component inside it.

Secondary problem, discovered during design: ingestion **downloads and then discards** the data such an engine needs. GDELT actor names, `GoldsteinScale`, `AvgTone`, and `NumSources` are parsed from the CSV but never inserted; ACLED's `notes` (a descriptive paragraph per event) and `fatalities` are reduced to a synthetic title. The engine's evidence base can therefore be built with **no scraping and no new infrastructure** — just stop throwing the data away.

## Contribution statement (defense narrative)

> NIM is a commodity extractor. The trust-weighted cross-source agreement algorithm, the `consistency_score`, and the dispute-aware SITREP are Sentinel's own — and they are quantitatively evaluated.

This yields a clean three-score story: `convergence_score` (World Monitor's formula, credited), `conf_score` (Sentinel contribution #1, FR-7/8/9 — untouched by this design), `consistency_score` (Sentinel contribution #2, this design).

## Decisions taken (brainstorm outcomes)

1. Build the Consistency Engine first, **including** ingestion enrichment; RAG/article-scraping and citation-groundedness are explicit follow-ons, not in scope.
2. **Hybrid backend:** NIM LLM (1 call/hotspot, existing Ollama fallback) for claim extraction; a small **local CPU NLI cross-encoder** for all pairwise entailment checks. The core algorithm runs without any hosted API.
3. **New `consistency_score` + claim tables;** `conf_score` formula stays locked (FR-7/8/9).
4. **SITREP is generated FROM the verified claim set** — the LLM may only summarize claims that passed verification, and must report disputes explicitly.
5. **Evaluation = hand-labeled gold set (~50 hotspots) + synthetic contradiction injection.**

## Architecture

Pipeline step 6 splits:

```
… → 5. Consensus scoring (conf_score)
    → 6a. Consistency Engine  (pipeline/consistency.py — NEW)
           extract claims → NLI agreement matrix → trust-weighted consensus
           → claims + claim_evidence rows, hotspots.consistency_score
    → 6b. SITREP generation   (pipeline/llm_verifier.py — rewired)
           prompt built from verified claims; dispute-aware; headline fallback
```

Trigger unchanged: hotspots with `conf_score > SENTINEL_LLM_THRESHOLD` and no existing summary. Scheduler unchanged.

### Component 1 — Ingestion enrichment (FR-21)

Migration `db/init/020_consistency_engine.sql` (018/019 already exist: end_window index, geo_precision), all columns nullable:

| Column | Source | Notes |
|---|---|---|
| `events.actor1_name`, `events.actor2_name` | GDELT `Actor1Name`/`Actor2Name` | already parsed, currently dropped |
| `events.goldstein_scale` | GDELT `GoldsteinScale` | REAL; conflict-intensity −10..+10 |
| `events.avg_tone` | GDELT `AvgTone` | REAL |
| `events.num_sources` | GDELT `NumSources` | INTEGER |
| `events.notes` | ACLED `notes` | TEXT; the richest free text we get without scraping |
| `events.fatalities` | ACLED `fatalities` | INTEGER |

Both ingestors populate the new columns; existing rows stay NULL (no backfill — the engine only processes hotspots going forward; `llm_summaries` NOT EXISTS guard already skips old ones).

**Evidence text** per event (rendered in `pipeline/consistency.py`, not stored):
- ACLED: `notes` (fallback: title).
- GDELT: title + structured sentence, e.g. `"Reported: MILITARY (Actor1) vs REBELS (Actor2); Goldstein −8.0; tone −5.2; 12 reports."` NULL fields omitted.

### Component 2 — Consistency Engine (FR-22), `pipeline/consistency.py`

**Phase A — Claim extraction (LLM as commodity tool).** One NIM chat call per hotspot (existing retry/backoff/Ollama-fallback machinery from `llm_verifier.py`, refactored to be shared). Input: numbered evidence texts over unique domains (same ordering contract as `fetch_hotspot_articles` so indices align with citations). Output JSON: `{claims: [{text, source_indices}]}`, ≤ 8 atomic, self-contained, English claims; Pydantic-validated; `_extract_json` tolerant parsing.

**Phase B — Agreement matrix (local, owned).** NLI cross-encoder — default `cross-encoder/nli-deberta-v3-base` (~400 MB), env-overridable via `SENTINEL_NLI_MODEL` — classifies every (claim, evidence-text) pair as `supports` / `contradicts` / `neutral` with probability. Pairs are batched; hard caps: 8 claims × 20 unique domains = 160 pairs (~10 s CPU; fits NFR-1's 5-minute budget). Model lazily downloaded to local HF cache on first run, offline afterwards. A claim's own originating source is recorded but excluded from corroboration counting (self-support is not corroboration).

**Phase C — Trust-weighted consensus (owned).** Per claim, over unique domains, using existing `sources.trust_score`:

```
support(c)  = Σ_{d ∈ supporters(c)}    trust_d × P_entail(c,d)
dispute(c)  = Σ_{d ∈ contradictors(c)} trust_d × P_contra(c,d)
```

Status rules (evaluated in order):
- `disputed`      if `dispute ≥ SENTINEL_CONSISTENCY_DISPUTE_RATIO × support` (default ratio 0.5) and at least one contradicting domain
- `corroborated`  if ≥ 2 distinct non-origin domains support (P_entail above threshold `SENTINEL_NLI_MIN_PROB`, default 0.6)
- `uncorroborated` otherwise

**Hotspot score:**

```
consistency_score = 100 × Σ_c w_c · v_c / Σ_c w_c
  v_c = 1.0 (corroborated) | 0.5 (uncorroborated) | 0.0 (disputed)
  w_c = support(c) + dispute(c)   (trust mass of the claim's evidence; floor 0.1)
```

Env weights mirror the conf_score pattern (`SENTINEL_CONSISTENCY_*`). Single-source hotspots produce all-`uncorroborated` claims → score ~50 with an `insufficient_sources` marker (see API) — honest "unverifiable", never faked confidence.

### Component 3 — Data model

Migration `020` (same file) also creates:

```sql
ALTER TABLE hotspots ADD COLUMN consistency_score DOUBLE PRECISION;  -- NULL = not evaluated

CREATE TABLE claims (
    claim_id BIGSERIAL PRIMARY KEY,
    hotspot_id BIGINT NOT NULL REFERENCES hotspots(hotspot_id) ON DELETE CASCADE,
    claim_text TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('corroborated','uncorroborated','disputed')),
    consensus_weight DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE claim_evidence (
    claim_id BIGINT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
    event_id BIGINT NOT NULL,
    relation TEXT NOT NULL CHECK (relation IN ('supports','contradicts','neutral')),
    probability DOUBLE PRECISION,
    PRIMARY KEY (claim_id, event_id)
);
```

`claim_evidence.event_id` is not an FK (events is partitioned; links die with the claim row via cascade from `claims`). Claim lifecycle follows FR-5 hotspot identity: unchanged membership keeps the hotspot row, so its claims and summary persist and the engine is skipped (same NOT-EXISTS guard as `llm_summaries`); changed membership replaces the hotspot row, cascading old claims away, and the engine runs fresh on the new row.

### Component 4 — Dispute-aware SITREP (FR-23), `pipeline/llm_verifier.py`

`build_prompt` gains a claims mode: input is the verified claim list — text, status, supporting/contradicting source indices — not raw headlines. Instructions:
- Summarize **only** corroborated + uncorroborated claims; mark uncorroborated ones as "single-source reports".
- Report each disputed claim explicitly: `"Sources disagree on <X> [2][5]."` — dispute sentences carry exactly two indices (supporter, contradictor).
- Citation rule otherwise unchanged: one `[N]` per sentence.

`validate_citations` gets one relaxation: a sentence matching the dispute pattern `\[\d+\]\[\d+\][.!?]\s*$` is also valid. Everything else (single-index rule, abbreviation guards, empty-summary rejection) unchanged.

**Fallback:** if the engine produced no claims for a hotspot (NLI unavailable, extraction failed), 6b uses today's headline prompt verbatim — zero regression path.

### Component 5 — API + dashboard (FR-24)

- `GET /hotspots/{id}/claims` — Bearer-gated, rate-limited, 404 on unknown id (same pattern as `/hotspots/{id}/events`). Returns `{claims: [{claim_id, claim_text, status, evidence: [{event_id, citation_index, relation, probability, domain}]}], insufficient_sources: bool}`. `citation_index` reuses the FR-13 ordering contract.
- `consistency_score` added to `GET /hotspots` and `GET /hotspots/{id}` payloads (nullable).
- Frontend-next detail panel: new **"Evidence & Consistency"** section — consistency score, then claim rows with status badges (✓ corroborated / ? single-source / ⚠ disputed) and per-claim source chips linking into the existing Sources list. Vietnamese strings via `lib/i18n.tsx` dictionaries. `consistency_score` NULL ⇒ section hidden.

### Error handling

| Failure | Behavior |
|---|---|
| NLI model missing / import error | warn once, skip engine, `consistency_score` NULL, SITREP falls back to headline mode — pipeline never blocks |
| Claim-extraction JSON invalid | `_extract_json` + existing retry; on final failure treat as "no claims" → headline fallback |
| NIM down | existing Ollama fallback path (shared machinery) |
| Single-source hotspot | engine runs; all claims `uncorroborated`; `insufficient_sources: true` |
| Hotspot deleted (TTL) | claims cascade-delete |

### Evaluation (thesis chapter)

Under `eval/consistency/`:
1. **Gold set:** ~50 real hotspots exported to JSONL; human labels per extracted claim (faithful? atomic?) and per agreement verdict (correct relation?). Runner script computes claim-extraction precision and contradiction-detection precision/recall vs. labels.
2. **Synthetic injection:** script takes real hotspots, injects a fabricated contradicting evidence text as an extra source, asserts the engine flags the affected claim `disputed`; reports detection rate. A small fixed-fixture version lives in `tests/` as a regression guard (NLI-model-gated, skipped if model absent).

### New environment variables

`SENTINEL_NLI_MODEL` (default `cross-encoder/nli-deberta-v3-base`), `SENTINEL_NLI_MIN_PROB` (0.6), `SENTINEL_CONSISTENCY_DISPUTE_RATIO` (0.5), `SENTINEL_CONSISTENCY_MAX_CLAIMS` (8), `SENTINEL_CONSISTENCY_MAX_DOMAINS` (20). All in `sentinel.env.example`.

### Resources & stated restrictions

- **Needs:** `transformers` + CPU `torch` (~2 GB disk incl. model, one-time download), one migration, no GPU, no scraping, no new services.
- **Restrictions (state honestly in thesis):** NLI operates in English (ACLED notes and GDELT titles are English — acceptable); GDELT evidence texts are structurally shallower than ACLED notes, so contradiction detection is strongest where feeds overlap; single-source hotspots are only ever "unverified", by design.

## Non-goals (follow-ons, own specs)

- Article-body scraping / RAG over full text (pgvector) — would deepen evidence texts.
- Citation-groundedness verification of SITREP sentences (hallucination-rate metric) — natural next chapter, reuses the same NLI machinery.
- LoRA fine-tuning — rejected on resource grounds.

## Test plan

- Unit: consensus math (status rules, score formula, weight floor), evidence-text rendering, dispute-pattern citation relaxation, claims-mode prompt builder, extraction-JSON validation.
- Integration: seeded hotspot → engine → claims rows + score persisted; headline fallback when NLI absent; `/hotspots/{id}/claims` contract; cascade on hotspot delete.
- Regression: synthetic-injection fixture (model-gated skip).
