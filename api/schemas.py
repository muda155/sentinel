"""Pydantic v2 response models matching Section 6.3."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class Hotspot(BaseModel):
    hotspot_id: int
    lat: float
    lon: float
    conf_score: float
    convergence_score: float
    alert_level: str
    event_count: int
    name: str | None = None


class HotspotSummary(BaseModel):
    summary: str
    conflict_detected: bool
    sources_cited: list[str]
    conf_score: float
    convergence_score: float


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


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
    trust_tier: str | None = None
    trust_score: float
    citation_index: int | None = None


class StreamEvent(BaseModel):
    hotspot_id: int
    lat: float
    lon: float
    conf_score: float
    convergence_score: float
    alert_level: str
