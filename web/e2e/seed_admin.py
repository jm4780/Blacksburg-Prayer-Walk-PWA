"""Mint an administrator token for e2e/admin.mjs.

There is deliberately no HTTP route that grants administrator rights — an application
that can promote itself is one request away from anyone else doing so — so the e2e
harness reaches into the database, exactly as an operator would.

Run this against the same BPW_DATABASE_URL the server will use, *before* starting it:

    BPW_TOKEN_PEPPER=... BPW_DATABASE_URL=sqlite:///./bpw-e2e.db \\
      python web/e2e/seed_admin.py
"""
from __future__ import annotations

import secrets
import sys

from sqlalchemy import select

sys.path.insert(0, __file__.rsplit("/web/", 1)[0])

from api.app.db import SessionLocal, init_db          # noqa: E402
from api.app.models import Participant                # noqa: E402
from api.app.security import hash_token               # noqa: E402

EMAIL = "admin-e2e@example.com"

init_db()
token = secrets.token_urlsafe(32)
with SessionLocal() as db:
    p = db.execute(select(Participant)
                   .where(Participant.email_normalized == EMAIL)).scalar_one_or_none()
    if p is None:
        p = Participant(first_name="Admin", last_name="User", email=EMAIL,
                        email_normalized=EMAIL)
        db.add(p)
    p.is_admin = True
    p.token_hash = hash_token(token)
    db.commit()
print(token)
