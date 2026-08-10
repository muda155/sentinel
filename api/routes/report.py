from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from api import queries
from api.auth import get_current_user
from api.ratelimit import limit_report
from pipeline.db import get_pooled_connection
from pipeline.llm_verifier import call_llm_raw, validate_citations
from pipeline.window_report import build_window_report_prompt, report_timeout, window_citations

logger = logging.getLogger("sentinel.api.report")
router = APIRouter()

CACHE_TTL_S = 86400


def _redis():
    try:
        import redis as redis_lib
    except ImportError:
        return None
    try:
        client = redis_lib.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
        client.ping()
        return client
    except Exception:
        return None


def _cache_key(hotspot_id: int, start: str, end: str, rows: list[dict]) -> str:
    # max(event_id) invalidates the entry the moment new evidence lands in the
    # window, so an unchanged report is never regenerated and a changed one is
    # never served stale.
    high = max((r.get("event_id") or 0) for r in rows) if rows else 0
    raw = f"{hotspot_id}:{start}:{end}:{high}"
    return "sentinel:report:" + hashlib.sha256(raw.encode()).hexdigest()


@router.get("/hotspots/{hotspot_id}/report")
def hotspot_report(hotspot_id: int,
                   start: datetime = Query(alias="from"),
                   end: datetime = Query(alias="to"),
                   _rate_limit: None = Depends(limit_report),
                   _user: dict = Depends(get_current_user)):
    if end <= start:
        raise HTTPException(status_code=422, detail="'to' must be after 'from'")

    conn, pool = get_pooled_connection()
    try:
        events = queries.fetch_hotspot_events(conn, hotspot_id)
        name = queries.fetch_hotspot_name(conn, hotspot_id)
    finally:
        pool.return_connection(conn)

    if events is None:
        raise HTTPException(status_code=404, detail="hotspot not found")

    rows = [e for e in events if start <= e["event_date"] < end]
    if not rows:
        raise HTTPException(status_code=404, detail="no events in window")

    citations = window_citations(rows)
    key = _cache_key(hotspot_id, start.isoformat(), end.isoformat(), rows)
    cache = _redis()
    if cache is not None:
        try:
            hit = cache.get(key)
            if hit:
                return {**json.loads(hit), "cached": True}
        except Exception:
            logger.warning("report cache read failed", exc_info=True)

    endpoint = os.getenv("NVIDIA_NIM_ENDPOINT", "")
    ollama = os.getenv("OLLAMA_ENDPOINT", "")
    if not endpoint and not ollama:
        raise HTTPException(status_code=503, detail="report generation unavailable")

    prompt = build_window_report_prompt(name or f"Hotspot #{hotspot_id}", rows,
                                        start.isoformat(), end.isoformat())

    narrative = None
    model_used = ""
    for _ in range(2):
        try:
            content, model_used = call_llm_raw(
                prompt,
                endpoint=endpoint,
                api_key=os.getenv("NVIDIA_NIM_API_KEY", ""),
                model=os.getenv("NVIDIA_NIM_MODEL", ""),
                # One attempt, not the pipeline default of three plus an Ollama
                # fallback: this call blocks a request worker while an analyst
                # waits.
                retries=1,
                timeout=report_timeout(),
                ollama_endpoint=ollama or "http://localhost:11434",
            )
        except Exception:
            logger.warning("report LLM call failed", exc_info=True)
            raise HTTPException(status_code=503, detail="report generation unavailable")
        try:
            validate_citations(content)
            narrative = content
            break
        except ValueError:
            logger.info("report failed citation validation, retrying once")

    if narrative is None:
        # FR-11/FR-12: an uncited narrative must never ship. Failing is
        # correct; the CSV and JSON exports are unaffected.
        raise HTTPException(status_code=422, detail="report failed citation validation")

    payload = {"narrative": narrative, "citations": citations, "model": model_used}
    if cache is not None:
        try:
            cache.setex(key, CACHE_TTL_S, json.dumps(payload))
        except Exception:
            logger.warning("report cache write failed", exc_info=True)
    return {**payload, "cached": False}
