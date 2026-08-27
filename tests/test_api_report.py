"""GET /hotspots/{id}/report — window-scoped narrative (FR-29)."""
import pytest
from fastapi.testclient import TestClient

from api.app import app
from pipeline.window_report import build_window_report_prompt, window_citations

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_report_state(monkeypatch):
    # Redis may be live from docker compose, and a cache hit would serve a
    # previous test's narrative instead of exercising the branch under test.
    # (The rate-limit buckets are reset for every test by conftest.)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6399")


def _auth_headers():
    r = client.post("/auth/login", json={"username": "analyst", "password": "analyst"})
    if r.status_code != 200:
        pytest.skip("default analyst credentials unavailable")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_prompt_states_the_window_bounds_and_requires_citations():
    events = [{"event_id": 1, "citation_index": 1, "title": "Shelling reported",
               "url": "https://a.test/1", "domain": "a.com"}]
    prompt = build_window_report_prompt("Khartoum Region", events,
                                        "2026-08-05T00:00:00Z", "2026-08-06T00:00:00Z")
    assert "2026-08-05T00:00:00Z" in prompt
    assert "2026-08-06T00:00:00Z" in prompt
    assert "[1]" in prompt


def test_citation_indices_are_reassigned_within_the_window():
    # The panel numbers citations over ALL of a hotspot's events; a windowed
    # report that inherited those numbers would start at [4] and cite rows it
    # does not contain.
    events = [
        {"event_id": 40, "citation_index": 4, "title": "A", "url": "https://a.test", "domain": "a.com"},
        {"event_id": 70, "citation_index": 7, "title": "B", "url": "https://b.test", "domain": "b.com"},
    ]
    assert [c["index"] for c in window_citations(events)] == [1, 2]


def test_report_requires_auth():
    r = client.get("/hotspots/1/report?from=2026-08-05T00:00:00Z&to=2026-08-06T00:00:00Z")
    assert r.status_code in (401, 403)


def test_report_rejects_an_inverted_window():
    r = client.get("/hotspots/1/report?from=2026-08-06T00:00:00Z&to=2026-08-05T00:00:00Z",
                   headers=_auth_headers())
    assert r.status_code == 422


def test_report_404s_for_an_unknown_hotspot():
    r = client.get("/hotspots/999999999/report"
                   "?from=2026-08-05T00:00:00Z&to=2026-08-06T00:00:00Z",
                   headers=_auth_headers())
    assert r.status_code == 404


def test_report_is_unavailable_without_llm_credentials(monkeypatch):
    # The route's only DB needs are events + a name for the prompt. Patching
    # the query functions lets the test reach the credentials check (the 503
    # branch) without seeding a committed hotspot, which the rollback-based
    # live_conn fixture cannot provide.
    from datetime import datetime, timezone

    from api import queries

    now = datetime(2026, 8, 5, 6, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(queries, "fetch_hotspot_events", lambda conn, hid: [{
        "event_id": 1, "title": "Shelling reported", "url": "https://a.test/1",
        "source_system": "GDELT", "event_date": now, "domain": "a.com",
        "duplicate_count": 1,
    }])
    monkeypatch.setattr(queries, "fetch_hotspot_name", lambda conn, hid: "Test Hotspot")
    monkeypatch.setenv("NVIDIA_NIM_ENDPOINT", "")
    monkeypatch.setenv("OLLAMA_ENDPOINT", "")

    r = client.get("/hotspots/1/report?from=2026-08-05T00:00:00Z&to=2026-08-06T00:00:00Z",
                   headers=_auth_headers())
    assert r.status_code == 503


def _patch_llm_only(monkeypatch):
    from datetime import datetime, timezone

    from api import queries

    now = datetime(2026, 8, 5, 6, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(queries, "fetch_hotspot_events", lambda conn, hid: [{
        "event_id": 1, "title": "Shelling reported", "url": "https://a.test/1",
        "source_system": "GDELT", "event_date": now, "domain": "a.com",
        "duplicate_count": 1,
    }])
    monkeypatch.setattr(queries, "fetch_hotspot_name", lambda conn, hid: "Test Hotspot")
    monkeypatch.setenv("NVIDIA_NIM_ENDPOINT", "")
    monkeypatch.setenv("OLLAMA_ENDPOINT", "http://localhost:11434")


def test_report_serves_an_ollama_only_deployment(monkeypatch):
    _patch_llm_only(monkeypatch)
    monkeypatch.setattr(
        "pipeline.llm_providers.call_ollama_raw",
        lambda prompt, endpoint="http://localhost:11434", timeout=None:
        ("Shelling was reported near the border [1].", "llama-3-8b-ollama"),
    )
    r = client.get("/hotspots/1/report?from=2026-08-05T00:00:00Z&to=2026-08-06T00:00:00Z",
                   headers=_auth_headers())
    assert r.status_code == 200
    body = r.json()
    assert "Shelling was reported near the border" in body["narrative"]
    assert body["cached"] is False


def test_report_422s_when_the_narrative_lacks_citations(monkeypatch):
    _patch_llm_only(monkeypatch)
    monkeypatch.setattr(
        "pipeline.llm_providers.call_ollama_raw",
        lambda prompt, endpoint="http://localhost:11434", timeout=None:
        ("The situation is calm.", "llama-3-8b-ollama"),
    )
    r = client.get("/hotspots/1/report?from=2026-08-05T00:00:00Z&to=2026-08-06T00:00:00Z",
                   headers=_auth_headers())
    assert r.status_code == 422


def test_report_handles_naive_window_times(monkeypatch):
    # A client may send from/to without a Z/offset. Treating them as naive makes
    # the window filter compare against tz-aware event_date and crash with a
    # TypeError (unhandled 500) instead of a clean 4xx.
    _patch_llm_only(monkeypatch)
    r = client.get("/hotspots/1/report?from=2026-08-06T00:00:00&to=2026-08-07T00:00:00",
                   headers=_auth_headers())
    # The event sits at 2026-08-05T06:00Z, outside the naive-as-UTC window.
    assert r.status_code == 404
