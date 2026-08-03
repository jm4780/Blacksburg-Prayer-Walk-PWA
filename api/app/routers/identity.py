"""Lightweight identity (§5).

First name, last name, email. A returning participant is matched on the normalized
email and handed a fresh token — no password, no verification email, no account
recovery flow. The scope is a church prayer walk.

Re-registering with a known email **rotates** the token. That is the honest behaviour
for a system with no verification: the alternative is refusing, which locks a walker
out of their own history when they clear their browser, and the risk it creates —
someone who knows your email can take over your walk history — is bounded by the fact
that a walk history contains no personal data beyond a name.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_participant
from ..models import Participant
from ..schemas import ParticipantOut, RegisterIn
from ..config import settings
from ..security import hash_token, new_token, normalize_email, valid_email

router = APIRouter(prefix="/api/identity", tags=["identity"])


@router.post("/register", response_model=ParticipantOut)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if not valid_email(body.email):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "that does not look like an email address")
    # Invite-restricted pilots (BPW_ACCESS_MODE=invite). Still no password and no
    # verification: the code gates who can sign up, not how identity works.
    cfg = settings()
    if cfg.access_mode == "invite" and cfg.invite_code:
        if (body.invite_code or "").strip() != cfg.invite_code:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "this pilot needs an invite code")
    key = normalize_email(body.email)
    token = new_token()

    p = db.execute(select(Participant)
                   .where(Participant.email_normalized == key)).scalar_one_or_none()
    returning = p is not None
    if p is None:
        p = Participant(first_name=body.first_name.strip(),
                        last_name=body.last_name.strip(),
                        email=body.email.strip(), email_normalized=key,
                        token_hash=hash_token(token))
        db.add(p)
    else:
        p.first_name = body.first_name.strip() or p.first_name
        p.last_name = body.last_name.strip() or p.last_name
        p.token_hash = hash_token(token)
    db.commit()
    db.refresh(p)

    return ParticipantOut(id=p.id, first_name=p.first_name, last_name=p.last_name,
                          email=p.email, is_admin=p.is_admin, token=token,
                          returning=returning)


@router.get("/me", response_model=ParticipantOut)
def me(p: Participant = Depends(current_participant)):
    # No token in the response. The browser already has it; echoing it back only
    # widens where it can leak (logs, caches, screenshots).
    return ParticipantOut(id=p.id, first_name=p.first_name, last_name=p.last_name,
                          email=p.email, is_admin=p.is_admin, returning=True)
