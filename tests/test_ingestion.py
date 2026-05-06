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

    ingestor = GDELT2Ingestor()
    filtered = ingestor.run_once()

    assert filtered["GlobalEventID"].tolist() == [1]
    assert filtered["EventRootCode"].tolist() == [14]
