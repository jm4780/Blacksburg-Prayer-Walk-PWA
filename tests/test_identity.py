"""Identity matrix (§20).

Covers: new participant, returning participant matched on normalized email, token
opacity, token rotation, unknown token, missing token, malformed email.
"""
from __future__ import annotations

import pytest

from .conftest import auth, register


def test_new_participant_gets_a_token(client):
    p = register(client, "ada@example.com", "Ada", "Lovelace")
    assert p["returning"] is False
    assert p["token"] and len(p["token"]) >= 32
    assert p["id"] != p["token"], "the id must not be derivable from the token"


@pytest.mark.parametrize("variant", [
    "Ada@Example.com", "  ada@example.com  ", "ADA@EXAMPLE.COM",
])
def test_returning_participant_matched_on_normalized_email(client, variant):
    first = register(client, "ada@example.com", "Ada", "Lovelace")
    again = register(client, variant, "Ada", "Lovelace")
    assert again["returning"] is True
    assert again["id"] == first["id"], "same person, one record"


def test_plus_tags_are_distinct_people(client):
    """alice+walks@ is NOT alice@.

    Collapsing them is provider-specific behaviour, and getting it wrong attributes
    one person's walks to another. Under-matching only creates a duplicate record.
    """
    a = register(client, "alice@example.com")
    b = register(client, "alice+walks@example.com")
    assert a["id"] != b["id"]


def test_token_rotates_on_reregistration(client):
    first = register(client, "bob@example.com")
    second = register(client, "bob@example.com")
    assert first["token"] != second["token"]
    # The old token stops working — rotation, not a second valid credential.
    assert client.get("/api/identity/me", headers=auth(first["token"])).status_code == 401
    assert client.get("/api/identity/me", headers=auth(second["token"])).status_code == 200


def test_me_never_echoes_the_token(client):
    p = register(client, "carol@example.com")
    body = client.get("/api/identity/me", headers=auth(p["token"])).json()
    assert body["token"] is None


def test_token_is_stored_only_as_a_hash(client):
    from sqlalchemy import select

    from api.app.db import SessionLocal
    from api.app.models import Participant
    p = register(client, "dave@example.com")
    with SessionLocal() as db:
        row = db.execute(select(Participant)
                         .where(Participant.id == p["id"])).scalar_one()
    assert p["token"] not in row.token_hash
    assert len(row.token_hash) == 64        # sha256 hex


@pytest.mark.parametrize("headers,expected", [
    ({}, 401),
    ({"Authorization": "Bearer nonsense"}, 401),
    ({"Authorization": "Basic abc"}, 401),
    ({"Authorization": "Bearer"}, 401),
])
def test_bad_credentials_are_rejected(client, headers, expected):
    assert client.get("/api/identity/me", headers=headers).status_code == expected


@pytest.mark.parametrize("email", ["notanemail", "a@b", "@example.com", "a b@x.com",
                                   "two@@example.com"])
def test_malformed_email_rejected(client, email):
    r = client.post("/api/identity/register",
                    json=dict(first_name="X", last_name="Y", email=email))
    assert r.status_code == 422


def test_admin_endpoints_require_admin(client):
    p = register(client, "eve@example.com")
    assert client.get("/api/admin/overview", headers=auth(p["token"])).status_code == 403
