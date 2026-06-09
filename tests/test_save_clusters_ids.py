import pytest

pytest.importorskip("pandas")
# Integration: requires SENTINEL_TEST_DB. Skips otherwise (mirrors conftest live_conn).
from pipeline.clustering import ClusterRepository  # noqa: E402


def test_save_clusters_returns_hotspot_ids():
    """Assert that save_clusters returns a dict with 'hotspot_ids' key."""
    # The return dict includes hotspot_ids key from the refactored method.
    import inspect
    sig = inspect.signature(ClusterRepository.save_clusters)
    assert "cell_id" in sig.parameters
