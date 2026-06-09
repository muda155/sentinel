"""Pydantic v2 response models matching Section 6.3."""
from __future__ import annotations

from pydantic import BaseModel


class Hotspot(BaseModel):
    hotspot_id: int
    lat: float
    lon: float
    conf_score: float
    convergence_score: float
    alert_level: str
    event_count: int


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


class StreamEvent(BaseModel):
    hotspot_id: int
    lat: float
    lon: float
    conf_score: float
    convergence_score: float
    alert_level: str
