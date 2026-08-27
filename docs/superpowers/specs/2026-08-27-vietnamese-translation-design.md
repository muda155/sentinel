# Vietnamese Translation of SITREP and Claims — Design (M10)

**Date:** 2026-08-27
**Status:** Approved (brainstorm) — pending implementation
**Spec FRs:** new FR-30 (display translation of LLM-generated text) — to be added to specs.md §4.12. **Amends FR-17**, which explicitly excludes this (see "Amendment to FR-17" below)
**Owning DOX:** `api/AGENTS.md`, `pipeline/AGENTS.md`, `frontend-next/AGENTS.md`, `tests/AGENTS.md`

## Problem

FR-17 shipped a bilingual UI with **Vietnamese as the default locale** (`frontend-next/lib/i18n-core.ts:5`), but it localizes chrome only — the 179 dictionary keys in `lib/locales/vi.ts` cover labels, buttons and status text. Every string the system actually *produces* is English:

| Text | Produced by | Stored in |
|---|---|---|
| SITREP `summary` | `build_claims_sitrep_prompt` (`pipeline/llm_verifier.py:45`) | `llm_summaries.summary_text` |
| Claim text | `build_claims_prompt` (`pipeline/consistency.py:141`) | `claims.claim_text` |

The result is a panel with Vietnamese headings wrapped around English analysis — the two sections a Vietnamese reader most needs (AI Intelligence Brief, Evidence & Consistency) are exactly the two that stay untranslated.

**`llm_summaries.conflict_detail` is deliberately out of scope.** The pipeline writes it, but no API query selects it and no component renders it — `fetch_hotspot_summary` returns `summary`, `conflict_detected`, `sources_cited`, `conf_score`, `convergence_score` and nothing else, and the panel's conflict line is the already-localized `t("detail.conflictDetected")`, not the model's text. Translating a column nothing displays would be dead work; surfacing it first is a separate change.

## Amendment to FR-17

FR-17's final sentence reads:

> Place names, article titles, and SITREP text remain English; the API and database are not localized.

That is not an omission this design fills in — it is a decision this design **reverses in part**, and the spec must say so rather than accumulate two clauses that contradict each other. FR-30 changes exactly one clause and leaves the rest standing:

| FR-17 clause | Under FR-30 |
|---|---|
| Place names remain English | **unchanged** |
| Article titles remain English | **unchanged** — deliberately (§ Decisions, 1) |
| SITREP text remains English | **amended** — English in every data endpoint, with display translation served separately |
| The database is not localized | **unchanged** — no translated column, no migration |
| The API is not localized | **narrowed** — data endpoints stay English; one new endpoint serves translations |

FR-17's sentence is to be rewritten accordingly in the same commit that adds FR-30, and the same claim appears in `frontend-next/AGENTS.md` ("Place names, titles, SITREPs stay English") — see §7.

## Constraint that shapes everything

**Claims cannot be generated in Vietnamese.** The FR-22 NLI cross-encoder (`cross-encoder/nli-deberta-v3-base`) and the FR-26 relevance gate (`all-MiniLM-L6-v2`) are English-only models. Vietnamese claims judged against English evidence would silently corrupt entailment, and every measurement in the final report — the 74.6% / 95.1% gold-set figures, the gate before/after, `consistency_score` itself — was taken on English text.

Therefore: **English stays canonical; Vietnamese is a display layer.** Nothing in this design writes to `claims`, `llm_summaries`, or `hotspots`, and no scoring path reads a translated string. This is stated in the UI (see §4) rather than hidden, because it is the honest account of why the analysis is English.

## Decisions taken (brainstorm outcomes)

1. **Scope is SITREP + claims only.** Not article titles — those are quoted source material, and a translated headline no longer matches the article it links to. Not the FR-29 window report; that is a possible follow-on with its own cache key.
2. **Google Cloud Translation v2 (Basic), not an LLM.** Rationale in §1.
3. **Automatic when `locale === "vi"`**, not a button. Affordable because the cache is keyed on content, so cost scales with distinct hotspots, not with views.
4. **Display-only, cache-only.** No migration, no new table, no new column. Redis or nothing.
5. **Google is the sole backend.** No LLM fallback path — an absent `GOOGLE_TRANSLATE_API_KEY` means the panel stays English, which is a correct outcome, not an error.

## Non-goals

- Translating into any language other than Vietnamese (the response contract carries `lang`, but only `vi` is accepted).
- Translating article titles, source domains, place names, or hotspot names.
- Persisting translations to Postgres.
- Any change to `conf_score`, `consistency_score`, the NLI path, or the relevance gate.

## 1. Why Google Translate rather than the NIM/Ollama LLM

An earlier draft of this design translated via a JSON prompt to the existing LLM. Cloud Translation is better on every axis that matters here:

| | LLM (NIM / Ollama) | Cloud Translation v2 |
|---|---|---|
| Latency | 2–5 s | ~100–300 ms |
| Cost | consumes the NIM quota | 500k chars/month free, then $20/M |
| `[N]` marker safety | prompt-instructed | structurally enforced (§2) |
| Can drop or invent a claim | yes — needs a rejection guard | no |
| VI quality on an Ollama-only host | poor (`llama3.2:3b`) | identical everywhere |

The quota argument is concrete: `979a4df` ("back off 429 on a quota schedule, not the 5xx one") and `f7d846c` ("log 429 recovery") are both NIM rate-limit work from the last five commits. An auto-firing per-panel LLM call would land on exactly that pressure. Translation is not a reasoning task and should not spend reasoning quota.

**Cost at project scale:** a SITREP (~400 chars) plus 8 claims (~800 chars) ≈ 1.2k chars per hotspot, so the free monthly allowance covers ~400 distinct hotspots before the cache does any work. Past that, 1,000 hotspots costs ~$0.024.

**Why v2 and not v3/Advanced:** v2 accepts a plain API key as a query parameter; v3 rejects API keys and requires a service account. v2 needs no `google-cloud-*` SDK and no credential JSON on disk — just `requests` and one env var, matching how `pipeline/gkg.py` and `pipeline/ingestion.py` already call external APIs. v3's glossary support is not needed.

## 2. Citation integrity

SITREP sentences must end in `[N]` (FR-11/FR-12), and those markers drive click-to-jump in the detail panel. Google honors `<span translate="no">…</span>`, **but only when `format: "html"`** — segments cannot be selectively excluded in `text` mode. So the pipeline is:

1. **Protect** — wrap every `[N]` occurrence: `Forces advanced [1].` → `Forces advanced <span translate="no">[1]</span>.`
2. **Translate** — `format: "html"`, `source: "en"`, `target: "vi"`.
3. **Restore** — strip the wrapper spans and unescape HTML entities (HTML mode returns `&#39;`, `&amp;` and friends).

Markers are then preserved by the API's contract rather than by a model's compliance.

**Assertion, retained:** after restore, compare the multiset of `[N]` tokens against the source and run `validate_citations()` on the translated summary. The validator is language-agnostic — it only requires sentences to end in `[N].`, and Vietnamese uses the same terminal punctuation. If either check fails, return the **English** summary with `summary_translated: false`. A mistranslated citation is worse than untranslated text. This should never trip; it exists so that a Google-side behavior change degrades visibly rather than silently.

Claims carry no citation markers and translate unconditionally.

*Known caveat:* Google's own troubleshooting docs note that wrapping special tokens in `notranslate` spans can affect the quality of the surrounding translation. Verify once against a real SITREP during implementation.

## 3. Backend

### 3.1 `pipeline/translate.py` (new)

Pure helpers plus one thin HTTP client, mirroring `pipeline/window_report.py`'s split of logic from orchestration.

```
protect_citations(text) -> str          # [N] -> <span translate="no">[N]</span>
restore_citations(html) -> str          # unwrap spans, unescape entities
citation_markers(text) -> list[str]     # multiset extraction for the guard
translate_batch(strings, *, target, api_key, timeout) -> list[str]
translate_enabled() -> bool             # SENTINEL_TRANSLATE_ENABLED and key present
translate_timeout() -> int
```

`translate_batch` POSTs to `https://translation.googleapis.com/language/translate/v2?key=…` with `{q: [...], source: "en", target: "vi", format: "html"}` and returns `data.translations[].translatedText` in request order.

> **Verify during implementation:** the v2 reference documents `q` as repeatable, but the current docs page does not state ordering guarantees for a multi-`q` request the way v3's `contents[]` does. Confirm with a live two-string call that responses come back in input order. If they do not, fall back to one request per string — still far cheaper and faster than one LLM call. This must be settled before the batching path ships.

The three `citations` helpers are pure and fully unit-testable with no network.

### 3.2 `api/cache.py` (new, small)

`api/routes/report.py` holds a module-level Redis singleton (`_redis()`, 1s connect/socket timeouts, failures swallowed and logged). The translation route needs the same thing. Lift it into `api/cache.py` as `redis_client()` / `cache_get_json()` / `cache_setex_json()` and switch `report.py` to it. Behavior unchanged — this is a targeted de-duplication of code the change touches anyway, not a refactor of its own.

### 3.3 `api/routes/translate.py` (new)

`GET /hotspots/{hotspot_id}/translation?lang=vi`

Built on `report.py`'s guard pattern:

- **Auth** — Bearer via `get_current_user`, like every other endpoint.
- **Rate limit** — its own `limit_translate` bucket, `SENTINEL_TRANSLATE_RATE_PER_MIN`, default **20**. The report bucket's 4/min would 429 an analyst clicking through five hotspots; the shared 60/min bucket in front of a paid external API is the cost hole `api/AGENTS.md` already warns about for `/report`.
- **Reads** — `queries.fetch_hotspot_summary` and `queries.fetch_hotspot_claims`, both existing. **No new SQL, no DB writes.**
- **Cache key** — `sha256(lang + hotspot_id + summary + sorted("claim_id:claim_text"))`, prefix `sentinel:translation:`, TTL `SENTINEL_TRANSLATE_TTL_S` (default 86400). Keyed on **content, not ids**: the pipeline rewrites `claims` every tick, so a re-scored hotspot must get a fresh translation while an unchanged one never re-pays.
- **Budget cap** — refuse to send more than `SENTINEL_TRANSLATE_MAX_CHARS` (default 5000) in one request; claims beyond the cap are returned untranslated rather than silently dropped. Bounds spend on a pathological hotspot and stays under the v2 request-size limit.
- **Metrics** — `api/metrics.py` is a flat in-process counter map (`METRICS.inc("alerts_total")`, `METRICS.observe("llm_latency_seconds", …)`) rendered as `f"{name} {value:g}"`. It has **no label support**, so use flat names — `translation_requests_total`, `translation_cache_hits_total`, `translation_errors_total`, and `METRICS.observe("translation_latency_seconds", …)`. Declared in `metrics.py`, per the api DOX rule. (`/report` currently exports no metrics; this is an addition, not a pattern to copy from.)

Status codes:

| Condition | Response |
|---|---|
| hotspot does not exist (`fetch_hotspot_summary` is None) | 404 |
| `lang` not `vi` | 422 |
| translation disabled or no API key | 503 |
| Google call fails, times out, or returns a non-200 | 503 |
| hotspot exists but has no summary and no claims | 200, empty payload, **no upstream call** |
| citation guard trips | 200, English summary, `summary_translated: false` |

Note `fetch_hotspot_summary` `COALESCE`s a missing `llm_summaries` row to `''`, so "no summary" and "no hotspot" are distinguishable only by the None return — hence the table above.

### 3.4 Response schema (`api/schemas.py`)

```
TranslatedClaim:  claim_id: int, text: str
Translation:      lang: str
                  summary: str
                  summary_translated: bool
                  claims: list[TranslatedClaim]
                  cached: bool
```

Per api DOX, these field names are the API contract once shipped.

## 4. Frontend

- **`lib/api.ts`** — `fetchTranslation(id, lang)` plus the `Translation` type.
- **`lib/translation.ts`** (new) — pure helpers so the logic is testable outside React, matching `lib/window-consistency.ts`:
  - `shouldTranslate(locale, summary, claims)` — false when locale is `en`, or when there is nothing to translate.
  - `applyTranslation(summary, claims, translation, showOriginal)` — returns the display strings, falling back to English on a null translation or `showOriginal`.
- **`components/HotspotDetail.tsx`** — the fetch effect fires when `shouldTranslate(...)` is true, guarded by a `useRef` generation counter exactly like the existing claims fetch (`claimsGen`), because panels switch faster than requests return.
- **Render** — translated strings replace the English in the Brief and Evidence sections; `parseCitations` runs on the translated summary, unchanged. English renders immediately and the Vietnamese swaps in when it lands — the panel never blocks on a spinner.
- **Disclosure** — a muted line under the Brief heading: *"Bản dịch tự động · phân tích gốc bằng tiếng Anh"*, with a **Xem bản gốc** toggle that flips back to English (component state, not persisted). When `summary_translated` is false the badge reads translation-unavailable for that field. This line is load-bearing for the defence: it is where the design states that NLI and the relevance gate ran on English.
- **New locale keys** in both `en.ts` and `vi.ts` — `detail.autoTranslated`, `detail.showOriginal`, `detail.showTranslation`, `detail.translationUnavailable`. `vi.ts` is typed `Record<MessageKey, string>` against `en.ts`, so a missing key is a type error.
- **Degradation** — any failure (503, timeout, network) leaves the panel English with no error UI. English is a correct fallback, not a broken state.

## 5. Configuration

New env vars, added to `sentinel.env.example` and the CLAUDE.md env list:

| Var | Default | Purpose |
|---|---|---|
| `GOOGLE_TRANSLATE_API_KEY` | *(unset)* | Cloud Translation v2 key. Unset ⇒ feature off, panel stays English. |
| `SENTINEL_TRANSLATE_ENABLED` | `true` | Kill switch independent of the key. |
| `SENTINEL_TRANSLATE_RATE_PER_MIN` | `20` | `limit_translate` bucket. |
| `SENTINEL_TRANSLATE_TIMEOUT_S` | `10` | Google is sub-second; a long timeout only pins a worker. |
| `SENTINEL_TRANSLATE_TTL_S` | `86400` | Redis TTL. |
| `SENTINEL_TRANSLATE_MAX_CHARS` | `5000` | Per-request budget cap. |

Never hard-coded, per the root DOX environment rule.

## 6. Testing

**`tests/test_translate.py`** (pipeline, no network)
- `protect_citations` wraps every marker including `[i][j]` dispute pairs.
- `restore_citations` round-trips: `restore(protect(x)) == x`, and unescapes entities.
- `citation_markers` counts duplicates as a multiset, not a set.
- `translate_enabled()` false when the key is absent or the kill switch is off.

**`tests/test_api_translate.py`** (fake Redis via `fakeredis`, stubbed HTTP)
- 401 unauthenticated.
- 404 unknown hotspot; 422 on `lang=fr`; 503 with no key.
- Cache hit returns `cached: true` **without** an upstream call.
- Content-keyed invalidation: changing one claim's text produces a different key.
- Citation guard: a stubbed response with a dropped marker returns the English summary and `summary_translated: false`.
- Empty hotspot (no summary, no claims) returns 200 and makes no upstream call.
- Budget cap leaves over-cap claims untranslated.
- **`_translate_bucket` must be added to `conftest._reset_rate_limit_buckets`** — the autouse fixture that currently replaces `_bucket`, `_auth_bucket` and `_report_bucket`. `api.ratelimit` buckets are session-wide singletons keyed on client IP, and every `TestClient` request presents the same key, so an unreset bucket hands a 429 to whatever unrelated test happens to exhaust it. Because refill is wall-clock, which test loses depends on runner speed — it looks like a flake but is reproducible.

**`frontend-next/__tests__/translation.test.ts`**
- `shouldTranslate` false for `en`, false for empty content, true otherwise.
- `applyTranslation` falls back to English on null and on `showOriginal`.
- Marker preservation through the display path.

**Regression:** `tests/test_api_report.py` must still pass after `report.py` switches to `api/cache.py`.

**Key parity is already enforced:** `__tests__/i18n.test.ts` asserts `Object.keys(vi) == Object.keys(en)`, on top of the `Record<MessageKey, string>` type constraint. The four new keys need no new test.

## 7. Documentation updates

### 7.1 Statements that FR-30 falsifies — correct in the shipping commit

These four are **true today** and must not be edited before the code lands; each is verified stale-on-ship, not stale now. They are the DOX "Update After Editing" obligation for this change, and the implementation plan carries them as a closing task.

| File | Text that becomes false | Correction |
|---|---|---|
| `specs.md` FR-17 | "Place names, article titles, and SITREP text remain English; the API and database are not localized." | Rewrite per the "Amendment to FR-17" table. |
| `frontend-next/AGENTS.md` (i18n bullet) | "Place names, titles, SITREPs stay English." | Titles and place names still do; SITREP/claims gain a display translation. Add the canonical-English rule and the disclosure requirement. |
| `api/AGENTS.md` (`/report` bullet) | "`GET /hotspots/{id}/report` … is the **only user-triggered LLM call in the API**" | Still the only user-triggered *LLM* call — `/translation` calls an external translation API, not an LLM. Narrow the wording to say that, so the distinction is deliberate rather than accidentally false. |
| `tests/AGENTS.md` (bucket bullet) | "replaces `api.ratelimit._bucket`, `_auth_bucket` and `_report_bucket`" | Add `_translate_bucket` to the enumeration. |

### 7.2 Additions

- **`api/AGENTS.md`** — the new endpoint contract: separate `limit_translate` bucket and why, content-keyed cache and why keying on ids would serve stale text, the no-DB-writes property, and the citation guard.
- **`pipeline/AGENTS.md`** — `translate.py`'s purpose, the protect/restore contract, and the `format: "html"` requirement (`notranslate` has no effect in `text` mode).
- **`frontend-next/AGENTS.md`** — English is canonical; the disclosure line is required, not decorative; citation markers must survive the display path.
- **`tests/AGENTS.md`** — the two new Python test files and the frontend one.
- **`specs.md`** — add §4.12 and FR-30, bump Document Version to **1.14.0** (§4.11/M9 is currently the last section), add the history row.
- **`sentinel.env.example`**, **`CLAUDE.md`** env list — the six vars in §5.

## 8. Risks

| Risk | Mitigation |
|---|---|
| v2 multi-`q` ordering unconfirmed | Verify with a live call before shipping the batch path; fall back to per-string requests. Blocking, settled in the first implementation task. |
| `notranslate` spans degrade surrounding quality | Eyeball one real SITREP during implementation; the guard catches marker damage regardless. |
| Auto-trigger cost surprise | Content-keyed cache + 20/min bucket + 5000-char cap. Free tier covers ~400 distinct hotspots/month before caching. |
| API key leaks into a client bundle | The key lives server-side only; the browser calls Sentinel's endpoint, never Google. Never expose it via `NEXT_PUBLIC_*`. |
| Sending hotspot text to Google | The corpus is public news headlines already fetched from public feeds. Worth one line in the report's ethics/limitations section. |
