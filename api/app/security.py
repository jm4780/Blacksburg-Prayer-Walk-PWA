"""Identity primitives: opaque tokens, token hashing, email normalization.

§5 asks for lightweight identity, and §18 requires the browser to hold an *opaque
token* rather than raw participant identity. So:

  - the browser stores a 256-bit random token and nothing else;
  - the server stores only sha256(pepper + token), so the database cannot be replayed;
  - the participant record is looked up by that hash on every request.

There is no password and no session cookie. This is a church prayer-walk sign-up, not
an account system — the threat model is "someone else's phone", not credential theft,
and the honest way to handle that is a bearer token the user can clear.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

from .config import settings

TOKEN_BYTES = 32


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    pepper = settings().token_pepper.encode()
    return hmac.new(pepper, token.encode(), hashlib.sha256).hexdigest()


def normalize_email(email: str) -> str:
    """Identity key for matching a returning participant.

    Lowercase and trim only. Deliberately NOT stripping dots or +tags: those rules are
    provider-specific, and collapsing alice+walks@ into alice@ would merge two people
    who believe they are separate. Under-matching creates a duplicate record; the
    over-matching alternative attributes one person's walks to another.
    """
    return email.strip().lower()


def valid_email(email: str) -> bool:
    e = email.strip()
    if len(e) < 3 or len(e) > 320 or e.count("@") != 1:
        return False
    local, _, domain = e.partition("@")
    return bool(local) and "." in domain and not domain.startswith(".") \
        and not domain.endswith(".") and " " not in e
