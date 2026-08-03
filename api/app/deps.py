"""Request dependencies: who is calling, and may they see geometry."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import Participant
from .security import hash_token


def _token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None


def current_participant(authorization: str | None = Header(default=None),
                        db: Session = Depends(get_db)) -> Participant:
    tok = _token(authorization)
    if not tok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    p = db.execute(select(Participant)
                   .where(Participant.token_hash == hash_token(tok))).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown token")
    p.last_seen_at = datetime.now(timezone.utc)
    db.commit()
    return p


def optional_participant(authorization: str | None = Header(default=None),
                         db: Session = Depends(get_db)) -> Participant | None:
    tok = _token(authorization)
    if not tok:
        return None
    return db.execute(select(Participant)
                      .where(Participant.token_hash == hash_token(tok))).scalar_one_or_none()


def require_admin(p: Participant = Depends(current_participant)) -> Participant:
    if not p.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "administrator access required")
    return p


def may_see_geometry(p: Participant | None = Depends(optional_participant)) -> bool:
    """Gate on source-derived geometry.

    Network geometry is derived from Town of Blacksburg GIS data, and no town dataset
    grants any reuse right — see docs/05-licensing-status.md, release gate G1. Serving
    it to anonymous callers is publication. Serving it to a signed-up pilot participant
    is not, on the same footing as showing someone a map in a meeting.

    So: authenticated callers always may. Anonymous callers may only when an operator
    has explicitly set BPW_PUBLIC_GEOMETRY_ENABLED, which the startup check flags
    loudly.
    """
    if p is not None:
        return True
    return settings().public_geometry_enabled


def geometry_or_403(allowed: bool = Depends(may_see_geometry)) -> bool:
    if not allowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Map geometry is derived from Town of Blacksburg GIS data whose reuse "
            "terms are unresolved (licensing gate G1). Sign in to view it, or set "
            "BPW_PUBLIC_GEOMETRY_ENABLED once the licensing question is settled.")
    return True
