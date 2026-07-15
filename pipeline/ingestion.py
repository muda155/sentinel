from __future__ import annotations

import argparse
import io
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

import pandas as pd
import requests
from psycopg2.extras import execute_values

from pipeline.clustering import assign_grid_cell
from pipeline.db import get_pooled_connection
from pipeline.source_country import resolve_country

try:
    import redis as _redis_lib

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    _redis_lib = None  # type: ignore[assignment]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

LASTUPDATE_URL = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"
MASTER_FILELIST_URL = "http://data.gdeltproject.org/gdeltv2/masterfilelist.txt"
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


# Mapping of GDELT 2.0 column names to expected pandas dtypes.
# Used for schema validation before further processing (FR-1).
GDELT_V2_COLUMN_TYPES: dict[str, str] = {
    "GLOBALEVENTID": "int64",
    "SQLDATE": "int64",
    "MonthYear": "int64",
    "Year": "int64",
    "FractionDate": "float64",
    "IsRootEvent": "int64",
    "EventCode": "object",
    "EventBaseCode": "object",
    "EventRootCode": "int64",
    "QuadClass": "int64",
    "GoldsteinScale": "float64",
    "NumMentions": "int64",
    "NumSources": "int64",
    "NumArticles": "int64",
    "AvgTone": "float64",
    "Actor1Geo_Type": "int64",
    "Actor1Geo_Lat": "float64",
    "Actor1Geo_Long": "float64",
    "Actor2Geo_Type": "int64",
    "Actor2Geo_Lat": "float64",
    "Actor2Geo_Long": "float64",
    "ActionGeo_Type": "int64",
    "ActionGeo_Lat": "float64",
    "ActionGeo_Long": "float64",
    "DATEADDED": "int64",
}


class SchemaError(ValueError):
    """Raised when GDELT CSV columns mismatch the expected schema (FR-1)."""
    pass


class GDELTColumnSchema:
    """Validates GDELT 2.0 export column presence before processing (FR-1)."""

    # Columns required for CAMEO filtering and event record building
    REQUIRED_COLUMNS: set[str] = {
        "GLOBALEVENTID",
        "SQLDATE",
        "EventRootCode",
        "EventCode",
        "Actor1Name",
        "ActionGeo_Lat",
        "ActionGeo_Long",
        "SOURCEURL",
    }

    @staticmethod
    def _token(name: str) -> str:
        """Normalize a column name to an alnum-lowercase token.

        Mirrors the tokenization in ``_normalize_columns`` so validation is
        agnostic to GDELT's raw casing (``GLOBALEVENTID``) versus the
        pipeline's canonical names (``GlobalEventID``). ``validate`` runs on
        already-normalized frames inside ``insert_to_db``, so it must accept
        both forms.
        """
        return re.sub(r"[^a-zA-Z0-9]+", "", str(name)).lower()

    @staticmethod
    def validate(df: pd.DataFrame) -> None:
        """Validate that all required columns are present in the DataFrame.

        Comparison is done on normalized tokens, so both the raw GDELT casing
        and the pipeline's canonical column names satisfy the requirement.

        Args:
            df: The GDELT 2.0 export DataFrame to validate.

        Raises:
            SchemaError: If any required columns are missing.
        """
        present_tokens = {GDELTColumnSchema._token(c) for c in df.columns}
        missing = {
            col
            for col in GDELTColumnSchema.REQUIRED_COLUMNS
            if GDELTColumnSchema._token(col) not in present_tokens
        }
        if missing:
            raise SchemaError(
                f"Missing required GDELT columns: {sorted(missing)}. "
                f"Available columns: {sorted(df.columns)}"
            )


@dataclass(slots=True)
class GDELT2Ingestor:
    timeout_seconds: int = 30
    max_retries: int = 3
    backoff_base_seconds: float = 1.0
    latest_export_retries: int = 12
    latest_export_backoff_seconds: float = 10.0

    def fetch_latest_url(self) -> str:
        # Try lastupdate.txt first - get the first export.CSV.zip URL
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
        # Validate schema before processing (FR-1)
        GDELTColumnSchema.validate(df)

        records = list(self._build_event_records(df))
        if not records:
            return 0

        # Register sources and get source_id for each event
        url_to_source_id = self._register_sources(df, conn)

        augmented_records = self._augment_records(records, url_to_source_id)

        with conn.cursor() as cursor:
            execute_values(
                cursor,
                """
                INSERT INTO events (
                    source_system,
                    gdelt_global_event_id,
                    external_event_id,
                    event_date,
                    cameo_code,
                    country_code,
                    url,
                    title,
                    point_geom,
                    source_id,
                    grid_cell_id,
                    geo_precision
                )
                VALUES %s
                ON CONFLICT (source_system, external_event_id, event_date) DO NOTHING
                """,
                augmented_records,
                template=(
                    "(%s, %s, %s, %s, %s, %s, %s, %s, "
                    "ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s)"
                ),
            )
        conn.commit()
        return len(augmented_records)

    def _register_sources(self, df: pd.DataFrame, conn) -> dict:
        """Register source domains and return mapping of URL to source_id."""
        # Extract unique URLs that are not null
        urls = df["SOURCEURL"].dropna().unique().tolist()

        if not urls:
            return {}

        url_to_source_id = {}

        with conn.cursor() as cursor:
            for url in urls:
                try:
                    cursor.execute(
                        "SELECT register_source(%s, %s)", (url, resolve_country(url))
                    )
                    result = cursor.fetchone()
                    if result:
                        url_to_source_id[url] = result[0]
                except Exception as e:
                    # Log but don't fail - some URLs might be malformed
                    logging.warning(f"Failed to register source for URL {url}: {e}")
                    continue

        return url_to_source_id

    def _augment_records(self, records, url_to_source_id):
        """Build augmented insert tuples from raw event records.

        Record layout from _build_event_records:
          [0]=global_event_id, [1]=event_date, [2]=cameo_code, [3]=country_code,
          [4]=url, [5]=title, [6]=lon, [7]=lat, [8]=geo_precision

        Returns a list of 13-field tuples ready for execute_values INSERT.
        """
        augmented_records = []
        for record in records:
            global_event_id = record[0]
            url = record[4]
            lat = record[7]
            lon = record[6]

            if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                logging.warning(
                    f"Skipping event {global_event_id}: "
                    f"out-of-range coordinates (lat={lat}, lon={lon})"
                )
                continue

            source_id = url_to_source_id.get(url)
            grid_cell_id = assign_grid_cell(lat, lon)
            augmented_records.append((
                "GDELT",                 # source_system
                int(global_event_id),    # gdelt_global_event_id
                str(global_event_id),    # external_event_id
                record[1],               # event_date
                record[2],               # cameo_code
                record[3],               # country_code
                record[4],               # url
                record[5],               # title
                record[6],               # lon (for ST_MakePoint)
                record[7],               # lat (for ST_MakePoint)
                source_id,
                grid_cell_id,
                record[8],               # geo_precision (GDELT ActionGeo_Type)
            ))
        return augmented_records

    def insert_to_db_returning_ids(self, df, conn) -> list[int]:
        """Like insert_to_db, but RETURNS the event_id of each inserted row.

        Rows skipped by ON CONFLICT DO NOTHING are not returned (idempotent
        replay yields an empty list on a re-run of the same batch)."""
        GDELTColumnSchema.validate(df)
        records = list(self._build_event_records(df))
        if not records:
            return []
        url_to_source_id = self._register_sources(df, conn)
        augmented_records = self._augment_records(records, url_to_source_id)
        if not augmented_records:
            return []
        ids: list[int] = []
        with conn.cursor() as cursor:
            rows = execute_values(
                cursor,
                """
                INSERT INTO events (
                    source_system, gdelt_global_event_id, external_event_id,
                    event_date, cameo_code, country_code, url, title,
                    point_geom, source_id, grid_cell_id, geo_precision
                )
                VALUES %s
                ON CONFLICT (source_system, external_event_id, event_date) DO NOTHING
                RETURNING event_id
                """,
                augmented_records,
                template=(
                    "(%s, %s, %s, %s, %s, %s, %s, %s, "
                    "ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s)"
                ),
                fetch=True,
            )
            ids = [r[0] for r in rows]
        conn.commit()
        return ids

    def run_once(self) -> pd.DataFrame:
        # Find the most recent file that actually exists (not just in the index)
        latest_url = self.fetch_latest_existing_url()
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
            lat = float(row["ActionGeo_Lat"])
            lon = float(row["ActionGeo_Long"])
            event_id = int(row["GlobalEventID"])

            # Coordinate validation: skip events with out-of-range coordinates (FR-3)
            if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                logging.warning(
                    f"Skipping event {event_id}: "
                    f"out-of-range coordinates (lat={lat}, lon={lon})"
                )
                continue

            geo_type = None
            if "ActionGeo_Type" in row and pd.notna(row["ActionGeo_Type"]):
                geo_type = int(row["ActionGeo_Type"])

            yield (
                event_id,
                pd.to_datetime(str(int(row["SQLDATE"])), format="%Y%m%d", utc=True),
                str(row["EventCode"]) if pd.notna(row["EventCode"]) else None,
                str(row["ActionGeo_CountryCode"])
                if "ActionGeo_CountryCode" in row and pd.notna(row["ActionGeo_CountryCode"])
                else None,
                str(row["SOURCEURL"]) if pd.notna(row["SOURCEURL"]) else None,
                str(row["Actor1Name"]) if pd.notna(row["Actor1Name"]) else None,
                float(row["ActionGeo_Long"]),
                float(row["ActionGeo_Lat"]),
                geo_type,
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
            "actiongeotype": "ActionGeo_Type",
        }
        rename_map = {}
        for column in df.columns:
            token = re.sub(r"[^a-zA-Z0-9]+", "", str(column)).lower()
            if token in canonical_by_token:
                rename_map[column] = canonical_by_token[token]
        return df.rename(columns=rename_map)

    def _download_latest_export(self, url: str) -> requests.Response:
        # Try the requested URL first
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
            except requests.RequestException:
                # Non-404 error, give up immediately
                raise

        # If all retries failed with 404, fallback to finding most recent existing file
        if isinstance(last_error, requests.HTTPError):
            fallback_url = self.fetch_latest_existing_url()
            print(f"Falling back to: {fallback_url}")
            return self._get_with_retry(fallback_url)

        raise last_error

    def fetch_latest_existing_url(self, max_candidates: int = 5) -> str:
        """Find the most recent export CSV that actually exists on the server.

        Uses master file list for discovery, then verifies each candidate with
        a HEAD request to avoid 404 errors.
        """
        response = self._get_with_retry(MASTER_FILELIST_URL)

        export_candidates = []
        for line in response.text.splitlines():
            parts = line.strip().split()
            if len(parts) >= 3 and parts[2].endswith(".export.CSV.zip"):
                url = parts[2]
                # Extract timestamp: .../YYYYMMDDHHMMSS.export.CSV.zip
                try:
                    ts_str = url.split("/")[-1].replace(".export.CSV.zip", "")
                    timestamp = int(ts_str)
                    export_candidates.append((timestamp, url))
                except ValueError:
                    continue

        if not export_candidates:
            raise ValueError("No export CSV URLs found in master file list")

        # Sort newest first
        export_candidates.sort(key=lambda x: x[0], reverse=True)

        # Try each candidate until we find one that actually exists
        for _, url in export_candidates[:max_candidates]:
            try:
                head_resp = requests.head(url, timeout=self.timeout_seconds)
                if head_resp.status_code == 200:
                    return url
            except requests.RequestException:
                continue

        raise RuntimeError(
            f"None of the top {max_candidates} export files are accessible"
        )


# ---------------------------------------------------------------------------
# ACLED event type mapping and source helpers (FR-1b)
# ---------------------------------------------------------------------------


def _map_acled_event_type(acled_type: str) -> str:
    """Map ACLED event types to Sentinel event_type_label.

    ACLED event categories:
    - Battles, Explosions/Remote violence → armed_conflict
    - Violence against civilians → civilian_violence
    - Protests, Riots → civil_unrest
    - Strategic developments, other → civilian_violence (default)

    Args:
        acled_type: Raw ACLED event_type string from API response.

    Returns:
        Sentinel-normalised event type label.
    """
    if not acled_type or not isinstance(acled_type, str):
        return "civilian_violence"

    acled_type_clean = acled_type.strip()
    mapping = {
        "Battles": "armed_conflict",
        "Explosions/Remote violence": "armed_conflict",
        "Violence against civilians": "civilian_violence",
        "Protests": "civil_unrest",
        "Riots": "civil_unrest",
    }
    for key, value in mapping.items():
        if key.lower() == acled_type_clean.lower():
            return value
    return "civilian_violence"


def _extract_acled_source_domain(source_str: str) -> str:
    """Derive a domain-like identifier from an ACLED source string.

    ACLED source values are typically organisation names (e.g. 'Agence
    France-Presse'), not URLs. We convert them to a URL-compatible domain
    identifier for use with the sources table.

    Args:
        source_str: ACLED source field value.

    Returns:
        Lowercase domain-compatible string.
    """
    if not source_str or not isinstance(source_str, str):
        return "acleddata.com"

    source = source_str.strip().lower()
    # Replace spaces and special chars with dots for domain-like format
    source = re.sub(r"[^a-z0-9]+", ".", source)
    return source.strip(".") or "acleddata.com"


def _register_acled_source(cursor, domain: str) -> int | None:
    """Register a source domain and return its source_id.

    Unlike GDELT sources (which pass full URLs to register_source()),
    ACLED source identifiers are pre-normalised domain strings inserted
    directly into the sources table.

    Args:
        cursor: Database cursor.
        domain: Cleaned source domain identifier.

    Returns:
        source_id of the registered source, or None on failure.
    """
    cursor.execute(
        "INSERT INTO sources (domain, country_code) VALUES (%s, %s) ON CONFLICT (domain) DO NOTHING",
        (domain, resolve_country(domain)),
    )
    cursor.execute("SELECT source_id FROM sources WHERE domain = %s", (domain,))
    result = cursor.fetchone()
    return result[0] if result else None


# ---------------------------------------------------------------------------
# ACLED Ingestor (FR-1b)
# ---------------------------------------------------------------------------


class ACLEDIngestor:
    """Fetch and ingest ACLED (Armed Conflict Location & Event Data) events.

    Authenticates against the myACLED OAuth endpoint (password grant,
    ``client_id=acled``) and calls the current ACLED API at
    ``https://acleddata.com/api/acled/read`` with a Bearer token.
    Access tokens are valid 24h; cached in Redis with in-memory fallback.

    Normalises ACLED events to Sentinel's events table schema with
    ``source_system='ACLED'`` discriminator. Uses Redis cache to respect
    ACLED's 24-hour update cadence and avoid redundant API calls.

    Rate limit: 1 request/second (academic access tier).
    """

    TOKEN_URL = "https://acleddata.com/oauth/token"
    TOKEN_CACHE_KEY = "acled:oauth:access_token"

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        cache_ttl: int | None = None,
    ):
        self.username = username or os.getenv("ACLED_EMAIL", "")
        self.password = password or os.getenv("ACLED_PASSWORD", "")
        poll_hours = int(os.getenv("SENTINEL_ACLED_POLL_HOURS", "24"))
        self.cache_ttl = (
            cache_ttl if cache_ttl is not None else poll_hours * 3600
        )
        self.base_url = "https://acleddata.com/api/acled/read"
        self.page_size = 5000  # ACLED maximum rows per request
        self.max_pages = 50  # defensive cap; API may not honour page param
        self.rate_limit = 1.0  # 1 request per second (academic tier)
        self.max_retries = 3
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

        # Redis cache (graceful fallback if unavailable)
        self._redis = None
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        if REDIS_AVAILABLE and _redis_lib is not None:
            try:
                self._redis = _redis_lib.from_url(redis_url)
                self._redis.ping()
            except Exception:
                logging.warning("Redis unavailable — ACLED cache disabled")
                self._redis = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_events(self, days: int = 7) -> pd.DataFrame:
        """Fetch ACLED events, with Redis cache.

        Checks Redis cache first; on cache miss, fetches from ACLED API
        with rate-limited pagination. Normalises to standard DataFrame
        columns expected by downstream pipeline steps.

        Args:
            days: Number of past days to fetch (default 7).

        Returns:
            DataFrame with columns: event_id_cnty, event_date, latitude,
            longitude, country_code, source_domain, event_type_label.
        """
        cache_key = f"acled:events:days_{days}"

        # 1. Check Redis cache
        if self._redis is not None:
            try:
                cached = self._redis.get(cache_key)
                if cached:
                    logging.info("ACLED cache hit for %dd window", days)
                    return pd.read_json(
                        io.StringIO(cached.decode("utf-8"))
                    )
            except Exception as exc:
                logging.warning("Redis cache read failed: %s", exc)

        # 2. Fetch from ACLED API
        df = self._fetch_from_api(days)
        logging.info("Fetched %d ACLED events for %dd window", len(df), days)

        # 3. Store in Redis cache
        if self._redis is not None and not df.empty:
            try:
                self._redis.setex(cache_key, self.cache_ttl, df.to_json())
                logging.info("ACLED data cached (TTL=%ds)", self.cache_ttl)
            except Exception as exc:
                logging.warning("Redis cache write failed: %s", exc)

        return df

    def insert_to_db(self, df: pd.DataFrame, conn) -> int:
        """Insert ACLED events into the events table.

        Uses the same upsert pattern as GDELT2Ingestor with
        ``source_system='ACLED'`` discriminator. Assigns ``grid_cell_id``
        at insert time and registers source domains.

        Args:
            df: Normalised ACLED DataFrame from ``fetch_events()``.
            conn: Database connection.

        Returns:
            Number of records submitted for insertion.
        """
        if df.empty:
            return 0

        # Step 1: Register source domains
        domain_to_source_id: dict[str, int] = {}
        if "source_domain" in df.columns:
            with conn.cursor() as cursor:
                for domain in df["source_domain"].dropna().unique():
                    if not domain:
                        continue
                    try:
                        source_id = _register_acled_source(
                            cursor, str(domain)
                        )
                        if source_id is not None:
                            domain_to_source_id[str(domain)] = source_id
                    except Exception as exc:
                        logging.warning(
                            "Failed to register ACLED source %s: %s",
                            domain,
                            exc,
                        )

        # Step 2: Build insert records
        records: list[tuple] = []
        for _, row in df.iterrows():
            try:
                lat = float(row.get("latitude", 0))
                lon = float(row.get("longitude", 0))

                if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                    logging.warning(
                        "Skipping ACLED event %s: out-of-range coordinates",
                        row.get("event_id_cnty"),
                    )
                    continue

                event_id = str(row.get("event_id_cnty", ""))
                grid_cell_id = assign_grid_cell(lat, lon)

                source_domain = str(
                    row.get("source_domain", "acleddata.com")
                )
                source_id = domain_to_source_id.get(source_domain)

                # Parse event_date — ACLED uses "YYYY-MM-DD" format
                event_date = row.get("event_date")
                if isinstance(event_date, str):
                    try:
                        event_date = datetime.strptime(
                            event_date, "%Y-%m-%d"
                        )
                    except ValueError:
                        event_date = None

                event_type_label = row.get(
                    "event_type_label", "civilian_violence"
                )
                location = row.get("location", "")
                records.append((
                    "ACLED",                                 # source_system
                    event_id,                                # external_event_id
                    event_date,                              # event_date
                    str(event_type_label),                   # cameo_code
                    row.get("country_code"),                 # country_code
                    str(source_domain),                      # url
                    f"{event_type_label}: {location}",        # title
                    lon,                                     # lon
                    lat,                                     # lat
                    source_id,                               # source_id
                    grid_cell_id,                            # grid_cell_id
                    4,                                       # geo_precision — ACLED geocodes to named locations
                ))
            except Exception as exc:
                logging.warning(
                    "Skipping ACLED event %s: %s",
                    row.get("event_id_cnty"),
                    exc,
                )
                continue

        if not records:
            return 0

        # Step 3: Batch insert with idempotent upsert
        with conn.cursor() as cursor:
            execute_values(
                cursor,
                """
                INSERT INTO events (
                    source_system, external_event_id, event_date,
                    cameo_code, country_code, url, title,
                    point_geom, source_id, grid_cell_id, geo_precision
                )
                VALUES %s
                ON CONFLICT (source_system, external_event_id, event_date) DO NOTHING
                """,
                records,
                template=(
                    "(%s, %s, %s, %s, %s, %s, %s, "
                    "ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s)"
                ),
            )
        conn.commit()
        logging.info(
            "Submitted %d ACLED events for insertion", len(records)
        )
        return len(records)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _request_token(self) -> tuple[str, int]:
        """Request a new access token via OAuth password grant.

        Returns:
            Tuple of (access_token, expires_in_seconds).
        """
        response = requests.post(
            self.TOKEN_URL,
            data={
                "username": self.username,
                "password": self.password,
                "grant_type": "password",
                "client_id": "acled",
                "scope": "authenticated",
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        return payload["access_token"], int(payload.get("expires_in", 86400))

    def _get_access_token(self, force_refresh: bool = False) -> str:
        """Return a valid Bearer token, fetching a new one if needed.

        Checks in-memory expiry first, then Redis, then performs a
        password grant. A 60s safety margin avoids using tokens at the
        edge of their 24h validity window.
        """
        now = time.time()
        if (
            not force_refresh
            and self._access_token
            and now < self._token_expires_at
        ):
            return self._access_token

        if not force_refresh and self._redis is not None:
            try:
                cached = self._redis.get(self.TOKEN_CACHE_KEY)
                if cached:
                    ttl = int(self._redis.ttl(self.TOKEN_CACHE_KEY) or 0)
                    if ttl > 0:
                        self._access_token = cached.decode("utf-8")
                        self._token_expires_at = now + ttl
                        return self._access_token
            except Exception as exc:
                logging.warning("Redis token cache read failed: %s", exc)

        token, expires_in = self._request_token()
        self._access_token = token
        self._token_expires_at = now + max(expires_in - 60, 60)
        if self._redis is not None:
            try:
                self._redis.setex(
                    self.TOKEN_CACHE_KEY, max(expires_in - 60, 60), token
                )
            except Exception as exc:
                logging.warning("Redis token cache write failed: %s", exc)
        return token

    def _fetch_from_api(self, days: int) -> pd.DataFrame:
        """Fetch events from ACLED API with retry and pagination."""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)

        params: dict = {
            "event_date": (
                f"{start_date.strftime('%Y-%m-%d')}"
                f"|{end_date.strftime('%Y-%m-%d')}"
            ),
            "event_date_where": "BETWEEN",
            "limit": self.page_size,
        }

        all_events: list[dict] = []
        page = 1
        seen_first_id: str | None = None

        while page <= self.max_pages:
            page_params = {**params, "page": page}
            data = self._fetch_page_with_retry(page_params)
            if data is None:
                logging.error(
                    "ACLED API page %d failed after %d retries",
                    page,
                    self.max_retries,
                )
                break

            if isinstance(data, dict):
                events_on_page = data.get("data", [])
            else:
                events_on_page = data
            if not events_on_page:
                break

            # Detect API silently ignoring page param (returning same data)
            if events_on_page:
                first_id = events_on_page[0].get("event_id_cnty", "")
                if seen_first_id is not None and first_id == seen_first_id:
                    logging.warning(
                        "ACLED page %d returned same data as page %d — "
                        "breaking pagination loop",
                        page,
                        page - 1,
                    )
                    break
                seen_first_id = first_id

            all_events.extend(events_on_page)

            if len(events_on_page) < self.page_size:
                break

            page += 1
            time.sleep(self.rate_limit)

        if page > self.max_pages:
            logging.warning(
                "ACLED pagination hit cap of %d pages — response may be truncated",
                self.max_pages,
            )

        if not all_events:
            return pd.DataFrame()

        df = pd.DataFrame(all_events)
        return self._normalize_acled_columns(df)

    def _fetch_page_with_retry(self, params: dict) -> dict | None:
        """Fetch a single ACLED API page with exponential backoff retry.

        On HTTP 401 the cached token is discarded and a fresh password
        grant is performed before the next attempt.

        Returns parsed JSON dict on success, ``None`` after exhausting retries.
        """
        for attempt in range(1, self.max_retries + 1):
            try:
                token = self._get_access_token()
            except requests.RequestException as exc:
                logging.error(
                    "ACLED token acquisition failed — check ACLED_EMAIL/"
                    "ACLED_PASSWORD: %s",
                    exc,
                )
                return None

            try:
                response = requests.get(
                    self.base_url,
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=30,
                )
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 401:
                    backoff = 1
                    logging.warning(
                        "ACLED token rejected (401), re-auth %d/%d",
                        attempt,
                        self.max_retries,
                    )
                    self._get_access_token(force_refresh=True)
                elif response.status_code == 429:
                    backoff = 2 ** attempt
                    logging.warning(
                        "ACLED rate limit (429), retry %d/%d in %ds",
                        attempt,
                        self.max_retries,
                        backoff,
                    )
                else:
                    backoff = 2 ** attempt
                    logging.warning(
                        "ACLED API returned %d, retry %d/%d in %ds",
                        response.status_code,
                        attempt,
                        self.max_retries,
                        backoff,
                    )
                time.sleep(backoff)
            except requests.RequestException as exc:
                backoff = 2 ** attempt
                logging.warning(
                    "ACLED request error: %s, retry %d/%d in %ds",
                    exc,
                    attempt,
                    self.max_retries,
                    backoff,
                )
                time.sleep(backoff)

        return None

    @staticmethod
    def _normalize_acled_columns(df: pd.DataFrame) -> pd.DataFrame:
        """Normalise ACLED API response columns to Sentinel standard.

        Handles column name variations and adds derived columns:
        - ``event_type_label``: mapped from ACLED ``event_type``
        - ``source_domain``: derived from ``source`` field
        """
        if df.empty:
            return df

        # Map event type labels
        if "event_type" in df.columns:
            df["event_type_label"] = df["event_type"].apply(
                _map_acled_event_type
            )
        else:
            df["event_type_label"] = "civilian_violence"

        # Derive source domain from source field
        if "source" in df.columns:
            df["source_domain"] = df["source"].apply(
                _extract_acled_source_domain
            )
        else:
            df["source_domain"] = "acleddata.com"

        # Ensure country_code is present
        if "country" in df.columns and "country_code" not in df.columns:
            df["country_code"] = df["country"]
        elif "country_code" not in df.columns:
            df["country_code"] = None

        return df


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


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
    parser.add_argument(
        "--fetch-acled",
        action="store_true",
        help="Fetch and ingest ACLED events (FR-1b)",
    )
    parser.add_argument(
        "--acled-days",
        type=int,
        default=7,
        help="Number of days to fetch from ACLED API (default: 7)",
    )
    return parser


def main_acled(args: argparse.Namespace) -> int:
    """Run ACLED ingestion (FR-1b)."""
    username = os.getenv("ACLED_EMAIL", "")
    password = os.getenv("ACLED_PASSWORD", "")
    if not username or not password:
        print(
            "Warning: ACLED_EMAIL or ACLED_PASSWORD not set. "
            "Skipping ACLED fetch."
        )
        return 0

    ingestor = ACLEDIngestor(username=username, password=password)
    print(f"Fetching ACLED events for last {args.acled_days} days...")
    df = ingestor.fetch_events(days=args.acled_days)
    print(f"Fetched {len(df)} ACLED events")

    if not df.empty and args.insert_db:
        conn, pool = get_pooled_connection()
        try:
            inserted = ingestor.insert_to_db(df, conn)
            print(f"Inserted {inserted} ACLED events into events table")
        finally:
            pool.return_connection(conn)

    csv_path = f"acled_events_{args.acled_days}d.csv"
    df.to_csv(csv_path, index=False)
    print(f"Saved ACLED events to {csv_path}")
    return 0


def main() -> int:
    args = _build_parser().parse_args()
    ingestor = GDELT2Ingestor()
    military_df = ingestor.run_once()
    military_df.to_csv(args.output_csv, index=False)
    print(f"Saved {len(military_df)} military events to {args.output_csv}")
    if args.insert_db:
        conn, pool = get_pooled_connection()
        try:
            inserted = ingestor.insert_to_db(military_df, conn)
            print(f"Inserted {inserted} records into events table")
        finally:
            pool.return_connection(conn)

    if args.fetch_acled:
        return main_acled(args)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
