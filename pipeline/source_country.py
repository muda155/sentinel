"""Resolve a news domain to an ISO-A3 country code.

Two layers: a curated map of major generic-TLD outlets (.com/.net/.org that
carry no country signal in the TLD), then a ccTLD fallback. Unknown domains
return None and are excluded from geopolitical-diversity scoring (FR-8)."""

from __future__ import annotations

# Curated major outlets whose TLD does not encode a country.
_CURATED: dict[str, str] = {
    "reuters.com": "GBR",
    "theguardian.com": "GBR",
    "ft.com": "GBR",
    "dailymail.com": "GBR",
    "bbc.com": "GBR",
    "cnn.com": "USA",
    "nytimes.com": "USA",
    "washingtonpost.com": "USA",
    "apnews.com": "USA",
    "bloomberg.com": "USA",
    "wsj.com": "USA",
    "foxnews.com": "USA",
    "nbcnews.com": "USA",
    "aljazeera.com": "QAT",
    "aljazeera.net": "QAT",
    "dw.com": "DEU",
    "spiegel.de": "DEU",
    "france24.com": "FRA",
    "rt.com": "RUS",
    "xinhuanet.com": "CHN",
    "globaltimes.cn": "CHN",
    "scmp.com": "HKG",
    "timesofindia.com": "IND",
    "thehindu.com": "IND",
    "jpost.com": "ISR",
    "haaretz.com": "ISR",
    "kyivindependent.com": "UKR",
}

# Country-code TLD -> ISO-A3.
_CCTLD: dict[str, str] = {
    "uk": "GBR", "ru": "RUS", "fr": "FRA", "de": "DEU", "cn": "CHN",
    "in": "IND", "il": "ISR", "ua": "UKR", "jp": "JPN", "au": "AUS",
    "ca": "CAN", "ng": "NGA", "qa": "QAT", "ir": "IRN", "tr": "TUR",
    "sa": "SAU", "eg": "EGY", "pk": "PAK", "kr": "KOR", "es": "ESP",
    "it": "ITA", "pl": "POL", "se": "SWE", "no": "NOR", "nl": "NLD",
    "br": "BRA", "mx": "MEX", "za": "ZAF", "ie": "IRL", "ch": "CHE",
}

_GENERIC_TLDS = {"com", "net", "org", "info", "biz", "gov", "edu", "int", "io", "co"}


def _host(value: str) -> str:
    v = value.strip().lower()
    if "://" in v:
        v = v.split("://", 1)[1]
    v = v.split("/", 1)[0]
    if v.startswith("www."):
        v = v[4:]
    return v


def resolve_country(value: str | None) -> str | None:
    if not value or not str(value).strip():
        return None
    host = _host(str(value))
    if not host:
        return None
    if host in _CURATED:
        return _CURATED[host]
    tld = host.rsplit(".", 1)[-1]
    if tld in _GENERIC_TLDS:
        return None
    return _CCTLD.get(tld)
