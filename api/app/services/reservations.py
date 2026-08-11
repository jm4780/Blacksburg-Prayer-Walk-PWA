"""Soft reservations (§12).

A reservation says "someone is probably walking this right now". It is never a lock:

  - created when a walk is previewed, short-lived;
  - extended when the walk is started;
  - auto-expiring, so an abandoned phone releases its hold without anyone doing
    anything;
  - released on submit or discard;
  - applied to the router as a prize multiplier, not by removing edges.

That last point is the one that matters. Removing reserved edges from the graph would
let one walker in a small neighbourhood make it unroutable for everybody else. Damping
the prize means the second walker is steered elsewhere if there is an elsewhere, and
still gets a route if there is not.

No reservation is ever exposed with the holder's identity. The public and per-request
views say "held", never by whom.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Reservation, Walk


def _now() -> datetime:
    return datetime.now(timezone.utc)


def reserve(db: Session, walk: Walk, segment_ids, minutes: int | None = None) -> int:
    """Hold the walk's required segments. Idempotent per (walk, segment)."""
    mins = minutes if minutes is not None else settings().reservation_preview_minutes
    expires = _now() + timedelta(minutes=mins)
    existing = set(db.execute(
        select(Reservation.segment_id).where(Reservation.walk_id == walk.id)
    ).scalars().all())
    added = 0
    for sid in segment_ids:
        if sid in existing:
            continue
        db.add(Reservation(walk_id=walk.id, participant_id=walk.participant_id,
                           segment_id=sid, expires_at=expires))
        added += 1
    # Renew the ones already held, so re-previewing does not let a hold lapse.
    db.execute(update(Reservation)
               .where(Reservation.walk_id == walk.id,
                      Reservation.released_at.is_(None))
               .values(expires_at=expires))
    db.commit()
    return added


def extend(db: Session, walk: Walk) -> None:
    """Starting a walk turns a preview hold into a walking-length hold."""
    expires = _now() + timedelta(minutes=settings().reservation_active_minutes)
    db.execute(update(Reservation)
               .where(Reservation.walk_id == walk.id,
                      Reservation.released_at.is_(None))
               .values(expires_at=expires))
    db.commit()


def release(db: Session, walk: Walk, commit: bool = True) -> int:
    """Let the walk's holds go.

    `commit=False` leaves the release inside the caller's open transaction. That is
    for the one case where releasing a walk's holds and creating the walk that
    replaces it have to land together or not at all: committing in the middle would
    drop the row lock the caller is holding and reopen the race it is closing.
    """
    now = _now()
    res = db.execute(update(Reservation)
                     .where(Reservation.walk_id == walk.id,
                            Reservation.released_at.is_(None))
                     .values(released_at=now))
    if commit:
        db.commit()
    return res.rowcount or 0


def purge_expired(db: Session) -> int:
    """Mark lapsed holds released. Not required for correctness — every read filters
    on expires_at — but it keeps the admin view honest about what is actually held."""
    now = _now()
    res = db.execute(update(Reservation)
                     .where(Reservation.released_at.is_(None),
                            Reservation.expires_at <= now)
                     .values(released_at=now))
    db.commit()
    return res.rowcount or 0


def held_segment_ids(db: Session, exclude_walk: str | None = None) -> set[str]:
    q = select(Reservation.segment_id).where(Reservation.released_at.is_(None),
                                             Reservation.expires_at > _now())
    if exclude_walk:
        q = q.where(Reservation.walk_id != exclude_walk)
    return set(db.execute(q).scalars().all())
