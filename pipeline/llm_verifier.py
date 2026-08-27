from __future__ import annotations

import argparse
import json
import logging
import os
import re
import threading
from urllib.parse import urlparse

from pydantic import BaseModel, ValidationError, field_validator

from pipeline.citations import collapse_duplicate_urls
from pipeline.db import get_pooled_connection
from pipeline.llm_providers import (  # noqa: F401 — transport moved here (FR-31); re-exported
    _llm_timeout,
    _ratelimit_backoff,
    _ratelimit_max_wait,
    _retry_after_seconds,
    call_llm,
    call_ollama_raw,
)

logger = logging.getLogger("sentinel.llm_verifier")


def build_prompt(hotspot_data: dict) -> str:
    lines = [
        "Act as an intelligence analyst. Detect any factual conflicts.",
        (
            "Summarise in 3-4 sentences. CRITICAL: follow the Attributed AI Briefs "
            "methodology. Every sentence MUST end with exactly ONE citation of the form "
            "[N], where N is a single source index number, placed immediately before the "
            "terminal period (e.g., 'Forces advanced 5km [1].'). Never put multiple numbers "
            "in one bracket (no '[1, 2]') and never put a URL in the bracket; if several "
            "sources support a claim, cite only the single most relevant index. Do not hallucinate."
        ),
        "Output JSON only, no prose outside it: "
        "{conflict_detected: bool, conflict_detail: str, summary: str, sources_cited: [str]}",
        "",
        f"Hotspot ID: {hotspot_data.get('hotspot_id')}",
        "Sources:",
    ]
    for idx, article in enumerate(hotspot_data.get("articles", []), start=1):
        lines.append(
            f"[{idx}] title={article.get('title','')} url={article.get('url','')} "
            f"domain={article.get('domain','')}"
        )
    return "\n".join(lines)


def build_claims_sitrep_prompt(hotspot_id: int, result) -> str:
    """FR-23: SITREP prompt over the verified claim set (EngineResult)."""
    lines = [
        "Act as an intelligence analyst writing a SITREP from VERIFIED claims only.",
        (
            "Summarise in 3-4 sentences. Rules: every sentence MUST end with exactly one "
            "citation [N] before the terminal period, where N is a source index below. "
            "Claims marked SINGLE-SOURCE must be attributed as single-source reports. "
            "For each claim marked DISPUTED, write one sentence of the form "
            "'Sources disagree on <topic> [i][j].' using the two indices given for it. "
            "Do not include any claim not listed below. Do not hallucinate."
        ),
        "Output JSON only, no prose outside it: "
        "{conflict_detected: bool, conflict_detail: str, summary: str, sources_cited: [str]}",
        "Set conflict_detected=true if any claim below is DISPUTED.",
        "",
        f"Hotspot ID: {hotspot_id}",
        "Verified claims:",
    ]
    status_names = {"corroborated": "CORROBORATED", "uncorroborated": "SINGLE-SOURCE",
                    "disputed": "DISPUTED"}
    for verdict in result.verdicts:
        supporters = [j.citation_index for j in verdict.evidence
                      if j.relation == "supports"]
        contradictors = [j.citation_index for j in verdict.evidence
                         if j.relation == "contradicts"]
        line = f"- [{status_names[verdict.status]}] {verdict.text} sources={supporters}"
        if verdict.status == "disputed" and supporters and contradictors:
            line += f" dispute_pair=[{supporters[0]}][{contradictors[0]}]"
        lines.append(line)
    return "\n".join(lines)


def generate_sitrep(
    conn,
    hotspot_id: int,
    *,
    endpoint: str,
    api_key: str,
    model: str,
    ollama_endpoint: str | None = None,
    engine=None,
    llm_call=None,
) -> tuple[int | None, str | None]:
    """Single shared 6a+6b entry point (monolith Step 6 and LLM worker).

    6a: consistency engine (never blocks; falls back to headline prompt).
    6b: SITREP generation + save. Returns (summary_id, model_used)."""
    from functools import partial

    from pipeline.consistency import run_consistency_engine

    engine = engine or run_consistency_engine
    llm_call = llm_call or call_nim_api
    repo = LLMRepository(conn)

    conf_score = repo.fetch_conf_score(hotspot_id)
    if conf_score is None:
        # NULL means "never scored": spending a paid provider on an unscored
        # hotspot is not the gate's intent. The only legitimate "unscoped"
        # conf_score=None caller is /report, which never reaches this path.
        conf_score = 0.0
    # One tier for the whole hotspot. Resolving it separately in the engine and
    # again for the SITREP would let a single hotspot be written half locally
    # and half by a paid provider, which makes llm_model_version a lie.
    bound_llm = partial(call_llm, conf_score=conf_score)

    engine_result = engine(conn, hotspot_id, llm=bound_llm)
    if engine_result is not None and engine_result.verdicts:
        prompt = build_claims_sitrep_prompt(hotspot_id, engine_result)
    else:
        articles = repo.fetch_hotspot_articles(hotspot_id)
        if not articles:
            return None, None
        prompt = build_prompt({"hotspot_id": hotspot_id, "articles": articles})

    result, model_used = llm_call(
        prompt, endpoint=endpoint, api_key=api_key, model=model,
        ollama_endpoint=ollama_endpoint, conf_score=conf_score,
    )
    if not result or not result.get("summary"):
        return None, model_used
    repo.save_summary(hotspot_id, result, model=model_used)
    with conn.cursor() as cur:
        cur.execute("SELECT summary_id FROM llm_summaries WHERE hotspot_id = %s",
                    (hotspot_id,))
        row = cur.fetchone()
    return (int(row[0]) if row else None), model_used


def _extract_json(text: str) -> dict:
    """Parse a JSON object from an LLM response, tolerating markdown fences/prose.

    Models (NIM Llama-3.1-70B included) frequently wrap the object in ```json
    fences or prefix prose like ``**Output JSON:**``. Falls back to the first
    ``{...}`` span when a direct parse fails.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"LLM response is not valid JSON: {text[:200]}") from None


def validate_citations(summary: str) -> None:
    r"""Validate that every sentence ends with a numeric citation (FR-11).

    Splits the summary into sentences and requires each to match
    the citation pattern. FR-23 dispute sentences may end with exactly
    two indices ``[i][j]``; three or more stay invalid.
    """
    # Abbreviations ("U.S.", "St.", "Gen.") must not split mid-sentence: legit
    # boundaries always look like "[N]." per FR-11, never end in an abbreviation.
    abbrevs = ["St", "Mt", "Dr", "Mr", "Mrs", "Ms", "Gen", "Lt", "Col", "Sgt", "Jr", "Sr"]
    guards = r'(?<![A-Z]\.)' + "".join(rf'(?<!\b{a}\.)' for a in abbrevs)
    sentences = [
        s.strip()
        for s in re.split(guards + r'(?<=[.!?])\s+', (summary or "").strip())
        if s.strip()
    ]
    if not sentences:
        raise ValueError("Summary is empty: no cited sentences found")
    # FR-11 single index, or FR-23 dispute sentences ending with exactly two
    # indices [i][j] (supporter, contradictor). Three or more stay invalid.
    pattern = re.compile(r'.+?(?<!\])\[\d+\](\[\d+\])?[.!?]\s*$')
    uncited = [s for s in sentences if not pattern.search(s)]
    if uncited:
        raise ValueError("Uncited sentences: " + " | ".join(uncited))


class LLMSummary(BaseModel):
    """Validated LLM SITREP response (FR-11). Runs citation validation."""

    conflict_detected: bool
    conflict_detail: str = ""
    summary: str
    sources_cited: list[str] = []

    @field_validator("sources_cited", mode="before")
    @classmethod
    def _coerce_sources(cls, value: object) -> object:
        # The LLM may emit numeric citation ids; the spec contract is list[str].
        if isinstance(value, list):
            return [str(item) for item in value]
        return value

    @field_validator("summary", "conflict_detail", mode="before")
    @classmethod
    def _coerce_text(cls, value: object) -> object:
        # The model intermittently returns these as a JSON list of sentences
        # rather than a string. sources_cited already had a coercion and these
        # did not, so a formatting quirk discarded the whole hotspot.
        if isinstance(value, list):
            return " ".join(str(item).strip() for item in value if str(item).strip())
        return value

    @field_validator("summary")
    @classmethod
    def _summary_must_cite(cls, value: str) -> str:
        validate_citations(value)  # raises ValueError on uncited sentences
        return value


# The shim applies its arguments by mutating os.environ for the duration of
# the call. The /report handler runs under a threadpool, so the mutation must
# be serialized or two concurrent reports could read each other's overrides.
_ENV_OVERRIDE_LOCK = threading.Lock()


def call_llm_raw(
    prompt: str,
    *,
    endpoint: str,
    api_key: str,
    model: str,
    retries: int = 3,
    timeout: int | None = None,
    ollama_endpoint: str | None = None,
    conf_score: float | None = None,
) -> tuple[str, str]:
    """Back-compat shim over the FR-31 provider chain.

    The endpoint/api_key/model arguments predate the chain and named NIM
    specifically; they are now applied as environment overrides for the `nim`
    and `ollama` providers so existing callers keep working unchanged.
    ollama_endpoint None leaves a configured OLLAMA_ENDPOINT alone; the old
    truthy localhost default used to clobber it whenever a caller omitted the
    argument."""
    overrides = {}
    if endpoint:
        overrides["NVIDIA_NIM_ENDPOINT"] = endpoint
    if api_key:
        overrides["NVIDIA_NIM_API_KEY"] = api_key
    if model:
        overrides["NVIDIA_NIM_MODEL"] = model
    if ollama_endpoint:
        overrides["OLLAMA_ENDPOINT"] = ollama_endpoint
    previous = {k: os.environ.get(k) for k in overrides}
    with _ENV_OVERRIDE_LOCK:
        os.environ.update(overrides)
        try:
            return call_llm(prompt, conf_score=conf_score, retries=retries, timeout=timeout)
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def call_ollama_fallback(
    prompt: str,
    endpoint: str = "http://localhost:11434",
    timeout: int | None = None,
) -> tuple[dict, str]:
    """Call local Ollama as fallback when NIM is unavailable (FR-12)."""
    text, model_used = call_ollama_raw(prompt, endpoint, timeout)
    return _parse_summary(text), model_used


def _parse_summary(content: str) -> dict:
    return LLMSummary(**_extract_json(content)).model_dump()


def _citation_repair_enabled() -> bool:
    return os.getenv("SENTINEL_LLM_CITATION_REPAIR", "true").strip().lower() not in {
        "false", "0", "no",
    }


def build_repair_prompt(original_prompt: str, bad_output: str, error: str) -> str:
    """Re-prompt carrying the original task plus what the last answer got wrong.

    The rejected call is already paid for, so one repair costs far less than
    discarding the hotspot — which is what every FR-11 violation did before.
    """
    return "\n".join([
        original_prompt,
        "",
        "Your previous answer was REJECTED because it broke the citation rule:",
        error,
        "",
        "Previous answer:",
        bad_output,
        "",
        "Return the SAME JSON object, correcting only the citations: every "
        'sentence in "summary" must end with exactly one marker like [1] '
        "immediately before its full stop. Do not add or change any facts.",
    ])


def call_nim_api(
    prompt: str,
    endpoint: str,
    api_key: str,
    model: str,
    retries: int = 3,
    timeout: int | None = None,
    ollama_endpoint: str | None = None,
    conf_score: float | None = None,
) -> tuple[dict, str]:
    content, model_used = call_llm_raw(
        prompt, endpoint=endpoint, api_key=api_key, model=model,
        retries=retries, timeout=timeout, ollama_endpoint=ollama_endpoint,
        conf_score=conf_score,
    )
    try:
        return _parse_summary(content), model_used
    except ValidationError as error:
        if not _citation_repair_enabled():
            raise
        logger.info("SITREP rejected on citations, re-prompting once to repair")
        # Exactly one repair: a model that cannot cite must not be retried
        # forever, and a second failure is the honest answer.
        content, model_used = call_llm_raw(
            build_repair_prompt(prompt, content, str(error)),
            endpoint=endpoint, api_key=api_key, model=model,
            retries=retries, timeout=timeout, ollama_endpoint=ollama_endpoint,
            conf_score=conf_score,
        )
        return _parse_summary(content), model_used


class LLMRepository:
    def __init__(self, conn) -> None:
        self._conn = conn

    def fetch_hotspot_articles(self, hotspot_id: int) -> list[dict]:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT e.title, e.url
                FROM event_hotspot eh
                JOIN events e ON e.event_id = eh.event_id
                WHERE eh.hotspot_id = %s
                  AND NOT COALESCE(eh.is_noise, false)
                ORDER BY e.event_date DESC, e.event_id DESC
                """,
                (hotspot_id,),
            )
            rows = cursor.fetchall()
        articles = [
            {"title": row[0] or "", "url": row[1] or "", "domain": _domain(row[1])}
            for row in rows
            if row[1]
        ]
        # count_key=None: these dicts are serialized into the prompt verbatim.
        return collapse_duplicate_urls(articles, count_key=None)

    def candidate_hotspots(self, threshold: float) -> list[int]:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT h.hotspot_id FROM hotspots h
                WHERE COALESCE(h.conf_score,0) > %s
                  AND NOT EXISTS (
                    SELECT 1 FROM llm_summaries ls WHERE ls.hotspot_id = h.hotspot_id
                  )
                ORDER BY h.hotspot_id
                """,
                (threshold,),
            )
            return [int(row[0]) for row in cursor.fetchall()]

    def summary_exists(self, hotspot_id: int) -> bool:
        with self._conn.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM llm_summaries WHERE hotspot_id = %s", (hotspot_id,)
            )
            return cursor.fetchone() is not None

    def fetch_conf_score(self, hotspot_id: int) -> float | None:
        with self._conn.cursor() as cursor:
            cursor.execute(
                "SELECT conf_score FROM hotspots WHERE hotspot_id = %s", (hotspot_id,)
            )
            row = cursor.fetchone()
        return float(row[0]) if row and row[0] is not None else None

    def save_summary(self, hotspot_id: int, result: dict, model: str) -> None:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO llm_summaries (
                    hotspot_id, summary_text, conflict_detected, conflict_detail, sources_cited, llm_model_version
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (hotspot_id) DO UPDATE
                SET summary_text = EXCLUDED.summary_text,
                    conflict_detected = EXCLUDED.conflict_detected,
                    conflict_detail = EXCLUDED.conflict_detail,
                    sources_cited = EXCLUDED.sources_cited,
                    llm_model_version = EXCLUDED.llm_model_version
                """,
                (
                    hotspot_id,
                    result.get("summary", ""),
                    bool(result.get("conflict_detected", False)),
                    result.get("conflict_detail", ""),
                    json.dumps(result.get("sources_cited", [])),
                    model,
                ),
            )
            cursor.execute(
                "UPDATE hotspots SET llm_verified = true WHERE hotspot_id = %s",
                (hotspot_id,),
            )
        self._conn.commit()


def verify_hotspots_with_llm(
    conn,
    endpoint: str,
    api_key: str,
    model: str,
    threshold: float = 40,
    ollama_endpoint: str | None = None,
) -> dict[str, int]:
    hotspot_ids = LLMRepository(conn).candidate_hotspots(threshold)
    processed = 0
    for hotspot_id in hotspot_ids:
        try:
            summary_id, _model_used = generate_sitrep(
                conn, hotspot_id, endpoint=endpoint, api_key=api_key, model=model,
                ollama_endpoint=ollama_endpoint,
            )
        except Exception as error:
            # One bad hotspot (every provider failing on it, a malformed
            # answer) must not end the run for all the rest — the LLM worker
            # isolates per hotspot already; the monolith/CLI must too.
            logger.warning("hotspot %s failed LLM verification: %s", hotspot_id, error)
            continue
        if summary_id is not None:
            processed += 1
    return {"candidates": len(hotspot_ids), "processed": processed}


def verify_hotspot(conn, hotspot_id: int) -> int | None:
    """Verify a single hotspot via the shared generate_sitrep path."""
    endpoint = os.getenv("NVIDIA_NIM_ENDPOINT", "")
    api_key = os.getenv("NVIDIA_NIM_API_KEY", "")
    model = os.getenv("NVIDIA_NIM_MODEL", "meta/llama-3.3-70b-instruct")
    ollama_endpoint = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")
    summary_id, _model_used = generate_sitrep(
        conn, hotspot_id, endpoint=endpoint, api_key=api_key, model=model,
        ollama_endpoint=ollama_endpoint,
    )
    return summary_id


def _domain(url: str | None) -> str:
    if not url:
        return ""
    return urlparse(url).netloc.lower()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify scored hotspots with NVIDIA NIM")
    parser.add_argument("--threshold", type=float, default=40)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    from pipeline.llm_providers import NoProviderConfigured, resolve_chain
    try:
        resolve_chain()
    except NoProviderConfigured as error:
        raise RuntimeError(
            "no LLM provider configured; check SENTINEL_LLM_PROVIDERS"
        ) from error
    conn, pool = get_pooled_connection()
    try:
        result = verify_hotspots_with_llm(
            conn,
            endpoint=os.getenv("NVIDIA_NIM_ENDPOINT", ""),
            api_key=os.getenv("NVIDIA_NIM_API_KEY", ""),
            model=os.getenv("NVIDIA_NIM_MODEL", "meta/llama-3.3-70b-instruct"),
            threshold=args.threshold,
            ollama_endpoint=os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434"),
        )
    finally:
        pool.return_connection(conn)
    print(f"LLM verified hotspots: {result['processed']} / {result['candidates']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
