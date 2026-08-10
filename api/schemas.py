"""Pydantic v2 response models matching Section 6.3."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class Hotspot(BaseModel):
    hotspot_id: int
    lat: float
    lon: float
    conf_score: float
    # NULL means "never scored" (never went through grid-cell convergence);
    # a COALESCE to 0 here would be indistinguishable from a genuine zero and
    # the detail panel would draw a hollow bar instead of "not yet scored".
    convergence_score: float | None = None
    alert_level: str
    event_count: int
    consistency_score: float | None = None
    source_density: float | None = None
    geopolitical_diversity: float | None = None
    convergence_types: int = 0
    convergence_events: int = 0
    name: str | None = None
    start_window: datetime | None = None
    end_window: datetime | None = None
    created_at: datetime | None = None


class HotspotSummary(BaseModel):
    summary: str
    conflict_detected: bool
    sources_cited: list[str]
    conf_score: float
    # NULL = never scored, matching the Hotspot payload — the summary endpoint
    # must not flatten a never-scored hotspot to 0 while /hotspots reports null.
    convergence_score: float | None = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


class UserRow(BaseModel):
    user_id: int
    username: str
    role: str
    created_at: datetime | None = None


class Source(BaseModel):
    source_id: int
    domain: str
    trust_tier: int | None = None
    country_code: str | None = None
    country_name: str | None = None


class HotspotEvent(BaseModel):
    event_id: int
    title: str | None = None
    url: str | None = None
    domain: str
    source_system: str
    event_type_label: str
    event_date: datetime
    goldstein_scale: float | None = None
    avg_tone: float | None = None
    num_sources: int | None = None
    fatalities: int | None = None
    duplicate_count: int = 1
    trust_tier: int | None = None
    trust_score: float
    country_code: str | None = None
    citation_index: int | None = None


class SearchEvent(BaseModel):
    event_id: int
    title: str | None = None
    url: str | None = None
    domain: str
    event_date: datetime
    report_count: int = 1
    hotspot: Hotspot


class SearchSource(BaseModel):
    source_id: int
    domain: str
    trust_tier: int | None = None
    hotspots: list[Hotspot]


class SearchResults(BaseModel):
    hotspots: list[Hotspot]
    events: list[SearchEvent]
    sources: list[SearchSource]


class ClaimEvidence(BaseModel):
    event_id: int
    citation_index: int | None = None
    relation: str
    probability: float | None = None
    domain: str


class Claim(BaseModel):
    claim_id: int
    claim_text: str
    status: str
    consensus_weight: float | None = None
    origin_domains: list[str] | None = None
    evidence: list[ClaimEvidence]


class HotspotClaims(BaseModel):
    claims: list[Claim]
    insufficient_sources: bool
