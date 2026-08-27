"""FR-30: citation-safe helpers for Google Translate (no network)."""
import pytest

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


def test_protect_wraps_every_marker():
    out = protect_citations("Forces advanced [1]. Shelling continued [2].")
    assert out.count('<span translate="no">') == 2
    assert '<span translate="no">[1]</span>' in out


def test_protect_wraps_both_indices_of_a_dispute_pair():
    # FR-23 dispute sentences end with two adjacent indices.
    out = protect_citations("Sources disagree on casualties [1][2].")
    assert '<span translate="no">[1]</span><span translate="no">[2]</span>' in out


def test_restore_is_the_inverse_of_protect():
    original = "Forces advanced [1]. Sources disagree on casualties [2][3]."
    assert restore_citations(protect_citations(original)) == original


def test_restore_unescapes_html_entities():
    # format=html makes Google return entity-encoded punctuation.
    assert restore_citations("Qu&#226;n &amp; d&#226;n") == "Quân & dân"


def test_restore_tolerates_reordered_span_attributes():
    # Never assume the exact attribute string survives the round trip.
    assert restore_citations('Lực lượng <span class="notranslate" translate="no">[1]</span>.') \
        == "Lực lượng [1]."


def test_citation_markers_is_a_multiset_not_a_set():
    # [1] appearing twice must not collapse, or the guard would accept a
    # translation that silently dropped one of them.
    assert citation_markers("A [1]. B [1]. C [2].") == ["[1]", "[1]", "[2]"]


def test_translate_enabled_requires_both_the_flag_and_a_key(monkeypatch):
    monkeypatch.setenv("SENTINEL_TRANSLATE_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_TRANSLATE_API_KEY", "k")
    assert translate_enabled() is True
    monkeypatch.delenv("GOOGLE_TRANSLATE_API_KEY")
    assert translate_enabled() is False
    monkeypatch.setenv("GOOGLE_TRANSLATE_API_KEY", "k")
    monkeypatch.setenv("SENTINEL_TRANSLATE_ENABLED", "false")
    assert translate_enabled() is False


def test_config_defaults(monkeypatch):
    for var in ("SENTINEL_TRANSLATE_TIMEOUT_S", "SENTINEL_TRANSLATE_MAX_CHARS",
                "SENTINEL_TRANSLATE_TTL_S"):
        monkeypatch.delenv(var, raising=False)
    assert translate_timeout() == 10
    assert translate_max_chars() == 5000
    assert translate_ttl() == 86400


def test_translate_batch_posts_html_format_and_returns_in_order(monkeypatch):
    captured = {}

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"data": {"translations": [
                {"translatedText": "Mot"}, {"translatedText": "Hai"},
            ]}}

    def _fake_post(url, params=None, json=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["json"] = json
        return _Resp()

    monkeypatch.setattr("pipeline.translate.requests.post", _fake_post)
    out = translate_batch(["One", "Two"], api_key="k")
    assert out == ["Mot", "Hai"]
    assert captured["json"]["format"] == "html"
    assert captured["json"]["target"] == "vi"
    assert captured["json"]["q"] == ["One", "Two"]
    assert captured["params"] == {"key": "k"}


def test_translate_batch_short_circuits_on_empty_input(monkeypatch):
    def _explode(*a, **k):
        raise AssertionError("must not call Google for an empty batch")

    monkeypatch.setattr("pipeline.translate.requests.post", _explode)
    assert translate_batch([], api_key="k") == []


def test_translate_batch_raises_on_a_non_200(monkeypatch):
    class _Resp:
        status_code = 403

        @staticmethod
        def json():
            return {}

    monkeypatch.setattr("pipeline.translate.requests.post",
                        lambda *a, **k: _Resp())
    with pytest.raises(TranslationUnavailable):
        translate_batch(["One"], api_key="k")


def test_translate_batch_raises_when_the_count_does_not_match(monkeypatch):
    # A short response would silently shift every claim onto the wrong row.
    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"data": {"translations": [{"translatedText": "Mot"}]}}

    monkeypatch.setattr("pipeline.translate.requests.post",
                        lambda *a, **k: _Resp())
    with pytest.raises(TranslationUnavailable):
        translate_batch(["One", "Two"], api_key="k")
