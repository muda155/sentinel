from api.metrics import METRICS, render_prometheus


def test_counter_increments_and_renders():
    METRICS.reset()
    METRICS.inc("hotspots_created_total")
    METRICS.inc("llm_fallback_total", 2)
    text = render_prometheus()
    assert "hotspots_created_total 1" in text
    assert "llm_fallback_total 2" in text
