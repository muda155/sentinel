"""One article = one citation (FR-16).

GDELT emits one ``events`` row per extracted actor pair, so a single article
URL becomes several rows. Left uncollapsed, one report is cited under several
numbers and reads as independent corroboration."""
from __future__ import annotations


def collapse_duplicate_urls(
    rows: list[dict],
    *,
    url_key: str = "url",
    count_key: str | None = "duplicate_count",
) -> list[dict]:
    """Keep the first row per URL, in input order.

    LOCKSTEP CONTRACT: every producer of the FR-16 citation list —
    ``api.queries.fetch_hotspot_events``,
    ``pipeline.llm_verifier.LLMRepository.fetch_hotspot_articles`` and
    ``pipeline.consistency.fetch_hotspot_evidence`` — must apply this to the
    same ordering. If one collapses and another does not, every ``[N]`` above
    the first duplicate shifts and SITREP markers point at the wrong article.

    Rows whose URL is missing or blank are never collapsed together: a missing
    URL is not an identity, and those rows carry no citation index anyway.

    MUTATION: when ``count_key`` is set, the input row dicts are modified in
    place (``row[count_key] = 1``), and the kept first row's ``count_key`` is
    incremented as duplicates fold into it. Callers must pass freshly
    materialised rows, not dicts that are reused or shared elsewhere.
    """
    kept: list[dict] = []
    first_by_url: dict[str, dict] = {}
    for row in rows:
        if count_key is not None:
            row[count_key] = 1
        url = (row.get(url_key) or "").strip()
        if not url:
            kept.append(row)
            continue
        seen = first_by_url.get(url)
        if seen is None:
            first_by_url[url] = row
            kept.append(row)
        elif count_key is not None:
            seen[count_key] += 1
    return kept
