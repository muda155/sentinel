"""FR-29: window-scoped narrative report.

The prompt is built from ONLY the window's events, and states the bounds, so
the model cannot narrate activity from outside the range the analyst asked
about. Output must satisfy validate_citations() like every other SITREP."""
from __future__ import annotations

import os

from pipeline.citations import collapse_duplicate_urls

MAX_EVIDENCE = 30


def window_citations(events: list[dict]) -> list[dict]:
    """Renumber citations [1..N] within the window.

    fetch_hotspot_events numbers over the hotspot's ENTIRE event set, so a
    filtered slice inherits gaps ([4], [7], ...) that reference rows the
    report does not contain. An exported report has to be self-contained."""
    rows = collapse_duplicate_urls(list(events))
    return [
        {"index": i, "event_id": r.get("event_id"), "title": r.get("title"),
         "url": r.get("url"), "domain": r.get("domain", "")}
        for i, r in enumerate(rows[:MAX_EVIDENCE], start=1)
    ]


def build_window_report_prompt(name: str | None, events: list[dict],
                               start: str, end: str) -> str:
    citations = window_citations(events)
    lines = [
        "Act as an intelligence analyst writing a situation report.",
    ]
    # An unnamed hotspot gets no Location line at all. The caller used to
    # synthesise "Hotspot #12750", which stated an internal id as the place
    # the report is about — the same leak that put "A court in Hotspot ID
    # 12750" into a live SITREP (2026-08-27).
    if name:
        lines.append(f"Location: {name}.")
    lines += [
        f"Reporting window: {start} to {end}. Describe ONLY what the evidence "
        "below reports within that window.",
        "",
        "Write 3 to 6 sentences of plain narrative prose. Every sentence MUST end "
        "with a citation index in square brackets, for example [1]. Do not invent "
        "facts, numbers or place names that are absent from the evidence. Do not "
        "use bullet points, headings or emoji.",
        "",
        "Evidence:",
    ]
    for c in citations:
        lines.append(f"[{c['index']}] {c['title'] or c['domain']}")
    return "\n".join(lines)


def report_timeout() -> int:
    return int(os.getenv("SENTINEL_REPORT_TIMEOUT_S", "30"))
