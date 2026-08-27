"""GET /hotspots/{id}/translation - Vietnamese display translation (FR-30)."""
import pytest
from fastapi.testclient import TestClient

from api.app import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_translation_state(monkeypatch):
    # Point at a dead Redis so a live docker-compose cache cannot serve another
    # test's payload. (Rate-limit buckets are reset per test by conftest.)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6399")
    monkeypatch.setattr("api.cache._client", None, raising=False)
    monkeypatch.setenv("GOOGLE_TRANSLATE_API_KEY", "test-key")
    monkeypatch.setenv("SENTINEL_TRANSLATE_ENABLED", "true")


def _auth_headers():
    r = client.post("/auth/login", json={"username": "analyst", "password": "analyst"})
    if r.status_code != 200:
        pytest.skip("default analyst credentials unavailable")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _patch_hotspot(monkeypatch, summary="Forces advanced [1].", claims=None):
    claims = [{"claim_id": 7, "claim_text": "Military forces advanced north."}] \
        if claims is None else claims
    monkeypatch.setattr("api.routes.translate.queries.fetch_hotspot_summary",
                        lambda conn, hid: {"summary": summary})
    monkeypatch.setattr("api.routes.translate.queries.fetch_hotspot_claims",
                        lambda conn, hid: {"claims": claims})


def test_translation_requires_auth():
    r = client.get("/hotspots/1/translation?lang=vi")
    assert r.status_code in (401, 403)


def test_translation_rejects_an_unsupported_language(monkeypatch):
    _patch_hotspot(monkeypatch)
    r = client.get("/hotspots/1/translation?lang=fr", headers=_auth_headers())
    assert r.status_code == 422


def test_translation_404s_for_an_unknown_hotspot(monkeypatch):
    monkeypatch.setattr("api.routes.translate.queries.fetch_hotspot_summary",
                        lambda conn, hid: None)
    monkeypatch.setattr("api.routes.translate.queries.fetch_hotspot_claims",
                        lambda conn, hid: None)
    r = client.get("/hotspots/999999999/translation?lang=vi", headers=_auth_headers())
    assert r.status_code == 404


def test_translation_is_unavailable_without_an_api_key(monkeypatch):
    _patch_hotspot(monkeypatch)
    monkeypatch.delenv("GOOGLE_TRANSLATE_API_KEY", raising=False)
    r = client.get("/hotspots/1/translation?lang=vi", headers=_auth_headers())
    assert r.status_code == 503


def test_an_empty_hotspot_returns_200_without_calling_google(monkeypatch):
    _patch_hotspot(monkeypatch, summary="", claims=[])

    def _explode(*a, **k):
        raise AssertionError("must not call Google when there is nothing to translate")

    monkeypatch.setattr("api.routes.translate.translate_batch", _explode)
    r = client.get("/hotspots/1/translation?lang=vi", headers=_auth_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["summary"] == ""
    assert body["claims"] == []


def test_markers_survive_and_claims_keep_their_ids(monkeypatch):
    _patch_hotspot(monkeypatch)
    monkeypatch.setattr(
        "api.routes.translate.translate_batch",
        lambda strings, **kw: ['L&#7921;c l&#432;&#7907;ng <span translate="no">[1]</span>.',
                               "Quân đội tiến về phía bắc."],
    )
    r = client.get("/hotspots/1/translation?lang=vi", headers=_auth_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["summary_translated"] is True
    assert "[1]" in body["summary"]
    assert "&#" not in body["summary"]
    assert body["claims"] == [{"claim_id": 7, "text": "Quân đội tiến về phía bắc."}]


def test_a_dropped_marker_falls_back_to_the_english_summary(monkeypatch):
    _patch_hotspot(monkeypatch)
    # Translation lost [1] - the panel's citation jump would break.
    monkeypatch.setattr(
        "api.routes.translate.translate_batch",
        lambda strings, **kw: ["Lực lượng đã tiến lên.", "Quân đội tiến về phía bắc."],
    )
    r = client.get("/hotspots/1/translation?lang=vi", headers=_auth_headers())
    body = r.json()
    assert body["summary_translated"] is False
    assert body["summary"] == "Forces advanced [1]."
    # The claim is unaffected - it carries no markers.
    assert body["claims"][0]["text"] == "Quân đội tiến về phía bắc."


def test_google_failure_is_a_503(monkeypatch):
    from pipeline.translate import TranslationUnavailable
    _patch_hotspot(monkeypatch)

    def _fail(*a, **k):
        raise TranslationUnavailable("boom")

    monkeypatch.setattr("api.routes.translate.translate_batch", _fail)
    r = client.get("/hotspots/1/translation?lang=vi", headers=_auth_headers())
    assert r.status_code == 503


def test_over_cap_claims_are_returned_untranslated(monkeypatch):
    monkeypatch.setenv("SENTINEL_TRANSLATE_MAX_CHARS", "40")
    _patch_hotspot(monkeypatch, summary="Short [1].", claims=[
        {"claim_id": 1, "claim_text": "A" * 30},
        {"claim_id": 2, "claim_text": "B" * 30},
    ])
    monkeypatch.setattr("api.routes.translate.translate_batch",
                        lambda strings, **kw: ["Ngắn <span translate=\"no\">[1]</span>.",
                                               "Đã dịch"])
    r = client.get("/hotspots/1/translation?lang=vi", headers=_auth_headers())
    body = r.json()
    assert [c["claim_id"] for c in body["claims"]] == [1, 2]
    # The second claim exceeded the budget and came back as its English source.
    assert body["claims"][1]["text"] == "B" * 30


def test_cache_key_changes_when_a_claim_changes(monkeypatch):
    from api.routes.translate import _cache_key
    a = _cache_key("vi", 1, "S [1].", [{"claim_id": 7, "claim_text": "One"}])
    b = _cache_key("vi", 1, "S [1].", [{"claim_id": 7, "claim_text": "Two"}])
    assert a != b
