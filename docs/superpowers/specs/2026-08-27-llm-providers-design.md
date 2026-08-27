# Multi-Provider LLM Chain (DeepSeek, Kimi) — Design (M11)

**Date:** 2026-08-27
**Status:** Approved (brainstorm) — pending implementation
**Spec FRs:** new FR-31 (LLM provider chain and paid-tier gate) — to be added to specs.md §4.13
**Owning DOX:** `pipeline/AGENTS.md`, `api/AGENTS.md`, `tests/AGENTS.md`

## Problem

Step 6 has exactly two providers, hard-wired: NVIDIA NIM, falling back to Ollama.
`call_llm_raw` (`pipeline/llm_verifier.py:264`) takes `endpoint`, `api_key`, `model`
and `ollama_endpoint` as positional configuration and encodes the NIM-to-Ollama
fallback as control flow — five separate `return call_ollama_raw(...)` statements,
one per failure class.

Three call sites each re-read the same NIM environment variables to feed it:

| Call site | Reads |
|---|---|
| `pipeline/workers/llm_worker.py:33` | `NVIDIA_NIM_ENDPOINT`, `NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_MODEL`, `OLLAMA_ENDPOINT` |
| `pipeline/consistency.py:165` (`_default_llm`) | the same four |
| `api/routes/report.py:73` | the same four |

Adding a provider therefore means editing a 100-line function whose paths are all
named after one vendor, and repeating the env plumbing at three sites. Adding two
providers means doing it twice.

The immediate operational pressure: NIM is unreachable from this deployment. It
completes the TLS handshake and never answers, so every call burns the full
`SENTINEL_LLM_TIMEOUT_S` (60s) before the fallback runs. A measured SITREP for
hotspot 12622 on 2026-08-27 took **512.6s**, of which 120s was two dead NIM
attempts and the rest was `llama3.2:3b` doing claim extraction, the NLI pass, a
citation-repair re-prompt and the narrative. At that rate the current backlog of
roughly 1000 unsummarised hotspots is about six days of continuous generation.

## Decisions taken (brainstorm outcomes)

1. **Ordered fallback chain**, not a single configured primary and not per-task
   routing. One env var lists providers in order; each is tried in turn.
2. **Paid providers are gated on `conf_score`.** Below the threshold a hotspot is
   summarised locally by Ollama; above it, the full chain runs. Accepted with the
   consequence recorded in *Risks* below.
3. **One adapter for the OpenAI-compatible providers.** NIM, DeepSeek and Kimi
   share `/chat/completions` request and response shapes; only base URL, key and
   model differ. Ollama's `/api/generate` keeps its own function.
4. **No gateway dependency** (LiteLLM or similar). It would hide retry and
   fallback behaviour that is deliberately tuned here — see the 429 wait cap in
   §3 — for three providers that share one API shape.

## Non-goals

- **Token and cost accounting.** All three paid providers return `usage` on every
  response, but `api/metrics.py` is a flat counter map with no label support and
  nothing consumes spend data today. Counting calls per provider is in scope;
  converting calls to currency is not.
- **Per-task routing.** Claim extraction and the SITREP for a given hotspot must
  use the same model (§4); splitting them by task is the opposite of that.
- **Streaming responses.** Nothing in the pipeline consumes partial output.
- **Changing prompts, retry counts, or the citation-repair pass.** This design
  moves transport only. Any output difference must be attributable to the model,
  not to a prompt edited in the same change.

## Model selection: what "cheapest" means as of 2026-08-27

Verified against vendor pricing pages on the day of writing, not from memory —
**both defaults are wrong within a release cycle and must be treated as such.**

| Provider | Cheapest model | Input $/M | Output $/M |
|---|---|---|---|
| DeepSeek | `deepseek-v4-flash` | 0.22 off-peak / 0.44 peak | 0.66 off-peak / 1.32 peak |
| Kimi (Moonshot) | `kimi-k2.5` | 0.60 | 3.00 |

Two facts that a stale default would get wrong:

- **`deepseek-chat` was retired on 2026-07-24.** It is now a deprecated alias.
  Anything pinning it is on borrowed time; `deepseek-v4-flash` is the successor.
- **DeepSeek moved to peak/off-peak billing on 2026-08-16.** Peak hours are
  01:00–04:00 and 06:00–10:00 UTC; all other hours bill at 50%. The scheduler runs
  every `SENTINEL_POLL_INTERVAL_S` around the clock, so both rates apply and the
  effective cost sits between them.

DeepSeek is 2–3× cheaper on input and 4.5× cheaper on output than Kimi, which is
why it leads the default chain. Estimated cost at two calls per hotspot
(claim extraction plus SITREP), ~3k input tokens each and the existing 500-token
`SENTINEL_LLM_MAX_TOKENS` ceiling: about **$0.002–0.004 per hotspot** on DeepSeek
and **$0.007** on Kimi — $2–7 to clear the current backlog.

Model names are env-configurable precisely because these numbers expire. The
defaults are a starting point with a date on them, not a maintained ranking.

## 1. `pipeline/llm_providers.py` (new)

All transport moves here, including `call_ollama_raw`, which is relocated from
`llm_verifier` unchanged. `llm_verifier` keeps prompt building, parsing, citation
validation and repair — the things that are about *what* is asked, not *who*
answers.

```python
@dataclass(frozen=True)
class Provider:
    name: str
    kind: str                 # "openai" | "ollama"
    endpoint_env: str
    endpoint_default: str
    key_env: str | None       # None => no credential needed (ollama)
    model_env: str
    model_default: str
    paid: bool
```

| name | endpoint default | key env | model default | paid |
|---|---|---|---|---|
| `deepseek` | `https://api.deepseek.com/v1/chat/completions` | `DEEPSEEK_API_KEY` | `deepseek-v4-flash` | yes |
| `kimi` | `https://api.moonshot.ai/v1/chat/completions` | `MOONSHOT_API_KEY` | `kimi-k2.5` | yes |
| `nim` | `https://integrate.api.nvidia.com/v1/chat/completions` | `NVIDIA_NIM_API_KEY` | `meta/llama-3.3-70b-instruct` | yes |
| `ollama` | `http://localhost:11434` | — | `llama3:8b` | no |

Public surface:

- `resolve_chain(*, paid_allowed: bool) -> list[Provider]` — parses
  `SENTINEL_LLM_PROVIDERS`, drops unknown names with a warning, drops providers
  whose `key_env` is unset, and drops paid providers entirely when
  `paid_allowed` is false.
- `call_llm(prompt, *, conf_score=None, retries=3, timeout=None) -> (str, str)` —
  the chain runner.
- `call_openai_compatible(prompt, *, provider, retries, timeout) -> (str, str)`
- `call_ollama_raw(prompt, endpoint, timeout) -> (str, str)` — moved verbatim.

**Dropping an unconfigured provider is not a failure.** It happens when the chain
is built, before any request, and mirrors how `translate_enabled()` and
`acled_credentials_configured()` already gate optional integrations. A chain that
resolves to nothing raises `NoProviderConfigured` — the honest answer, distinct
from every provider being tried and failing.

## 2. Configuration

| Variable | Default | Meaning |
|---|---|---|
| `SENTINEL_LLM_PROVIDERS` | `deepseek,kimi,ollama` | ordered chain |
| `SENTINEL_LLM_PAID_MIN_CONF` | `70` | `conf_score` above which paid providers may be used |
| `DEEPSEEK_API_KEY` | unset | server-side only |
| `DEEPSEEK_ENDPOINT` | see table | |
| `DEEPSEEK_MODEL` | `deepseek-v4-flash` | |
| `MOONSHOT_API_KEY` | unset | server-side only |
| `MOONSHOT_ENDPOINT` | see table | |
| `MOONSHOT_MODEL` | `kimi-k2.5` | |

`NVIDIA_NIM_*`, `OLLAMA_ENDPOINT`, `SENTINEL_OLLAMA_MODEL` (code default `llama3:8b`;
this deployment sets `llama3.2:3b`), `SENTINEL_LLM_TIMEOUT_S`,
`SENTINEL_LLM_TEMPERATURE`, `SENTINEL_LLM_MAX_TOKENS`,
`SENTINEL_LLM_RATELIMIT_BACKOFF_S` and `SENTINEL_LLM_RATELIMIT_MAX_WAIT_S` keep
their current names and meanings.

**`nim` is absent from the default chain.** It stays fully implemented, and any
deployment that wants it back adds it to `SENTINEL_LLM_PROVIDERS`. Leaving a
provider that never answers at the head of the default chain would cost 60s on
every call for nothing, which is the condition this design was written under.

Neither API key may ever appear in a `NEXT_PUBLIC_*` variable or reach the
browser, on the same grounds as `GOOGLE_TRANSLATE_API_KEY` (FR-30).

## 3. Chain semantics

For each provider in the resolved chain, in order:

| Outcome | Action |
|---|---|
| 2xx | return `(content, f"{provider.name}:{model}")` |
| Timeout | log, fall through to the next provider |
| Connection error | log, fall through |
| 429 | existing backoff: `Retry-After` when stated, else exponential, capped by `SENTINEL_LLM_RATELIMIT_MAX_WAIT_S`; on cap or exhausted retries, fall through |
| 5xx | retry up to `retries` with exponential backoff, then fall through |
| 401 / 402 / 403 | **fall through immediately, no retries** |
| 400 | **raise** — do not fall through |

Two rows carry the reasoning that is not obvious:

**401/402/403 are not retried.** A rejected key, an exhausted quota and a
disentitled account do not resolve within a tick, and retrying one only burns the
worker's time. This is the same conclusion `_fetch_page_with_retry` reached for
ACLED's 403 (`pipeline/AGENTS.md`), and it is worth stating in the log at WARNING
with the provider name, because a silently-skipped paid provider looks identical
to one that was never configured.

**400 raises rather than falling through.** A malformed request is our bug, and
every provider in the chain will reject it identically. Falling through would turn
one loud error into three quiet ones and end at Ollama, which would then answer a
prompt the paid providers refused — the worst possible outcome, because the run
looks successful.

**The 429 wait cap carries over unchanged.** It exists because the worker is
single-threaded: parking it past the cap stalls every other hotspot behind the
one being rate-limited. That reasoning is unaffected by the number of providers.

`model_used` becomes `"<provider>:<model>"` (e.g. `deepseek:deepseek-v4-flash`)
**for the OpenAI-compatible providers only**. `call_ollama_raw` keeps its existing
tag untouched (`llama-3-8b-ollama` for the default model, `<model>-ollama`
otherwise): that string is the historical audit tag named in FR-12's acceptance
criteria, and reformatting it would silently invalidate every stored row that
carries it. Both forms satisfy `llm_worker`'s existing
`"ollama" in model_used.lower()` fallback check.

The effect either way is that `llm_summaries.llm_model_version` records which
vendor wrote each SITREP, which is what makes the confound in *Risks* auditable
after the fact rather than merely acknowledged.

## 4. The paid-tier gate

`conf_score` decides which providers a hotspot may use:

```
conf_score >  SENTINEL_LLM_PAID_MIN_CONF  ->  full chain (deepseek, kimi, ollama)
conf_score <= SENTINEL_LLM_PAID_MIN_CONF  ->  local providers only (ollama)
```

This is a **second, higher threshold** and does not replace
`SENTINEL_LLM_THRESHOLD` (40), which still decides whether a hotspot gets a SITREP
at all. A hotspot at conf 55 is summarised, locally; one at 75 is summarised by
DeepSeek.

**The tier is resolved once per hotspot, in `generate_sitrep`, and the bound
callable is passed down.** Today `generate_sitrep` calls `engine(conn, hotspot_id)`
(`llm_verifier.py:99`) with no `llm` argument, so the consistency engine falls back
to its own `_default_llm` and reads the environment independently. Left that way,
a hotspot's claim extraction and its SITREP could resolve different tiers — the
same hotspot, half local and half paid. So:

1. `generate_sitrep` reads the hotspot's `conf_score` once.
2. It builds `llm = partial(call_llm, conf_score=score)`.
3. It passes that into `engine(conn, hotspot_id, llm=llm)` — `run_consistency_engine`
   already accepts the parameter (`consistency.py:476`) and threads it to
   `extract_claims`.
4. It uses the same bound callable for the SITREP and for the citation-repair
   re-prompt.

`_default_llm` remains as the unbound default for direct callers of
`run_consistency_engine` (the `python -m pipeline.consistency` CLI), resolving the
chain with `paid_allowed=False` — a manual invocation must not silently spend.

## 5. Call-site migration

`generate_sitrep` keeps its `endpoint`, `api_key`, `model` and `ollama_endpoint`
parameters. They become **overrides for the `nim` and `ollama` providers** rather
than the only configuration, so `llm_worker.py` and `api/routes/report.py` continue
to work untouched while the chain lands, and their existing tests keep passing.

`api/routes/report.py` needs one behavioural change: its 503 guard currently reads
`if not endpoint and not ollama` (`report.py:75`), which tests exactly the two
providers that exist today. It becomes a check that `resolve_chain()` is non-empty,
or the endpoint returns 503 while DeepSeek is configured and working.

## 6. Metrics

Flat names, matching `api/metrics.py`'s no-label constraint and the FR-30
translation counters:

- `llm_calls_<provider>_total` — incremented per attempt, not per success, so the
  ratio against failures is meaningful
- `llm_failures_<provider>_total`
- `llm_paid_skipped_total` — a hotspot diverted to local-only by the gate
- `llm_fallback_total` — kept, unchanged in meaning

## 7. Testing

`tests/test_llm_providers.py`, every `requests.post` mocked, no network and no key:

| Test | Asserts |
|---|---|
| chain order | providers are attempted in `SENTINEL_LLM_PROVIDERS` order |
| unconfigured skip | a provider with no key is never called, and does not count as a failure |
| empty chain | `NoProviderConfigured` raises rather than returning empty text |
| timeout fall-through | second provider is called, first is not retried |
| 5xx fall-through | retried `retries` times, *then* the next provider |
| 429 cap | falls through when the stated wait exceeds the cap |
| 401/403 | next provider called with **exactly one** call to the first |
| 400 | raises; no further provider is called |
| `model_used` | is `"provider:model"`, and the ollama case still matches the fallback check |
| paid gate | `conf_score` at or below the threshold calls only local providers |
| gate binding | claim extraction and SITREP for one hotspot receive the same bound callable |

The 401/403 and 400 tests must assert **call counts**, not just the final result.
A test that only checks the returned text cannot tell "fell through after one
attempt" from "fell through after three", which is the entire behaviour being
specified — the same trap `tests/AGENTS.md` records from PR #31.

## 8. Documentation updates

| File | Change |
|---|---|
| `specs.md` | new FR-31 in §4.13; Document Version to 1.15.0 |
| `pipeline/AGENTS.md` | provider chain bullet: table, fall-through rules, the 400-raises rule, the once-per-hotspot binding |
| `api/AGENTS.md` | `/report`'s 503 guard now tests the resolved chain |
| `CLAUDE.md` | new env vars in the Environment list |
| `sentinel.env.example` | the eight new variables, keys blank |
| `tests/AGENTS.md` | `test_llm_providers.py` in the file-naming list |

## 9. Risks

**SITREP text becomes a function of `conf_score`.** This is the accepted
consequence of the gate: two hotspots with comparable evidence can be written by
different models purely because one scored 71 and the other 69, and model quality
is not constant across that boundary. Any measurement over SITREP output — length,
citation density, reader assessment — is confounded by model unless it is
stratified by `llm_summaries.llm_model_version`, which is why §3 puts the provider
name in that column. The report's methodology section must say so.

**Pricing defaults expire.** `deepseek-chat` was retired six weeks before this was
written and DeepSeek changed its billing model eleven days before it. The defaults
carry a date for that reason; anyone reading this later should re-check both vendor
pages before trusting the table in *Model selection*.

**Backlog drain is a single large spend event.** Roughly 1000 hotspots currently
have no summary. The first run after DeepSeek is configured will attempt every one
of them above the gate, back to back. The estimate is $2–4, which is why no budget
cap is in this design — but the estimate rests on ~3k input tokens per call, and a
hotspot with 20 evidence domains will exceed that. Watch
`llm_calls_deepseek_total` on the first run rather than assuming the arithmetic.

**Both keys are new credentials in `sentinel.env`.** They join
`GOOGLE_TRANSLATE_API_KEY` as server-side secrets that must never reach a
`NEXT_PUBLIC_*` variable.
