from api.metrics import METRICS


def test_fallback_counter_increments(monkeypatch):
    monkeypatch.setattr("os.getenv", lambda k, d="": "http://ollama:11434" if k == "OLLAMA_ENDPOINT" else d)
    METRICS.reset()
    METRICS.inc("llm_fallback_total")
    text = METRICS.snapshot()
    assert text.get("llm_fallback_total", 0) >= 1
