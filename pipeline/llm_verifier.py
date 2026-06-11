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
            "Summarise in 3-4 sentences. CRITICAL: You must follow the Attributed AI Briefs "
            "methodology. Every single claim in your summary must end with a citation bracket "
            "containing the index or URL of the source (e.g., 'Forces advanced 5km [1]'). "
            "Do not hallucinate."
        ),
        "Output JSON: {conflict_detected: bool, conflict_detail: str, summary: str, sources_cited: [str]}",
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


def validate_citations(summary: str) -> None:
    """Validate that every sentence ends with a numeric citation (FR-11).

    Splits the summary into sentences and requires each to match
    ``r'.+\[\d+\][.!?]\s*$'``. Raises ``ValueError`` listing every
    uncited sentence. Returns ``None`` when all sentences are cited.
    """
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', (summary or "").strip()) if s.strip()]
    if not sentences:
        raise ValueError("Summary is empty: no cited sentences found")
    pattern = re.compile(r'.+\[\d+\][.!?]\s*$')
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


def call_ollama_fallback(
    prompt: str,
    endpoint: str = "http://localhost:11434",
    timeout: int = 60,
) -> tuple[dict, str]:
    """Call local Ollama as fallback when NIM is unavailable (FR-12)."""
    payload = {
        "model": "llama3:8b",
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0,
            "num_predict": 500,
        },
    }
    try:
        response = requests.post(
            f"{endpoint}/api/generate",
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        raw = response.json()
        text = raw.get("response", "")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            # Try to extract JSON from the response
            import re as _re

            match = _re.search(r"\{.*\}", text, _re.DOTALL)
            if match:
                parsed = json.loads(match.group())
            else:
                raise ValueError(f"Ollama response is not valid JSON: {text[:200]}")
        summary = LLMSummary(**parsed)  # validates citations + types, fills defaults
        return summary.model_dump(), "llama-3-8b-ollama"
    except requests.RequestException as e:
        raise RuntimeError(f"Ollama fallback failed: {e}") from e


def call_nim_api(
    prompt: str,
    endpoint: str,
    api_key: str,
    model: str,
    retries: int = 3,
    timeout: int = 15,
    ollama_endpoint: str = "http://localhost:11434",
) -> tuple[dict, str]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 500,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            summary = LLMSummary(**parsed)  # validates citations + types, fills defaults
            return summary.model_dump(), model
        except requests.Timeout:
            logger.warning("NIM API timed out after %ds, falling back to Ollama", timeout)
            return call_ollama_fallback(prompt, ollama_endpoint)
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
                return call_ollama_fallback(prompt, ollama_endpoint)
            if status is not None and status >= 500:
                logger.warning("NIM API server error (%d), falling back to Ollama", status)
                return call_ollama_fallback(prompt, ollama_endpoint)
            raise
        except Exception as error:  # parse/validation errors
            last_error = error
            raise
    if last_error is not None:
        raise last_error
    raise RuntimeError("NIM call failed without explicit error")


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
                "SELECT hotspot_id FROM hotspots WHERE COALESCE(conf_score,0) > %s ORDER BY hotspot_id",
                (threshold,),
            )
            return [int(row[0]) for row in cursor.fetchall()]

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
    repo = LLMRepository(conn)
    hotspot_ids = repo.candidate_hotspots(threshold)
    processed = 0
    for hotspot_id in hotspot_ids:
        prompt = build_prompt(
            {"hotspot_id": hotspot_id, "articles": repo.fetch_hotspot_articles(hotspot_id)}
        )
        result, model_used = call_nim_api(
            prompt, endpoint=endpoint, api_key=api_key, model=model,
            ollama_endpoint=ollama_endpoint,
        )
        repo.save_summary(hotspot_id, result, model=model_used)
        processed += 1
    return {"candidates": len(hotspot_ids), "processed": processed}


def verify_hotspot(conn, hotspot_id: int) -> int | None:
    """Verify a single hotspot: NIM (Ollama fallback) -> save -> return summary_id.

    Thin wrapper so the LLM worker and the monolith share one code path.
    Returns the created llm_summaries.summary_id or None if NIM+Ollama fail."""
    endpoint = os.getenv("NVIDIA_NIM_ENDPOINT", "")
    api_key = os.getenv("NVIDIA_NIM_API_KEY", "")
    model = os.getenv("NVIDIA_NIM_MODEL", "meta/llama-3.1-70b-instruct")
    ollama_endpoint = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")

    repo = LLMRepository(conn)
    articles = repo.fetch_hotspot_articles(hotspot_id)
    if not articles:
        return None
    prompt = build_prompt({"hotspot_id": hotspot_id, "articles": articles})
    result, model_used = call_nim_api(
        prompt, endpoint=endpoint, api_key=api_key, model=model,
        ollama_endpoint=ollama_endpoint,
    )
    if not result or not result.get("summary"):
        return None
    repo.save_summary(hotspot_id, result, model=model_used)
    # Fetch the generated summary_id
    with conn.cursor() as cur:
        cur.execute(
            "SELECT summary_id FROM llm_summaries WHERE hotspot_id = %s",
            (hotspot_id,),
        )
        row = cur.fetchone()
    return int(row[0]) if row else None


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
    model = os.getenv("NVIDIA_NIM_MODEL", "meta/llama-3.1-70b-instruct")
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
