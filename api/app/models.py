"""Persistence model.

Three privacy rules are enforced by the *shape* of these tables, not by convention:

  1. No residential address, household coordinate or household identifier is stored
     anywhere. Households are only ever counted, via the segment they hang off in the
     canonical network, and that count is computed at read time.

  2. No participant location is stored. A route request records the graph node its
     start snapped to — a public street intersection — never the browser's GPS fix.
     The fix is used once, in memory, to pick that node, and then discarded.

  3. The browser's token is stored as a hash. A stolen database yields no working
     tokens.

Every stored route also records the network id and engine version it was computed
under, so a route can always be traced to the network that produced it.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Participant(Base):
    """A walker. Deliberately minimal: name and email, nothing else.

    `email_normalized` is the identity key — lowercased and trimmed — so the same
    person coming back on a new phone is matched rather than duplicated.
    """
    __tablename__ = "participants"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(320))
    email_normalized: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    walks: Mapped[list["Walk"]] = relationship(back_populates="participant")


class RouteRequest(Base):
    """One 'generate a walk' action, with all variants it produced.

    Stored whole because §11 asks for reproducibility: the seed plus the completion
    state at request time plus the network id is enough to regenerate the identical
    set of variants.
    """
    __tablename__ = "route_requests"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    participant_id: Mapped[str] = mapped_column(ForeignKey("participants.id"), index=True)
    network_id: Mapped[str] = mapped_column(String(64))
    engine_version: Mapped[str] = mapped_column(String(16))
    # The snapped graph node. NOT the browser's GPS fix — see the module docstring.
    start_node: Mapped[int] = mapped_column(Integer)
    start_source: Mapped[str] = mapped_column(String(16))     # DEVICE_LOCATION | MAP
    seed: Mapped[int] = mapped_column(Integer)
    component_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    variants: Mapped[dict] = mapped_column(JSON)              # full per-variant payload
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                default=utcnow, index=True)


class Walk(Base):
    """A route a participant selected. PREVIEW -> ACTIVE -> COMPLETED | DISCARDED."""
    __tablename__ = "walks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    participant_id: Mapped[str] = mapped_column(ForeignKey("participants.id"), index=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("route_requests.id"), index=True)
    network_id: Mapped[str] = mapped_column(String(64))
    engine_version: Mapped[str] = mapped_column(String(16))

    status: Mapped[str] = mapped_column(String(16), default="PREVIEW", index=True)
    band: Mapped[str] = mapped_column(String(16))
    target_miles: Mapped[float] = mapped_column(Float)
    distance_miles: Mapped[float] = mapped_column(Float)
    estimated_minutes: Mapped[int] = mapped_column(Integer)

    # The plan as generated. Never rewritten — §14 requires the original planned route
    # to survive unchanged in the audit record even when the walker reports something
    # different. What actually got walked lives in `completions`.
    planned_segment_ids: Mapped[list] = mapped_column(JSON)
    planned_required_ids: Mapped[list] = mapped_column(JSON)
    score_components: Mapped[dict] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                        nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                         nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(24), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    participant: Mapped[Participant] = relationship(back_populates="walks")


class Reservation(Base):
    """A soft hold on a segment. Expires on its own; never a lock.

    §12: reservations are a *scoring penalty*, not a graph edit. Two walkers who start
    near each other both get routes; the second is nudged away from the first's
    segments rather than blocked from them.
    """
    __tablename__ = "reservations"
    __table_args__ = (
        UniqueConstraint("walk_id", "segment_id", name="uq_reservation_walk_segment"),
        Index("ix_reservation_segment_expiry", "segment_id", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    walk_id: Mapped[str] = mapped_column(ForeignKey("walks.id"), index=True)
    participant_id: Mapped[str] = mapped_column(ForeignKey("participants.id"), index=True)
    segment_id: Mapped[str] = mapped_column(String(16), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                         nullable=True)


class Completion(Base):
    """One segment, prayed for, once, by one walk.

    The unique constraint is the whole idempotency mechanism: submitting the same walk
    twice inserts nothing the second time. Segments completed by different walks are
    separate rows — the town-wide view counts distinct segment ids.
    """
    __tablename__ = "completions"
    __table_args__ = (
        UniqueConstraint("walk_id", "segment_id", name="uq_completion_walk_segment"),
        Index("ix_completion_segment", "segment_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    walk_id: Mapped[str] = mapped_column(ForeignKey("walks.id"), index=True)
    participant_id: Mapped[str] = mapped_column(ForeignKey("participants.id"), index=True)
    segment_id: Mapped[str] = mapped_column(String(16))
    network_id: Mapped[str] = mapped_column(String(64))
    # AS_PLANNED | PARTIAL | DIFFERENT_ROUTE — how the walker reported it (§14).
    source: Mapped[str] = mapped_column(String(24))
    # True when the credit came from walking a parallel campus walkway rather than the
    # canonical side (network v1.2, spec §4.2). Kept so a coverage claim is traceable.
    via_alternative: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                   default=utcnow, index=True)


class AdminAction(Base):
    """Audit trail for administrative changes. Reversing a completion is a real edit
    to the town-wide number and has to leave a trace."""
    __tablename__ = "admin_actions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    actor_id: Mapped[str] = mapped_column(ForeignKey("participants.id"), index=True)
    action: Mapped[str] = mapped_column(String(48))
    target: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow, index=True)
