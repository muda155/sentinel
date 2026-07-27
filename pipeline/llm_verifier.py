from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from urllib.parse import urlparse

import requests
from pydantic import BaseModel, field_validator

from pipeline.db import get_pooled_connection

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
    ollama_endpoint: str = "http://localhost:11434",
    engine=None,
    llm_call=None,
) -> tuple[int | None, str | None]:
    """Single shared 6a+6b entry point (monolith Step 6 and LLM worker).

    6a: consistency engine (never blocks; falls back to headline prompt).
    6b: SITREP generation + save. Returns (summary_id, model_used)."""
    from pipeline.consistency import run_consistency_engine

    engine = engine or run_consistency_engine
    llm_call = llm_call or call_nim_api
    repo = LLMRepository(conn)

    engine_result = engine(conn, hotspot_id)
    if engine_result is not None and engine_result.verdicts:
        prompt = build_claims_sitrep_prompt(hotspot_id, engine_result)
    else:
        articles = repo.fetch_hotspot_articles(hotspot_id)
        if not articles:
            return None, None
        prompt = build_prompt({"hotspot_id": hotspot_id, "articles": articles})

    result, model_used = llm_call(
        prompt, endpoint=endpoint, api_key=api_key, model=model,
        ollama_endpoint=ollama_endpoint,
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


def _llm_timeout(timeout: int | None) -> int:
    if timeout is not None:
        return timeout
    return int(os.getenv("SENTINEL_LLM_TIMEOUT_S", "60"))


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

    @field_validator("summary")
    @classmethod
    def _summary_must_cite(cls, value: str) -> str:
        validate_citations(value)  # raises ValueError on uncited sentences
        return value


def call_ollama_raw(
    prompt: str,
    endpoint: str = "http://localhost:11434",
    timeout: int | None = None,
) -> tuple[str, str]:
    """Raw Ollama call: returns (response text, model tag). FR-12 fallback."""
    payload = {
        "model": "llama3:8b",
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": float(os.getenv("SENTINEL_LLM_TEMPERATURE", "0")),
            "num_predict": int(os.getenv("SENTINEL_LLM_MAX_TOKENS", "500")),
        },
    }
    try:
        response = requests.post(
            f"{endpoint}/api/generate", json=payload, timeout=_llm_timeout(timeout),
        )
        response.raise_for_status()
        return response.json().get("response", ""), "llama-3-8b-ollama"
    except requests.RequestException as e:
        raise RuntimeError(f"Ollama fallback failed: {e}") from e


def call_llm_raw(
    prompt: str,
    *,
    endpoint: str,
    api_key: str,
    model: str,
    retries: int = 3,
    timeout: int | None = None,
    ollama_endpoint: str = "http://localhost:11434",
) -> tuple[str, str]:
    """NIM chat call with 429 backoff and Ollama fallback; returns (content, model_used)."""
    timeout = _llm_timeout(timeout)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": float(os.getenv("SENTINEL_LLM_TEMPERATURE", "0")),
        "max_tokens": int(os.getenv("SENTINEL_LLM_MAX_TOKENS", "500")),
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"], model
        except requests.Timeout:
            logger.warning("NIM API timed out after %ds, falling back to Ollama", timeout)
            return call_ollama_raw(prompt, ollama_endpoint, timeout)
        except requests.HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            last_error = error
            if status == 429:
                if attempt < retries:
                    time.sleep(2**attempt)
                    continue
                logger.warning(
                    "NIM API exhausted (429) after %d retries, falling back to Ollama", retries
                )
                return call_ollama_raw(prompt, ollama_endpoint, timeout)
            if status is not None and status >= 500:
                logger.warning("NIM API server error (%d), falling back to Ollama", status)
                return call_ollama_raw(prompt, ollama_endpoint, timeout)
            raise
    if last_error is not None:
        raise last_error
    raise RuntimeError("NIM call failed without explicit error")


def call_ollama_fallback(
    prompt: str,
    endpoint: str = "http://localhost:11434",
    timeout: int | None = None,
) -> tuple[dict, str]:
    """Call local Ollama as fallback when NIM is unavailable (FR-12)."""
    text, model_used = call_ollama_raw(prompt, endpoint, timeout)
    parsed = _extract_json(text)
    summary = LLMSummary(**parsed)
    return summary.model_dump(), model_used


def call_nim_api(
    prompt: str,
    endpoint: str,
    api_key: str,
    model: str,
    retries: int = 3,
    timeout: int | None = None,
    ollama_endpoint: str = "http://localhost:11434",
) -> tuple[dict, str]:
    content, model_used = call_llm_raw(
        prompt, endpoint=endpoint, api_key=api_key, model=model,
        retries=retries, timeout=timeout, ollama_endpoint=ollama_endpoint,
    )
    parsed = _extract_json(content)
    summary = LLMSummary(**parsed)
    return summary.model_dump(), model_used


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
        return [
            {"title": row[0] or "", "url": row[1] or "", "domain": _domain(row[1])}
            for row in rows
            if row[1]
        ]

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
    ollama_endpoint: str = "http://localhost:11434",
) -> dict[str, int]:
    hotspot_ids = LLMRepository(conn).candidate_hotspots(threshold)
    processed = 0
    for hotspot_id in hotspot_ids:
        summary_id, _model_used = generate_sitrep(
            conn, hotspot_id, endpoint=endpoint, api_key=api_key, model=model,
            ollama_endpoint=ollama_endpoint,
        )
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
    endpoint = os.getenv("NVIDIA_NIM_ENDPOINT", "")
    api_key = os.getenv("NVIDIA_NIM_API_KEY", "")
    model = os.getenv("NVIDIA_NIM_MODEL", "meta/llama-3.3-70b-instruct")
    ollama_endpoint = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")
    if not endpoint or not api_key:
        raise RuntimeError("NVIDIA_NIM_ENDPOINT and NVIDIA_NIM_API_KEY are required")
    conn, pool = get_pooled_connection()
    try:
        result = verify_hotspots_with_llm(
            conn, endpoint=endpoint, api_key=api_key, model=model,
            threshold=args.threshold, ollama_endpoint=ollama_endpoint,
        )
    finally:
        pool.return_connection(conn)
    print(f"LLM verified hotspots: {result['processed']} / {result['candidates']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
