import io
import zipfile
from unittest.mock import Mock

import pandas as pd
import pytest
import requests

from pipeline.ingestion import GDELT2Ingestor


def _zip_tsv(content: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("export.CSV", content)
    return buffer.getvalue()


def _gdelt_v2_row(global_event_id: int, event_root_code: int) -> str:
    cols = [""] * 61
    cols[0] = str(global_event_id)  # GLOBALEVENTID
    cols[1] = "20260505"  # SQLDATE
    cols[6] = "Actor Name"  # Actor1Name
    cols[26] = "190"  # EventCode
    cols[28] = str(event_root_code)  # EventRootCode
    cols[56] = "10.1234"  # ActionGeo_Lat
    cols[57] = "106.1234"  # ActionGeo_Long
    cols[60] = f"https://example.com/{global_event_id}"  # SOURCEURL
    return "\t".join(cols)


def test_fetch_latest_url_parses_lastupdate_index(monkeypatch: pytest.MonkeyPatch) -> None:
    response = Mock()
    response.raise_for_status.return_value = None
    response.text = (
        "175211 77290142 http://data.gdeltproject.org/gdeltv2/20260505080000.export.CSV.zip\n"
        "4137 1893 http://data.gdeltproject.org/gdeltv2/20260505080000.mentions.CSV.zip\n"
    )
    monkeypatch.setattr("pipeline.ingestion.requests.get", Mock(return_value=response))

    ingestor = GDELT2Ingestor()
    url = ingestor.fetch_latest_url()

    assert url.endswith(".export.CSV.zip")


def test_download_csv_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    compressed = _zip_tsv("GlobalEventID\tEventRootCode\n1\t14\n")
    ok_response = Mock()
    ok_response.raise_for_status.return_value = None
    ok_response.content = compressed

    get_mock = Mock(
        side_effect=[
            requests.RequestException("temporary failure"),
            requests.RequestException("temporary failure"),
            ok_response,
        ]
    )
    monkeypatch.setattr("pipeline.ingestion.requests.get", get_mock)
    monkeypatch.setattr("pipeline.ingestion.time.sleep", Mock())

    ingestor = GDELT2Ingestor(max_retries=3)
    df = ingestor.download_csv("http://example.com/export.CSV.zip")

    assert get_mock.call_count == 3
    assert len(df) == 1
    assert set(df.columns) == {"GlobalEventID", "EventRootCode"}


def test_filter_military_keeps_event_root_code_14_to_19() -> None:
    ingestor = GDELT2Ingestor()
    df = pd.DataFrame(
        {
            "GlobalEventID": [1, 2, 3, 4, 5, 6],
            "EventRootCode": ["13", "14", "17", "19", "20", None],
        }
    )

    filtered = ingestor.filter_military(df)

    assert filtered["GlobalEventID"].tolist() == [2, 3, 4]
    assert filtered["EventRootCode"].tolist() == [14, 17, 19]


def test_run_once_supports_headerless_gdelt_export(monkeypatch: pytest.MonkeyPatch) -> None:
    lastupdate_response = Mock()
    lastupdate_response.raise_for_status.return_value = None
    lastupdate_response.text = (
        "175211 77290142 http://data.gdeltproject.org/gdeltv2/20260505080000.export.CSV.zip\n"
    )

    export_content = _zip_tsv(
        f"{_gdelt_v2_row(1, 14)}\n{_gdelt_v2_row(2, 13)}\n"
    )
    export_response = Mock()
    export_response.raise_for_status.return_value = None
    export_response.content = export_content

    monkeypatch.setattr(
        "pipeline.ingestion.requests.get",
        Mock(side_effect=[lastupdate_response, export_response]),
    )
    # run_once goes through fetch_latest_existing_url, which HEAD-checks each
    # candidate. Unmocked, that reaches data.gdeltproject.org for a URL this
    # test invented; the 404 it gets back leaves no accessible candidate and
    # the test fails everywhere, network or not.
    monkeypatch.setattr(
        "pipeline.ingestion.requests.head",
        Mock(return_value=Mock(status_code=200)),
    )

    ingestor = GDELT2Ingestor()
    filtered = ingestor.run_once()

    assert filtered["GlobalEventID"].tolist() == [1]
    assert filtered["EventRootCode"].tolist() == [14]


def test_download_csv_retries_same_latest_url_on_404_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    latest_url = "http://data.gdeltproject.org/gdeltv2/20260506003000.export.CSV.zip"

    not_found_response = Mock()
    not_found_response.status_code = 404
    not_found_response.raise_for_status.side_effect = requests.HTTPError(response=not_found_response)

    compressed = _zip_tsv("GlobalEventID\tEventRootCode\n1\t14\n")
    ok_response = Mock()
    ok_response.raise_for_status.return_value = None
    ok_response.content = compressed

    get_mock = Mock(side_effect=[not_found_response, ok_response])
    monkeypatch.setattr("pipeline.ingestion.requests.get", get_mock)
    monkeypatch.setattr("pipeline.ingestion.time.sleep", Mock())

    ingestor = GDELT2Ingestor(max_retries=1)
    df = ingestor.download_csv(latest_url)

    assert len(df) == 1
    assert df["EventRootCode"].tolist() == [14]
    assert get_mock.call_count == 2
    assert get_mock.call_args_list[0].args[0] == latest_url
    assert get_mock.call_args_list[1].args[0] == latest_url


# ---------------------------------------------------------------------------
# ACLED tests (Phase E1)
# ---------------------------------------------------------------------------


def test_acled_event_type_mapping() -> None:
    from pipeline.ingestion import _map_acled_event_type

    assert _map_acled_event_type("Battles") == "armed_conflict"
    assert _map_acled_event_type("Explosions/Remote violence") == "armed_conflict"
    assert _map_acled_event_type("Violence against civilians") == "civilian_violence"
    assert _map_acled_event_type("Protests") == "civil_unrest"
    assert _map_acled_event_type("Riots") == "civil_unrest"
    assert _map_acled_event_type("Strategic developments") == "civilian_violence"
    assert _map_acled_event_type("") == "civilian_violence"
    assert _map_acled_event_type(None) == "civilian_violence"


def test_acled_extract_source_domain() -> None:
    from pipeline.ingestion import _extract_acled_source_domain

    assert _extract_acled_source_domain("Agence France-Presse") == "agence.france.presse"
    assert _extract_acled_source_domain("Radio Free Europe/Radio Liberty") == "radio.free.europe.radio.liberty"
    assert _extract_acled_source_domain("") == "acleddata.com"
    assert _extract_acled_source_domain(None) == "acleddata.com"


def test_acled_insert_to_db(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock

    from pipeline.ingestion import ACLEDIngestor

    mock_exec = MagicMock()
    monkeypatch.setattr("pipeline.ingestion.execute_values", mock_exec)
    monkeypatch.setattr(
        "pipeline.ingestion._register_acled_source",
        MagicMock(return_value=5),
    )
    monkeypatch.setattr(
        "pipeline.ingestion.assign_grid_cell",
        MagicMock(return_value="1x1_LAT48_LON2"),
    )

    ingestor = ACLEDIngestor(username="test@test.com", password="test_pw")
    df = pd.DataFrame(
        {
            "event_id_cnty": ["TEST001"],
            "event_date": ["2024-01-15"],
            "latitude": [48.85],
            "longitude": [2.35],
            "country_code": ["FRA"],
            "source_domain": ["example.com"],
            "event_type_label": ["armed_conflict"],
            "location": ["Paris"],
        }
    )

    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    count = ingestor.insert_to_db(df, mock_conn)
    assert count == 1
    assert mock_exec.called

    # Verify records contain 'ACLED' as source_system and grid_cell_id
    call_args = mock_exec.call_args
    records = call_args[0][2]  # third positional arg = records list
    assert records[0][0] == "ACLED"
    assert records[0][10] == "1x1_LAT48_LON2"


def test_acled_fetch_cache_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify fetch_events returns cached data without calling the API."""
    from unittest.mock import MagicMock

    from pipeline.ingestion import ACLEDIngestor

    try:
        import redis  # noqa: F401
    except ImportError:
        pytest.skip("redis package not installed")

    test_df = pd.DataFrame(
        {
            "event_id_cnty": ["CACHED001"],
            "event_date": ["2024-01-15"],
            "latitude": [48.85],
            "longitude": [2.35],
            "country_code": ["FRA"],
            "source_domain": ["cached.com"],
            "event_type_label": ["armed_conflict"],
        }
    )

    mock_redis = MagicMock()
    mock_redis.get.return_value = test_df.to_json().encode("utf-8")
    mock_redis.ping.return_value = True

    mock_redis_lib = MagicMock()
    mock_redis_lib.from_url.return_value = mock_redis

    monkeypatch.setattr("pipeline.ingestion.REDIS_AVAILABLE", True)
    monkeypatch.setattr("pipeline.ingestion._redis_lib", mock_redis_lib)

    ingestor = ACLEDIngestor(username="test@test.com", password="test_pw")
    df = ingestor.fetch_events(days=7)

    assert len(df) == 1
    assert df.iloc[0]["event_id_cnty"] == "CACHED001"
    mock_redis.get.assert_called()


def test_acled_oauth_token_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """Token is fetched via password grant against the myACLED OAuth endpoint."""
    from unittest.mock import MagicMock

    from pipeline.ingestion import ACLEDIngestor

    monkeypatch.setattr("pipeline.ingestion.REDIS_AVAILABLE", False)

    token_response = MagicMock()
    token_response.status_code = 200
    token_response.json.return_value = {
        "access_token": "tok123",
        "refresh_token": "ref456",
        "expires_in": 86400,
        "token_type": "Bearer",
    }
    post_mock = MagicMock(return_value=token_response)
    monkeypatch.setattr("pipeline.ingestion.requests.post", post_mock)

    ingestor = ACLEDIngestor(username="user@test.com", password="pw")
    token = ingestor._get_access_token()

    assert token == "tok123"
    call = post_mock.call_args
    assert call.args[0] == "https://acleddata.com/oauth/token"
    assert call.kwargs["data"] == {
        "username": "user@test.com",
        "password": "pw",
        "grant_type": "password",
        "client_id": "acled",
        "scope": "authenticated",
    }


def test_acled_token_reused_until_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    """A second token request within the validity window hits the in-memory cache."""
    from unittest.mock import MagicMock

    from pipeline.ingestion import ACLEDIngestor

    monkeypatch.setattr("pipeline.ingestion.REDIS_AVAILABLE", False)

    token_response = MagicMock()
    token_response.status_code = 200
    token_response.json.return_value = {
        "access_token": "tok123",
        "expires_in": 86400,
    }
    post_mock = MagicMock(return_value=token_response)
    monkeypatch.setattr("pipeline.ingestion.requests.post", post_mock)

    ingestor = ACLEDIngestor(username="user@test.com", password="pw")

    assert ingestor._get_access_token() == "tok123"
    assert ingestor._get_access_token() == "tok123"
    assert post_mock.call_count == 1


def test_acled_fetch_uses_bearer_token_and_new_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Data requests hit acleddata.com/api with a Bearer header, no key/email params."""
    from unittest.mock import MagicMock

    from pipeline.ingestion import ACLEDIngestor

    monkeypatch.setattr("pipeline.ingestion.REDIS_AVAILABLE", False)

    api_response = MagicMock()
    api_response.status_code = 200
    api_response.json.return_value = {
        "data": [
            {
                "event_id_cnty": "UKR1",
                "event_date": "2026-06-10",
                "latitude": "50.45",
                "longitude": "30.52",
                "country": "Ukraine",
                "event_type": "Battles",
                "source": "Reuters",
            }
        ]
    }
    get_mock = MagicMock(return_value=api_response)
    monkeypatch.setattr("pipeline.ingestion.requests.get", get_mock)

    ingestor = ACLEDIngestor(username="user@test.com", password="pw")
    monkeypatch.setattr(
        ingestor, "_get_access_token", lambda force_refresh=False: "tok123"
    )

    df = ingestor._fetch_from_api(days=7)

    assert len(df) == 1
    call = get_mock.call_args
    assert call.args[0] == "https://acleddata.com/api/acled/read"
    assert call.kwargs["headers"]["Authorization"] == "Bearer tok123"
    assert call.kwargs["params"]["limit"] == 5000
    assert "key" not in call.kwargs["params"]
    assert "email" not in call.kwargs["params"]


def test_acled_fetch_reauths_on_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """An expired/rejected token triggers exactly one re-auth, then the retry succeeds."""
    from unittest.mock import MagicMock

    from pipeline.ingestion import ACLEDIngestor

    monkeypatch.setattr("pipeline.ingestion.REDIS_AVAILABLE", False)
    monkeypatch.setattr("pipeline.ingestion.time.sleep", Mock())

    unauthorized = MagicMock()
    unauthorized.status_code = 401
    ok = MagicMock()
    ok.status_code = 200
    ok.json.return_value = {"data": []}
    get_mock = MagicMock(side_effect=[unauthorized, ok])
    monkeypatch.setattr("pipeline.ingestion.requests.get", get_mock)

    token_response = MagicMock()
    token_response.status_code = 200
    token_response.json.return_value = {
        "access_token": "tok",
        "expires_in": 86400,
    }
    post_mock = MagicMock(return_value=token_response)
    monkeypatch.setattr("pipeline.ingestion.requests.post", post_mock)

    ingestor = ACLEDIngestor(username="user@test.com", password="pw")
    result = ingestor._fetch_page_with_retry({"page": 1})

    assert result == {"data": []}
    assert get_mock.call_count == 2
    # one initial password grant + one forced re-auth after the 401
    assert post_mock.call_count == 2


def test_acled_fetch_multipage_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pagination fetches consecutive pages and stops when a page is shorter than page_size."""
    from unittest.mock import MagicMock

    from pipeline.ingestion import ACLEDIngestor

    monkeypatch.setattr("pipeline.ingestion.REDIS_AVAILABLE", False)

    page_1_events = [
        {
            "event_id_cnty": f"UKR{i:04d}",
            "event_date": "2026-06-10",
            "latitude": "50.45",
            "longitude": "30.52",
            "country": "Ukraine",
            "event_type": "Battles",
            "source": "Reuters",
        }
        for i in range(3)
    ]
    page_2_events = [
        {
            "event_id_cnty": "UKR1001",
            "event_date": "2026-06-10",
            "latitude": "50.45",
            "longitude": "30.52",
            "country": "Ukraine",
            "event_type": "Protests",
            "source": "AFP",
        }
    ]

    page_1_response = MagicMock()
    page_1_response.status_code = 200
    page_1_response.json.return_value = {"data": page_1_events}
    page_2_response = MagicMock()
    page_2_response.status_code = 200
    page_2_response.json.return_value = {"data": page_2_events}
    get_mock = MagicMock(side_effect=[page_1_response, page_2_response])
    monkeypatch.setattr("pipeline.ingestion.requests.get", get_mock)

    ingestor = ACLEDIngestor(username="user@test.com", password="pw")
    ingestor.page_size = 3  # smaller for test convenience

    monkeypatch.setattr(
        ingestor, "_get_access_token", lambda force_refresh=False: "tok123"
    )

    df = ingestor._fetch_from_api(days=7)

    assert len(df) == 4
    assert get_mock.call_count == 2
    # page 1 params
    assert get_mock.call_args_list[0].kwargs["params"]["page"] == 1
    # page 2 params
    assert get_mock.call_args_list[1].kwargs["params"]["page"] == 2


def test_build_event_records_carries_geo_precision(synthetic_gdelt_df):
    df = GDELT2Ingestor._normalize_columns(synthetic_gdelt_df.copy())
    df["ActionGeo_Type"] = [1, 4, 3, 1, 2, 5]
    records = list(GDELT2Ingestor._build_event_records(df))
    assert records, "expected records from valid coordinates"
    assert records[0][8] == 1
    assert records[1][8] == 4


def test_build_event_records_tolerates_missing_geo_type(synthetic_gdelt_df):
    df = GDELT2Ingestor._normalize_columns(synthetic_gdelt_df.copy())
    records = list(GDELT2Ingestor._build_event_records(df))
    assert records
    assert all(r[8] is None for r in records)


def test_augment_records_appends_geo_precision(synthetic_gdelt_df):
    df = GDELT2Ingestor._normalize_columns(synthetic_gdelt_df.copy())
    df["ActionGeo_Type"] = [1, 4, 3, 1, 2, 5]
    ingestor = GDELT2Ingestor()
    records = list(ingestor._build_event_records(df))
    augmented = ingestor._augment_records(records, {})
    # geo_precision is at index 12 (0-based), after grid_cell_id and before enrichment fields
    assert augmented[0][12] == 1
    assert augmented[1][12] == 4
