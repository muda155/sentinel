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

_MARKER = re.compile(r"\[\d+\]")
_WRAPPED = re.compile(r'<span[^>]*>\s*(\[\d+\])\s*</span>')
_ANY_SPAN = re.compile(r"</?span[^>]*>")


def protect_citations(text: str) -> str:
    return _MARKER.sub(lambda m: f'<span translate="no">{m.group(0)}</span>', text or "")


def restore_citations(text: str) -> str:
    # Unwrap by pattern rather than by exact string: the attribute order and
    # spacing Google returns is not guaranteed to match what we sent.
    out = _WRAPPED.sub(r"\1", text or "")
    out = _ANY_SPAN.sub("", out)
    return html.unescape(out)


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
