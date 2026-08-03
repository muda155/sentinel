"""GDELT emits one events row per extracted actor pair, so one article URL
becomes several rows. Collapsing them is what keeps the citation list from
reading as independent corroboration."""
from pipeline.citations import collapse_duplicate_urls


def test_keeps_first_row_per_url_in_input_order():
    rows = [
        {"event_id": 1, "url": "https://a.example/x"},
        {"event_id": 2, "url": "https://b.example/y"},
        {"event_id": 3, "url": "https://a.example/x"},
    ]
    out = collapse_duplicate_urls(rows)
    assert [r["event_id"] for r in out] == [1, 2]


def test_tags_how_many_rows_collapsed_into_each_kept_row():
    rows = [
        {"event_id": 1, "url": "https://a.example/x"},
        {"event_id": 2, "url": "https://a.example/x"},
        {"event_id": 3, "url": "https://a.example/x"},
        {"event_id": 4, "url": "https://b.example/y"},
    ]
    out = collapse_duplicate_urls(rows)
    assert [(r["event_id"], r["duplicate_count"]) for r in out] == [(1, 3), (4, 1)]


def test_rows_without_a_url_are_never_collapsed_together():
    """A missing url is not an identity — those rows carry no citation index
    and each still represents a distinct event."""
    rows = [
        {"event_id": 1, "url": None},
        {"event_id": 2, "url": ""},
        {"event_id": 3, "url": "   "},
    ]
    out = collapse_duplicate_urls(rows)
    assert [r["event_id"] for r in out] == [1, 2, 3]
    assert all(r["duplicate_count"] == 1 for r in out)


def test_count_key_none_leaves_rows_untagged():
    """The SITREP prompt serializes these dicts verbatim; an extra key would
    become prompt noise."""
    rows = [{"url": "https://a.example/x"}, {"url": "https://a.example/x"}]
    out = collapse_duplicate_urls(rows, count_key=None)
    assert out == [{"url": "https://a.example/x"}]


def test_url_key_is_configurable():
    rows = [{"link": "https://a.example/x"}, {"link": "https://a.example/x"}]
    assert len(collapse_duplicate_urls(rows, url_key="link")) == 1
