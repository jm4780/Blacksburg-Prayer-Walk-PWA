"""Request and response shapes.

Response models are deliberately explicit rather than passthrough dicts: the privacy
tests in tests/test_privacy.py assert on what these can contain, and a permissive
`dict` response would make that assertion meaningless.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------- identity
class RegisterIn(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=320)
    # Only consulted when BPW_ACCESS_MODE=invite.
    invite_code: str | None = Field(default=None, max_length=120)


class ParticipantOut(BaseModel):
    """What the browser learns about itself.

    The token is returned exactly once, at registration. Everything after that is
    `Authorization: Bearer <token>`; the server never sends it back again.
    """
    id: str
    first_name: str
    last_name: str
    email: str
    is_admin: bool
    token: str | None = None
    returning: bool = False


# ---------------------------------------------------------------------- routing
class RouteRequestIn(BaseModel):
    # Exactly one of these two ways of saying where to start (§6).
    lat: float | None = None
    lon: float | None = None
    start_source: Literal["DEVICE_LOCATION", "MAP"] = "DEVICE_LOCATION"
    # Optional: narrow the response to one size. Default returns all of them (§7).
    requested_family: str | None = None
    # Optional: reproduce an earlier request byte-for-byte.
    seed: int | None = None


class VariantOut(BaseModel):
    band: str
    target_miles: float
    available: bool
    state: str
    reason: str
    distance_miles: float | None
    estimated_minutes: int | None
    new_required_miles: float | None
    repeated_miles: float | None
    efficiency: float | None
    households: int | None
    walk_quality: float | None
    dead_end_returns_miles: float | None
    closing_leg_miles: float | None
    segment_count: int | None
    required_segment_count: int | None
    nests_within_shorter: bool | None
    component: dict | None
    score_components: dict | None
    campus_credited_miles: float | None
    suggested_band: str | None
    nearest_incomplete_miles: float | None
    segment_ids: list[str]
    required_segment_ids: list[str]
    connector_segment_ids: list[str]
    start_point: list[float] | None
    end_point: list[float] | None
    route_score: float | None
    seed: int
    network_version: str
    engine_version: str
    geometry: dict | None


class RouteResponseOut(BaseModel):
    request_id: str
    network_id: str
    network_version: str
    engine_version: str
    seed: int
    state: str
    coverage_area_id: str | None
    completion_state_version: str
    component: dict | None
    available_bands: list[str]
    variants: list[VariantOut]


# ------------------------------------------------------------------------ walks
class SelectWalkIn(BaseModel):
    request_id: str
    band: str


class WalkOut(BaseModel):
    id: str
    status: str
    band: str
    target_miles: float
    distance_miles: float
    estimated_minutes: int
    network_id: str
    engine_version: str
    required_segment_count: int
    planned_required_ids: list[str] = []
    households: int | None = None
    start_point: list[float] | None = None
    created_at: str
    started_at: str | None = None
    resolved_at: str | None = None
    outcome: str | None = None
    geometry: dict | None = None
    directions: list[dict] | None = None


class CompleteWalkIn(BaseModel):
    outcome: Literal["AS_PLANNED", "EDITED", "DID_NOT_COMPLETE"]
    segment_ids: list[str] | None = None
    note: str | None = Field(default=None, max_length=2000)


# --------------------------------------------------------------------- progress
class MetricsOut(BaseModel):
    network_id: str
    network_version: str
    percent_prayed_for: dict
    total_miles_walked: dict
    estimated_households_prayed_for: dict
    required_segments_total: int
    required_segments_complete: int
    completed_walks: int
    distinct_walkers: int
    mileage_breakdown: dict


class HealthOut(BaseModel):
    status: str
    tier: str
    network_id: str
    network_version: str
    engine_version: str
    warnings: list[str]
    public_geometry_enabled: bool
    licensing_gate: dict[str, Any]
    # Which build is running, and whether the data on disk matches the code. See
    # api/app/version.py — these exist so a stale preview can be diagnosed from the
    # app rather than guessed at.
    build: dict[str, Any]
    network_data: dict[str, Any]


# -------------------------------------------------------------------- feedback
class FeedbackIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    easy_to_follow: bool | None = None
    time_felt_accurate: bool | None = None
    had_bad_connection: bool = False
    bad_connection_detail: str | None = Field(default=None, max_length=2000)
    completed_as_planned: bool | None = None
    comment: str | None = Field(default=None, max_length=2000)
    submitted_from: Literal["ACTIVE_WALK", "AFTER_SUBMISSION"] = "AFTER_SUBMISSION"


class FeedbackOut(BaseModel):
    id: str
    walk_id: str
    rating: int
    reproduce: dict
    updated: bool
