
import pandas as pd
import pytest

from pipeline import scoring


def test_compute_source_density_default_divisor_3():
    # tanh(2.0/3) ≈ 0.583
    assert scoring.compute_source_density([1.0, 0.6, 0.4]) == pytest.approx(0.583, abs=0.01)


def test_compute_source_density_explicit_divisor():
    # divisor passed through; tanh(10/10)=tanh(1)≈0.762
    assert scoring.compute_source_density([1.0] * 10, divisor=10) == pytest.approx(0.762, abs=0.01)


def test_geopolitical_diversity_expected_values() -> None:
    same_country = scoring.geopolitical_diversity(["US", "US", "US"])
    equal_four = scoring.geopolitical_diversity(["US", "VN", "FR", "JP"])
    assert same_country == pytest.approx(0.0, abs=0.0001)
    assert equal_four == pytest.approx(1.0, abs=0.0001)


def test_compute_conf_score_weighted_to_100_scale() -> None:
    assert scoring.compute_conf_score(1.0, 0.0) == pytest.approx(60.0, abs=0.01)
    assert scoring.compute_conf_score(0.0, 1.0) == pytest.approx(40.0, abs=0.01)


def test_score_hotspot_from_events_aggregates_metrics() -> None:
    events_df = pd.DataFrame(
        {
            "url": ["https://a.com/1", "https://b.com/2", "https://a.com/3"],
            "country_code": ["US", "US", "VN"],
            "trust_score": [1.0, 0.8, 0.6],
        }
    )
    result = scoring.score_hotspot_from_events(events_df)
    assert result["source_density"] > 0
    assert result["geopolitical_diversity"] > 0
    assert 0 <= result["conf_score"] <= 100


def test_scoring_repository_updates_hotspot_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeCursor:
        def __init__(self) -> None:
            self.executed = []

        def execute(self, query, params=None) -> None:
            self.executed.append((query, params))

        def fetchall(self):
            return [
                ("https://a.com/1", "US", 1.0),
                ("https://b.com/2", "VN", 0.8),
            ]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConn:
        def __init__(self) -> None:
            self.cursor_obj = FakeCursor()
            self.committed = False

        def cursor(self):
            return self.cursor_obj

        def commit(self):
            self.committed = True

    repo = scoring.ScoringRepository(FakeConn())
    result = repo.score_hotspot(7)

    assert repo._conn.committed is True
    assert result["hotspot_id"] == 7
    assert any("UPDATE hotspots" in query for query, _ in repo._conn.cursor_obj.executed)


def test_compute_source_density_empty() -> None:
    assert scoring.compute_source_density([]) == 0.0


def test_score_hotspot_dedupes_by_domain():
    # a.com appears twice but counts once: weights = [a:1.0, b:0.8] over divisor 3
    events_df = pd.DataFrame({
        "domain": ["a.com", "b.com", "a.com"],
        "country_code": ["US", "US", "US"],
        "trust_score": [1.0, 0.8, 1.0],
    })
    result = scoring.score_hotspot_from_events(events_df)
    # source_density = tanh((1.0+0.8)/3) = tanh(0.6) ≈ 0.537
    assert result["source_density"] == pytest.approx(0.537, abs=0.01)
