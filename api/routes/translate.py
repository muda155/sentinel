"""FR-30: Vietnamese display translation of the SITREP and claims.

English is canonical - this endpoint writes nothing and no scoring path reads
its output. It is the only externally-billed call in the API, which is what
drives the separate rate-limit bucket, the character cap and the cache."""
from __future__ import annotations

import hashlib
import html
import logging
import os

import requests
from fastapi import APIRouter, Depends, HTTPException, Query

from api import queries
from api.auth import get_current_user
from api.cache import cache_get_json, cache_setex_json
from api.metrics import METRICS
from api.ratelimit import limit_translate
from api.schemas import Translation
from pipeline.db import get_pooled_connection
from pipeline.translate import (
    TranslationUnavailable,
    citation_markers,
    protect_citations,
    restore_citations,
    translate_batch,
    translate_enabled,
    translate_max_chars,
    translate_timeout,
    translate_ttl,
)

logger = logging.getLogger("sentinel.api.translate")
router = APIRouter()

SUPPORTED_LANGS = {"vi"}


def _cache_key(lang: str, hotspot_id: int, summary: str, claims: list[dict]) -> str:
    # Keyed on CONTENT, not ids: the pipeline rewrites claims every tick, so an
    # id-keyed entry would serve the previous run's text under new claims.
    body = "\x1f".join(
        [lang, str(hotspot_id), summary]
        + [f"{c['claim_id']}:{c['claim_text']}" for c in claims]
    )
    return "sentinel:translation:" + hashlib.sha256(body.encode()).hexdigest()


def _within_budget(summary: str, claims: list[dict]) -> tuple[bool, list[dict]]:
    """Which strings fit under the per-request character cap, in order.

    The summary is part of the metered total, so one that alone exceeds the cap
    is skipped and returned untranslated rather than shipping an over-budget
    request."""
    budget = translate_max_chars()
    summary_fits = len(summary) <= budget
    if summary_fits:
        budget -= len(summary)
    kept = []
    for claim in claims:
        text = claim["claim_text"]
        if len(text) > budget:
            continue
        budget -= len(text)
        kept.append(claim)
    return summary_fits, kept


@router.get("/hotspots/{hotspot_id}/translation", response_model=Translation)
def hotspot_translation(hotspot_id: int, lang: str = Query("vi"),
                        _rate_limit: None = Depends(limit_translate),
                        _user: dict = Depends(get_current_user)):
    # Count every request that reaches the handler (auth and rate limiting
    # already ran as dependencies), so the errors/requests ratio covers the
    # 4xx/5xx responses below rather than understating the failure rate.
    METRICS.inc("translation_requests_total")

    if lang not in SUPPORTED_LANGS:
        METRICS.inc("translation_errors_total")
        raise HTTPException(status_code=422, detail=f"unsupported language: {lang}")

    conn, pool = get_pooled_connection()
    try:
        summary_row = queries.fetch_hotspot_summary(conn, hotspot_id)
        claims_row = queries.fetch_hotspot_claims(conn, hotspot_id)
    finally:
        pool.return_connection(conn)

    # fetch_hotspot_summary COALESCEs a missing llm_summaries row to '', so None
    # means the hotspot itself does not exist.
    if summary_row is None:
        METRICS.inc("translation_errors_total")
        raise HTTPException(status_code=404, detail="hotspot not found")

    summary = summary_row.get("summary") or ""
    claims = list((claims_row or {}).get("claims") or [])

    if not summary and not claims:
        return {"lang": lang, "summary": "", "summary_translated": True,
                "claims": [], "cached": False}

    key = _cache_key(lang, hotspot_id, summary, claims)
    hit = cache_get_json(key)
    if hit:
        METRICS.inc("translation_cache_hits_total")
        return {**hit, "cached": True}

    if not translate_enabled():
        METRICS.inc("translation_errors_total")
        raise HTTPException(status_code=503, detail="translation unavailable")

    summary_fits, translatable = _within_budget(summary, claims)
    send_summary = bool(summary) and summary_fits
    # format=html parses markup, so raw text with < or & would be dropped as
    # tags/entities; escaping makes it literal and restore_citations unescapes.
    payload_strings = ([protect_citations(html.escape(summary))] if send_summary else []) + \
        [html.escape(c["claim_text"]) for c in translatable]

    try:
        raw = translate_batch(
            payload_strings,
            api_key=os.getenv("GOOGLE_TRANSLATE_API_KEY", ""),
            target=lang,
            timeout=translate_timeout(),
        )
    except (TranslationUnavailable, requests.RequestException) as exc:
        METRICS.inc("translation_errors_total")
        logger.warning("translation failed for hotspot %s: %s", hotspot_id, exc)
        raise HTTPException(status_code=503, detail="translation unavailable") from exc

    # An empty summary is vacuously translated - nothing failed, so the client
    # must not read summary_translated=false as a translation failure.
    translated_summary, summary_ok = summary, not bool(summary)
    if send_summary:
        candidate = restore_citations(raw[0])
        # The markers drive FR-16 click-to-jump and FR-11 validation. If Google
        # dropped or duplicated one, the English text is the safer answer.
        if citation_markers(candidate) == citation_markers(summary):
            translated_summary, summary_ok = candidate, True
        else:
            logger.warning("hotspot %s: citation markers changed, keeping English",
                           hotspot_id)

    by_id = {c["claim_id"]: restore_citations(text)
             for c, text in zip(translatable, raw[1:] if send_summary else raw)}
    out_claims = [{"claim_id": c["claim_id"],
                   "text": by_id.get(c["claim_id"], c["claim_text"])}
                  for c in claims]

    payload = {"lang": lang, "summary": translated_summary,
               "summary_translated": summary_ok, "claims": out_claims}
    cache_setex_json(key, translate_ttl(), payload)
    return {**payload, "cached": False}
