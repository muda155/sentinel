from __future__ import annotations

import argparse
import io
import re
import time
from dataclasses import dataclass
from typing import Iterable

import pandas as pd
import requests
from psycopg2.extras import execute_values

from pipeline.db import get_connection

LASTUPDATE_URL = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"
GDELT_V2_COLUMNS = [
    "GLOBALEVENTID",
    "SQLDATE",
    "MonthYear",
    "Year",
    "FractionDate",
    "Actor1Code",
    "Actor1Name",
    "Actor1CountryCode",
    "Actor1KnownGroupCode",
    "Actor1EthnicCode",
    "Actor1Religion1Code",
    "Actor1Religion2Code",
    "Actor1Type1Code",
    "Actor1Type2Code",
    "Actor1Type3Code",
    "Actor2Code",
    "Actor2Name",
    "Actor2CountryCode",
    "Actor2KnownGroupCode",
    "Actor2EthnicCode",
    "Actor2Religion1Code",
    "Actor2Religion2Code",
    "Actor2Type1Code",
    "Actor2Type2Code",
    "Actor2Type3Code",
    "IsRootEvent",
    "EventCode",
    "EventBaseCode",
    "EventRootCode",
    "QuadClass",
    "GoldsteinScale",
    "NumMentions",
    "NumSources",
    "NumArticles",
    "AvgTone",
    "Actor1Geo_Type",
    "Actor1Geo_FullName",
    "Actor1Geo_CountryCode",
    "Actor1Geo_ADM1Code",
    "Actor1Geo_ADM2Code",
    "Actor1Geo_Lat",
    "Actor1Geo_Long",
    "Actor1Geo_FeatureID",
    "Actor2Geo_Type",
    "Actor2Geo_FullName",
    "Actor2Geo_CountryCode",
    "Actor2Geo_ADM1Code",
    "Actor2Geo_ADM2Code",
    "Actor2Geo_Lat",
    "Actor2Geo_Long",
    "Actor2Geo_FeatureID",
    "ActionGeo_Type",
    "ActionGeo_FullName",
    "ActionGeo_CountryCode",
    "ActionGeo_ADM1Code",
    "ActionGeo_ADM2Code",
    "ActionGeo_Lat",
    "ActionGeo_Long",
    "ActionGeo_FeatureID",
    "DATEADDED",
    "SOURCEURL",
]


@dataclass(slots=True)
class GDELT2Ingestor:
    timeout_seconds: int = 30
    max_retries: int = 3
    backoff_base_seconds: float = 1.0
    latest_export_retries: int = 12
    latest_export_backoff_seconds: float = 10.0

    def fetch_latest_url(self) -> str:
        response = self._get_with_retry(LASTUPDATE_URL)

        for line in response.text.splitlines():
            parts = line.strip().split()
            if len(parts) >= 3 and parts[2].endswith(".export.CSV.zip"):
                return parts[2]
        raise ValueError("No export CSV URL found in lastupdate index")

    def download_csv(self, url: str) -> pd.DataFrame:
        response = self._download_latest_export(url)

        raw_df = pd.read_csv(
            io.BytesIO(response.content),
            sep="\t",
            compression="zip",
            low_memory=False,
        )
        normalized = self._normalize_columns(raw_df)
        if "EventRootCode" in normalized.columns:
            return normalized

        # GDELT exports are headerless; retry with known v2 column layout.
        fallback_df = pd.read_csv(
            io.BytesIO(response.content),
            sep="\t",
            compression="zip",
            header=None,
            names=GDELT_V2_COLUMNS,
            low_memory=False,
        )
        return self._normalize_columns(fallback_df)

    def filter_military(self, df: pd.DataFrame) -> pd.DataFrame:
        parsed_codes = pd.to_numeric(df["EventRootCode"], errors="coerce")
        filtered = df[parsed_codes.between(14, 19, inclusive="both")].copy()
        filtered["EventRootCode"] = parsed_codes.loc[filtered.index].astype(int)
        return filtered

    def insert_to_db(self, df: pd.DataFrame, conn) -> int:
        records = list(self._build_event_records(df))
        if not records:
            return 0

        with conn.cursor() as cursor:
            execute_values(
                cursor,
                """
                INSERT INTO events (
                    gdelt_global_event_id,
                    event_date,
                    cameo_code,
                    country_code,
                    url,
                    title,
                    point_geom
                )
                VALUES %s
                ON CONFLICT (gdelt_global_event_id) DO NOTHING
                """,
                records,
                template=(
                    "(%s, %s, %s, %s, %s, %s, "
                    "ST_SetSRID(ST_MakePoint(%s, %s), 4326))"
                ),
            )
        conn.commit()
        return len(records)

    def run_once(self) -> pd.DataFrame:
        latest_url = self.fetch_latest_url()
        raw_df = self.download_csv(latest_url)
        return self.filter_military(raw_df)

    def _get_with_retry(self, url: str) -> requests.Response:
        last_error: requests.RequestException | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.get(url, timeout=self.timeout_seconds)
                response.raise_for_status()
                return response
            except requests.RequestException as error:
                last_error = error
                if attempt == self.max_retries:
                    break
                time.sleep(self.backoff_base_seconds * (2 ** (attempt - 1)))

        if last_error is None:
            raise RuntimeError("Retry loop ended unexpectedly without an error")
        raise last_error

    @staticmethod
    def _build_event_records(df: pd.DataFrame) -> Iterable[tuple]:
        required_columns = {
            "GlobalEventID",
            "SQLDATE",
            "EventCode",
            "SOURCEURL",
            "Actor1Name",
            "ActionGeo_Lat",
            "ActionGeo_Long",
        }
        missing = required_columns - set(df.columns)
        if missing:
            raise ValueError(f"DataFrame missing required columns: {sorted(missing)}")

        valid_coords = df[
            df["ActionGeo_Lat"].notna()
            & df["ActionGeo_Long"].notna()
            & df["SQLDATE"].notna()
            & df["GlobalEventID"].notna()
        ]

        for _, row in valid_coords.iterrows():
            yield (
                int(row["GlobalEventID"]),
                pd.to_datetime(str(int(row["SQLDATE"])), format="%Y%m%d", utc=True),
                str(row["EventCode"]) if pd.notna(row["EventCode"]) else None,
                str(row["ActionGeo_CountryCode"])
                if "ActionGeo_CountryCode" in row and pd.notna(row["ActionGeo_CountryCode"])
                else None,
                str(row["SOURCEURL"]) if pd.notna(row["SOURCEURL"]) else None,
                str(row["Actor1Name"]) if pd.notna(row["Actor1Name"]) else None,
                float(row["ActionGeo_Long"]),
                float(row["ActionGeo_Lat"]),
            )

    @staticmethod
    def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
        canonical_by_token = {
            "globaleventid": "GlobalEventID",
            "eventrootcode": "EventRootCode",
            "sqldate": "SQLDATE",
            "eventcode": "EventCode",
            "sourceurl": "SOURCEURL",
            "actor1name": "Actor1Name",
            "actiongeolat": "ActionGeo_Lat",
            "actiongeolong": "ActionGeo_Long",
            "actiongeocountrycode": "ActionGeo_CountryCode",
        }
        rename_map = {}
        for column in df.columns:
            token = re.sub(r"[^a-zA-Z0-9]+", "", str(column)).lower()
            if token in canonical_by_token:
                rename_map[column] = canonical_by_token[token]
        return df.rename(columns=rename_map)

    def _download_latest_export(self, url: str) -> requests.Response:
        last_error: requests.RequestException | None = None
        for attempt in range(1, self.latest_export_retries + 1):
            try:
                return self._get_with_retry(url)
            except requests.HTTPError as error:
                status_code = (
                    error.response.status_code if error.response is not None else None
                )
                last_error = error
                if status_code != 404 or attempt == self.latest_export_retries:
                    raise
                time.sleep(self.latest_export_backoff_seconds)

        if last_error is None:
            raise RuntimeError("Retry loop ended unexpectedly without an error")
        raise last_error


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch and filter latest GDELT 2.0 export")
    parser.add_argument(
        "--output-csv",
        default="military_events.csv",
        help="Where to write the filtered output CSV",
    )
    parser.add_argument(
        "--insert-db",
        action="store_true",
        help="Insert filtered events into PostgreSQL events table",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    ingestor = GDELT2Ingestor()
    military_df = ingestor.run_once()
    military_df.to_csv(args.output_csv, index=False)
    print(f"Saved {len(military_df)} military events to {args.output_csv}")
    if args.insert_db:
        with get_connection() as conn:
            inserted = ingestor.insert_to_db(military_df, conn)
        print(f"Inserted {inserted} records into events table")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
