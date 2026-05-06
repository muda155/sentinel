import importlib
from unittest import mock

import numpy as np
import pandas as pd
import pytest


def _sample_events() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "event_id": [1, 2, 3, 4],
            "ActionGeo_Lat": [10.0, 10.04, 10.5, 11.5],
            "ActionGeo_Long": [106.0, 106.03, 106.5, 107.5],
            "event_date": pd.to_datetime(
                [
                    "2026-05-06T00:00:00Z",
                    "2026-05-06T00:30:00Z",
                    "2026-05-06T00:20:00Z",
                    "2026-05-06T03:30:00Z",
                ],
                utc=True,
            ),
        }
    )


def test_build_distance_matrix_applies_temporal_penalty() -> None:
    clustering = importlib.import_module("pipeline.clustering")
    df = _sample_events()

    matrix = clustering.build_distance_matrix(df, max_time_diff_h=1)

    assert matrix.shape == (4, 4)
    assert matrix[0, 1] < 10
    assert matrix[0, 3] == float("inf")


def test_cluster_dbscan_groups_close_events_and_marks_noise() -> None:
    clustering = importlib.import_module("pipeline.clustering")
    df = _sample_events().iloc[[0, 1, 2]].reset_index(drop=True)
    matrix = clustering.build_distance_matrix(df, max_time_diff_h=1)

    labels = clustering.cluster_dbscan(matrix, eps_km=8, min_samples=2)

    assert labels[0] == labels[1]
    assert labels[2] == -1


def test_cluster_repository_persists_hotspots_and_event_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clustering = importlib.import_module("pipeline.clustering")
    events_df = pd.DataFrame(
        {
            "event_id": [10, 11, 12],
            "ActionGeo_Lat": [10.0, 10.02, 13.0],
            "ActionGeo_Long": [106.0, 106.02, 109.0],
            "event_date": pd.to_datetime(
                ["2026-05-06T00:00:00Z", "2026-05-06T00:20:00Z", "2026-05-06T00:30:00Z"],
                utc=True,
            ),
            "SOURCEURL": [
                "https://a.example.com/news/1",
                "https://b.example.com/news/2",
                "https://c.example.com/news/3",
            ],
        }
    )
    labels = np.array([0, 0, -1])

    class FakeCursor:
        def __init__(self) -> None:
            self.executed = []

        def execute(self, query, params=None) -> None:
            self.executed.append((query, params))

        def fetchone(self):
            return (55,)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    class FakeConn:
        def __init__(self) -> None:
            self.cursor_obj = FakeCursor()
            self.committed = False

        def cursor(self):
            return self.cursor_obj

        def commit(self) -> None:
            self.committed = True

    fake_conn = FakeConn()
    execute_values_mock = mock.Mock()
    monkeypatch.setattr("pipeline.clustering.execute_values", execute_values_mock)

    repository = clustering.ClusterRepository(fake_conn)
    summary = repository.save_clusters(events_df, labels)

    assert fake_conn.committed is True
    assert summary["hotspot_count"] == 1
    assert summary["linked_events"] == 2
    assert any("INSERT INTO hotspots" in query for query, _ in fake_conn.cursor_obj.executed)
    execute_values_mock.assert_called_once()
    assert execute_values_mock.call_args.args[2] == [(10, 55), (11, 55)]


def test_run_clustering_pipeline_calls_repository() -> None:
    clustering = importlib.import_module("pipeline.clustering")
    events_df = pd.DataFrame(
        {
            "event_id": [1, 2, 3],
            "ActionGeo_Lat": [10.0, 10.02, 12.5],
            "ActionGeo_Long": [106.0, 106.01, 109.5],
            "event_date": pd.to_datetime(
                ["2026-05-06T00:00:00Z", "2026-05-06T00:15:00Z", "2026-05-06T03:00:00Z"],
                utc=True,
            ),
            "SOURCEURL": [
                "https://a.example.com/x",
                "https://b.example.com/y",
                "https://c.example.com/z",
            ],
        }
    )

    class Repo:
        def __init__(self) -> None:
            self.called = False
            self.labels = None

        def save_clusters(self, events_df_arg, labels_arg):
            self.called = True
            self.labels = labels_arg
            return {"hotspot_count": 1, "linked_events": 2}

    repo = Repo()
    summary = clustering.run_clustering_pipeline(
        events_df, repository=repo, eps_km=8, min_samples=2, max_time_diff_h=1
    )

    assert repo.called is True
    assert summary["hotspot_count"] == 1
    assert summary["linked_events"] == 2
    assert summary["noise_count"] == 1
