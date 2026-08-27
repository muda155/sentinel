"""FR-30: Vietnamese display translation via Google Cloud Translation v2.

English stays canonical everywhere in the system; this module only produces
text for display. Citation markers are wrapped in <span translate="no"> before
the call because Google honours that tag ONLY when format=html - in text mode
there is no way to exclude a segment, and a translated [N] breaks both the
FR-11 validator and the detail panel's click-to-jump."""
from __future__ import annotations

import html
import os
import re

import requests

_MARKER = re.compile(r"\[\d+\]")
_WRAPPED = re.compile(r'<span[^>]*>\s*(\[\d+\])\s*</span>')
_ANY_SPAN = re.compile(r"</?span[^>]*>")
# Google treats the wrapper as a word and returns "Dabholkar [1] ." for a
# sentence that went out as "Dabholkar [1]." - close the gap it opened.
_MARKER_GAP = re.compile(r"(\[\d+\])\s+([.,;:!?)\]])")


def protect_citations(text: str) -> str:
    return _MARKER.sub(lambda m: f'<span translate="no">{m.group(0)}</span>', text or "")


def restore_citations(text: str) -> str:
    # Unwrap by pattern rather than by exact string: the attribute order and
    # spacing Google returns is not guaranteed to match what we sent.
    out = _WRAPPED.sub(r"\1", text or "")
    out = _ANY_SPAN.sub("", out)
    # after unescape, so an &nbsp; Google inserted counts as the gap it is
    return _MARKER_GAP.sub(r"\1\2", html.unescape(out))


def citation_markers(text: str) -> list[str]:
    return _MARKER.findall(text or "")


def _flag(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def translate_enabled() -> bool:
    return _flag("SENTINEL_TRANSLATE_ENABLED") and bool(
        os.getenv("GOOGLE_TRANSLATE_API_KEY", "").strip()
    )


def translate_timeout() -> int:
    return int(os.getenv("SENTINEL_TRANSLATE_TIMEOUT_S", "10"))


def translate_max_chars() -> int:
    return int(os.getenv("SENTINEL_TRANSLATE_MAX_CHARS", "5000"))


def translate_ttl() -> int:
    return int(os.getenv("SENTINEL_TRANSLATE_TTL_S", "86400"))


GOOGLE_ENDPOINT = "https://translation.googleapis.com/language/translate/v2"


class TranslationUnavailable(RuntimeError):
    """Google Translate could not be reached or answered unusably."""


def translate_batch(strings: list[str], *, api_key: str, target: str = "vi",
                    source: str = "en", timeout: int | None = None) -> list[str]:
    """Translate strings in one call, preserving input order.

    Raises TranslationUnavailable rather than returning partial output: a short
    or reordered response would misalign claims against their claim_ids."""
    if not strings:
        return []
    response = requests.post(
        GOOGLE_ENDPOINT,
        params={"key": api_key},
        json={"q": list(strings), "source": source, "target": target, "format": "html"},
        timeout=timeout or translate_timeout(),
    )
    if response.status_code != 200:
        raise TranslationUnavailable(f"google translate returned {response.status_code}")
    try:
        items = response.json()["data"]["translations"]
    except (ValueError, KeyError, TypeError) as exc:
        raise TranslationUnavailable(f"unparseable translate response: {exc}") from exc
    if len(items) != len(strings):
        raise TranslationUnavailable(
            f"expected {len(strings)} translations, got {len(items)}"
        )
    return [item.get("translatedText", "") for item in items]
