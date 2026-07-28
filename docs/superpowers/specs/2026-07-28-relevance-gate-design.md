# Relevance-Gated Consistency Verification — Design (M8)

**Date:** 2026-07-28
**Status:** Approved (brainstorm) — pending implementation
**Spec FR:** new FR-26 (relevance gate + vacuity filter) — to be added to specs.md §4.10
**Owning DOX:** `pipeline/AGENTS.md` (primary), `db/AGENTS.md` (migration 022), `tests/AGENTS.md`
**Depends on:** M7 (FR-25) — real headlines are what made this defect visible and measurable

## Problem

M6 built a correct verification algorithm. M7 gave it real article headlines to work with. With both in place, the engine now produces confident verdicts that are wrong in **both** directions.

Measured on the live database, 2026-07-28, across every claim currently stored:

| Status | Count |
|---|---|
| disputed | 67 |
| uncorroborated | 31 |
| corroborated | 5 |

### False disputes

Hotspot 24874 holds five events, **100% of them carrying enriched GKG headlines** — so this is not a leftover from pre-M7 actor-name titles:

```
Georgia school shooter alleged to have obsession with Parkland killer…   (×3)
Three self-radicalised Singapore teens detained, including 14-year-old…  (×2)
```

Claim extraction worked correctly — four well-formed, specific propositions:

```
Three self-radicalised Singapore teens were detained.                         | disputed
A 14-year-old among the detained teens plotted a school stabbing.             | disputed
A Georgia school shooter allegedly had an obsession with the Parkland killer. | disputed
The Georgia school shooter left behind 'Easter eggs' as a twisted tribute.    | disputed
```

Every claim is judged to contradict the others, so `consistency_score = 0` — "sources disagree" — when the truth is "these are two unrelated news stories."

### False corroboration

The only hotspot in the database scoring above 50 on genuine corroboration is 24795 (87.4). Its eight claims include:

```
Russia is mentioned                      | corroborated
Russia is mentioned                      | corroborated
Russia is mentioned                      | corroborated
Russia is in conflict with employees     | disputed
Authorities are involved in a conflict   | uncorroborated
```

(The eight remaining hotspots above 50 all sit at exactly 50.0 — a single uncorroborated claim each, which is the formula's neutral point, not corroboration.)

Three identical vacuous claims, each scored independently. `is_valid_claim` (FR-22, ≥4 words + one lowercase word) passes `"Russia is mentioned"` — it is grammatical and lowercase, just contentless. Any Russia-mentioning premise entails it.

### Why this is worse than the M6 baseline

Before M7, GDELT-only hotspots produced no valid claims and the engine honestly abstained (`consistency_score` NULL). It now asserts a confident, wrong number instead. For a thesis result, a confident wrong answer is worse than a stated abstention.

## Root cause

`judge_claims` (`pipeline/consistency.py:223`) builds the cross product of every evidence row and every claim, and sends all of it to an MNLI cross-encoder:

```python
pairs = [(item["evidence_text"], claim.text) for claim in claims for item in evidence]
```

MNLI-trained models assume premise and hypothesis describe the **same scene**. That assumption is baked into the training data: two specific statements about different subjects are labelled *contradiction*, not *neutral*. Feeding the model off-scene pairs therefore yields high-confidence contradictions by construction. `consensus` then treats any `contradicts` above `SENTINEL_NLI_MIN_PROB` as a dispute (line 280), and a single contradicting domain is enough to flip a claim.

**The engine has no notion of aboutness.** Nothing asks "are these two texts about the same event?" before asking "does one contradict the other?" Supplying that missing signal is M8.

A contributing upstream cause is recorded but deliberately not fixed here — see Non-goals.

## Decisions taken (brainstorm outcomes)

1. **Semantic relevance via sentence embeddings**, not lexical overlap, LLM grouping, or GDELT metadata. Lexical overlap misses paraphrase ("IDF strike" vs "Israeli forces attacked") and would push genuine corroboration into `uncorroborated`. An extra NIM call reintroduces the network dependency that already failed in M6. GDELT actors are too coarse (`THE US`) to separate unrelated US stories.
2. **No new package dependency.** `all-MiniLM-L6-v2` (~80 MB) runs on the `transformers` stack already installed, via `AutoModel` + mean pooling + L2 normalisation — the same pattern `pipeline/nli.py` uses for `AutoModelForSequenceClassification`. Adding `sentence-transformers` would install a second copy of the same machinery for no functional gain.
3. **Vacuity is detected by discriminative power**, conditioned on evidence diversity (see Component 3 — the conditioning is essential and a naive spread test is wrong).
4. **Fail-closed**, reversing M6's fail-open stance. Justified by measurement: see Error Handling.
5. **Claim deduplication** before judging, so a repeated claim cannot inflate the score.
6. **Gate statistics persisted** so the gate's effect is observable rather than asserted.

## Architecture

```
fetch_hotspot_evidence ──> extract_claims (NIM)
                              │
                              ├─ NEW dedupe_claims
                              ├─ NEW Embedder: embed claims + evidence
                              ├─ NEW vacuity filter    (drops claims)
                              ├─ NEW relevance gate    (marks off-topic pairs neutral)
                              ▼
                           judge_claims (NLI — gated pairs only)
                              ▼
                           consensus ──> consistency_score + gate stats
```

### Component 1 — `pipeline/relevance.py` (new)

Single responsibility: embed text and score pairwise semantic similarity. No DB access, no knowledge of claims, hotspots, or evidence rows. Structured to mirror `pipeline/nli.py` so the two are read the same way.

- `class RelevanceUnavailable(RuntimeError)` — raised on any import or model-load failure, mirroring `NLIUnavailable`.
- `class Embedder` — lazy-loads `SENTINEL_RELEVANCE_MODEL` (default `sentence-transformers/all-MiniLM-L6-v2`) on first use; `_ensure_loaded()` guards, `eval()` mode, CPU only.
  - `embed(texts: list[str]) -> np.ndarray` — mean-pools the last hidden state over the attention mask, then L2-normalises. Batched at 32.
- `similarity_matrix(claims: list[str], evidence: list[str], embedder) -> np.ndarray` — shape `(n_claims, n_evidence)`, cosine similarity (a dot product, since vectors are normalised).
- `evidence_homogeneity(evidence: list[str], embedder) -> float` — median of the pairwise evidence-evidence cosine similarities, excluding the diagonal. Returns `1.0` for fewer than two rows (a single row is trivially homogeneous).

### Component 2 — Relevance gate

In `judge_claims`, a pair is sent to the NLI model only when `sim[c][e] >= SENTINEL_RELEVANCE_MIN_SIM` (default `0.35`). Pairs below the threshold never reach the model and are recorded directly as:

```python
EvidenceJudgment(event_id=…, citation_index=…, domain=…, relation="neutral", probability=0.0)
```

`consensus` already ignores `neutral` (line 265), so no downstream logic changes. The judgment row is still emitted for every (claim, evidence) pair, which keeps the FR-16 citation lockstep and the `claim_evidence` persistence contract intact.

Side effect worth noting: NLI is the expensive step, so gating *reduces* engine runtime rather than adding to it. The embedding pass is O(n) over texts; the NLI pass it replaces is O(claims × evidence).

### Component 3 — Vacuity filter

A vacuous claim is one that every premise entails because it asserts almost nothing. The naive test — "low variance of the claim's similarity vector" — is **wrong**, and the reason matters:

> In a hotspot where all evidence genuinely covers a single event, a good, specific claim is also uniformly similar to every row. A plain spread test would drop it. That is exactly the textbook multi-source corroboration case the engine exists to reward.

The rule is therefore two-part, and the second part is a guard, not a refinement:

1. **Peakedness:** the claim is a candidate for dropping when
   `max(sim[c]) - median(sim[c]) < SENTINEL_RELEVANCE_MIN_PEAK` (default `0.15`)
   — it matches everything and peaks on nothing.
2. **Diversity guard:** the filter only fires when
   `evidence_homogeneity < SENTINEL_RELEVANCE_MAX_HOMOGENEITY` (default `0.75`)
   — i.e. only when the hotspot actually contains distinct topics for a claim to have failed to discriminate between.

Worked through the observed cases:

| Case | Peakedness | Homogeneity | Outcome |
|---|---|---|---|
| `"Russia is mentioned"` vs 8 mixed Russia rows | low (no peak) | low (diverse) | **dropped** |
| `"Three Singapore teens were detained."` in 24874 | high (peaks on 2 of 5) | low (two topics) | kept |
| Specific claim, 5 near-identical headlines | low (no peak) | high (one topic) | kept — guard suppresses the filter |

Dropped claims are counted, not silently discarded (see Component 5). If every claim is dropped, the engine returns no verdicts and `consistency_score` stays NULL — the same honest-abstention path M6 already takes when no claim survives `is_valid_claim`.

### Component 4 — Claim deduplication

Before embedding, collapse claims whose normalised text (casefolded, whitespace-collapsed, trailing punctuation stripped) is identical. The surviving claim keeps the union of the duplicates' `source_indices`. This is what hotspot 24795 needed: three `"Russia is mentioned"` rows each contributed independent weight to the score.

Deduplication is deliberately exact-match, not similarity-based. Similarity-based merging would need its own threshold and could collapse two genuinely distinct claims about the same actors; exact-match fixes the observed defect with no tunable.

### Component 5 — Gate statistics

Migration **022** (021 is `event_hotspot_is_noise`) adds two nullable columns to `hotspots`:

- `gated_pairs INTEGER` — pairs suppressed by the relevance gate
- `vacuous_claims_dropped INTEGER` — claims removed by the vacuity filter

Both are written by the engine alongside `consistency_score`. Without them the thresholds would be tuned blind and the evaluation could not quantify the gate's effect. They are not exposed in the API or dashboard in M8 — they exist for tuning and for the thesis writeup.

## Error handling

| Failure | Behaviour |
|---|---|
| `RelevanceUnavailable` (torch/transformers/model missing) | Engine **skips**; `consistency_score` NULL; SITREP falls back to the FR-11 headline prompt |
| `SENTINEL_RELEVANCE_ENABLED=false` | Gate and vacuity filter disabled; pure M6 behaviour (documented as known-degraded) |
| Every claim dropped as vacuous | No verdicts; `consistency_score` NULL — same path as no claim surviving `is_valid_claim` |
| Every pair gated out for a claim | Claim is `uncorroborated` (no support, no dispute) — the correct verdict for a claim with no on-topic evidence |
| NLI unavailable | Unchanged from M6: engine skips, score NULL |

### The fail-closed reversal

M6's contract was fail-open: if a model is unavailable, degrade rather than block. M8 reverses this for the relevance model specifically. The justification is empirical — ungated judging is now *measured* to be wrong on 65% of claims, so "degrade to M6 behaviour" means "degrade to known-bad output". Abstention is already the engine's stated philosophy when it cannot do its job honestly (FR-22: "zero surviving claims ⇒ engine skips"). `SENTINEL_RELEVANCE_ENABLED=false` remains the operator escape hatch for a deliberate, informed downgrade.

The pipeline itself is still never blocked: a skipped engine leaves `consistency_score` NULL and FR-23 falls back to the headline prompt, exactly as today.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `SENTINEL_RELEVANCE_ENABLED` | `true` | Kill switch |
| `SENTINEL_RELEVANCE_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Embedding model |
| `SENTINEL_RELEVANCE_MIN_SIM` | `0.35` | Gate threshold |
| `SENTINEL_RELEVANCE_MIN_PEAK` | `0.15` | Vacuity peakedness threshold |
| `SENTINEL_RELEVANCE_MAX_HOMOGENEITY` | `0.75` | Diversity guard |

**All four numeric defaults are starting points, not derived values.** They are to be tuned on the gold set during evaluation, and the implementation plan must say so rather than presenting them as principled. Final values land in `sentinel.env.example` and specs.md after the eval run.

## Testing

- **Unit (`tests/test_relevance.py`, no network):** `RelevanceUnavailable` on a bogus model name; embeddings L2-normalised; `similarity_matrix` shape and symmetry; `evidence_homogeneity` returns 1.0 for a single row; identical texts score ≈1.0, unrelated texts score low. Real-model tests gated behind an opt-in env flag, mirroring `SENTINEL_NLI_TEST=1`.
- **Engine unit (`tests/test_consistency.py` additions):** a fake embedder injected by parameter (per the `tests/AGENTS.md` rule — fakes are injected, never `unittest.mock.patch`) proves: off-topic pairs are marked `neutral` and never reach the judge; a vacuous claim is dropped in a diverse hotspot; the same claim is **kept** in a homogeneous hotspot; duplicate claims collapse with merged `source_indices`.
- **Regression fixture:** hotspot 24874's real headlines (Georgia shooter × 3, Singapore teens × 2) frozen as a fixture, asserting the claims are **not** all disputed. This is the bug, pinned.
- **Integration (live DB):** migration 022 columns populated after an engine run.
- **Contradiction injection:** the existing `eval/consistency/inject.py` — a planted, genuinely contradicting evidence row must still be detected through the gate. This guards the gate's own dangerous failure mode and is the single most important test in M8.

## Evaluation (thesis)

Two parts:

1. **Automated regression** — the injection harness above. Reproducible, no labelling, proves the gate does not suppress true contradictions.
2. **Hand-labelled gold set** — ~30 hotspots from the live database, each claim labelled corroborated / uncorroborated / disputed by hand, scored with the existing `eval/consistency/score_gold.py`. Reported as before/after verdict accuracy against the M8-entry baseline below.

### The baseline figure (corrected 2026-07-28)

An earlier draft of this document quoted **5 corroborated / 31 uncorroborated / 67 disputed**. That measurement was taken over a database whose `events.title` column had been corrupted by a buggy pre-fix run of the M7 backfill: one headline had been written across 7,825 rows spanning 2,727 distinct URLs, so many claims were extracted from evidence text that did not belong to its article. **Do not use that figure.**

The database was rebuilt from scratch and re-ingested from GDELT with the fixed code. The clean baseline is:

| Status | Count |
|---|---|
| disputed | 32 |
| uncorroborated | 31 |
| **corroborated** | **0** |

over 63 claims / 24 scored hotspots / 319 GDELT events (318 enriched, 98 distinct titles — a healthy ~1 title per article). Of 24 scored hotspots, 7 score exactly 0 (every claim disputed) and 13 score exactly 50 (every claim uncorroborated, the formula's neutral point).

The corrected numbers **strengthen** the case rather than weakening it: on clean data there is not a single corroborated claim anywhere in the database, and the 5 that previously appeared were the duplicate `"Russia is mentioned"` artifact. The diagnosis is unchanged and was re-confirmed end to end on clean data — hotspot 8 ("India", 13 events) mixes an Indian government/Meta story, a Rajya Sabha adjournment, a Chief Justice of Pakistan protest warning, and a lathicharge ruling, and marks all five well-formed claims disputed, rendering "Phát hiện mâu thuẫn giữa các nguồn" ("contradiction detected between sources") in the dashboard.

The harness (`export_gold.py`, `score_gold.py`, `inject.py`) exists from M6 but **no gold set was ever created** — building it is real work in this milestone, not a formality, and the plan must budget for it.

## Non-goals (deliberate)

- **Raising `SENTINEL_MIN_GEO_PRECISION` from 2 to 3.** All five events in hotspot 24874 sit on the Florida state centroid `(27.83, -81.72)` at `geo_precision = 2`, which is the upstream reason two unrelated stories share a hotspot at all. Raising the floor would remove that cause, but it drops 196 currently-clustered events across 38 hotspots — real data loss on an already-sparse GDELT-only feed — and it does not address topical mixing among genuinely co-located events, which the gate must handle regardless. **Deferred until the gate has been measured**, at which point the trade-off can be decided on evidence.
- **Requiring 2+ contradicting domains for a dispute.** Would mechanically reduce the dispute count, but treats the symptom rather than the off-topic cause, and would suppress genuine single-source contradictions — arguably the most valuable finding an OSINT tool can surface.
- **Topical clustering of evidence into event groups.** A richer formulation of the same idea (cluster the evidence, judge within clusters). The pairwise threshold gate captures most of the benefit with one threshold instead of a clustering algorithm; revisit only if the eval shows the gate is the limiting factor.
- Changes to `conf_score` (FR-7/8/9), which remains locked.

## Risks

- **The gate suppresses genuine disputes.** The central risk, and the reason the injection harness is mandatory rather than optional. A real contradiction between two sources reporting the same event should score high similarity, so it should pass the gate — but this is an assumption until measured.
- **Threshold sensitivity.** Three numeric thresholds, all untuned at design time. Mitigated by the gate statistics columns and by tuning on the gold set rather than by intuition.
- **Model download on first run.** ~80 MB from HuggingFace, cached thereafter. On an 8 GB M1 running alongside the ~400 MB NLI cross-encoder this is acceptable, but both models resident simultaneously should be confirmed during implementation.
- **Vacuity thresholds interact with claim quality.** If M7's backfill substantially improves evidence text, fewer vacuous claims will be extracted and the filter may rarely fire. That is a good outcome, but it means the filter's value should be measured on data captured *after* the backfill completes, not before.
