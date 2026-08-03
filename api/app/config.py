"""Application settings. Everything that varies by deployment comes from the
environment — nothing sensitive is committed.

Three deployment tiers are recognised, because what may be exposed differs between
them and the licensing question (docs/05-licensing-status.md, gate G1) is unresolved:

  development   local, single operator. Everything on.
  pilot         limited authenticated pilot. Source-derived geometry served only to
                authenticated participants. This is the intended pilot posture.
  public        open to anyone. Geometry endpoints refuse to serve source-derived
                data until G1 is resolved, because publishing it is redistribution.

Set BPW_TIER to choose. The default is `pilot`: the safe middle. A deployment has to
opt *into* public exposure, never fall into it.
"""
from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings

TIERS = ("development", "pilot", "public")


class Settings(BaseSettings):
    model_config = {"env_prefix": "BPW_", "extra": "ignore"}

    tier: str = "pilot"

    # WHO MAY SEE ROUTE AND MAP GEOMETRY. This is the G1 control, and it is a
    # deployment setting rather than a product decision baked into the API:
    #
    #   authenticated  any signed-up participant.
    #   open_read      anyone may read the dashboard, progress map and a suggested
    #                  walk; identity is required to accept one. The pilot default.
    #   invite         signing up additionally requires BPW_INVITE_CODE.
    #   public         anyone, no sign-up. Set this once G1 is resolved.
    #
    # Moving to `public` changes no route handler, no schema and no client code —
    # `deps.may_see_geometry` is the single place the mode is consulted. The identity
    # model is unaffected in all three: name, email, remembered device. There is no
    # password and no account system to build.
    #
    # Default changed at Phase 3.5 to `open_read`: the product requires that the
    # dashboard, the progress map and a preliminary mission are visible before anyone
    # is asked for a name (Priority 2). `open_read` serves geometry to anonymous
    # readers while still requiring identity to *accept* a walk. G1 has not moved —
    # this is an operator decision about a pilot deployment, and it is stated in the
    # startup warnings and on /api/health rather than being silent.
    access_mode: str = "open_read"
    invite_code: str = ""

    # sqlite for the vertical slice; set BPW_DATABASE_URL to a postgresql+psycopg URL
    # for a real deployment. No credentials are ever written to the repository.
    database_url: str = "sqlite:///./bpw.db"

    # Canonical network snapshot to serve.
    snapshot_date: str = "2026-08-03"

    # Opaque participant tokens are stored only as a hash. This pepper is mixed in so a
    # stolen database does not yield working tokens. MUST be set outside development.
    token_pepper: str = ""

    # How long a soft reservation survives without being renewed.
    reservation_preview_minutes: int = 20
    reservation_active_minutes: int = 240

    # Set true only when licensing gate G1 is resolved AND the operator intends public
    # exposure. Serves route/progress geometry without authentication.
    public_geometry_enabled: bool = False

    cors_origins: str = "http://localhost:5173"

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_public(self) -> bool:
        return self.tier == "public"

    @property
    def geometry_is_public(self) -> bool:
        """The single question `deps.may_see_geometry` asks."""
        return (self.access_mode in ("open_read", "public")
                or self.public_geometry_enabled)

    def check(self) -> list[str]:
        """Deployment warnings, surfaced at startup and by /health."""
        out = []
        if self.tier not in TIERS:
            out.append(f"BPW_TIER={self.tier!r} is not one of {TIERS}")
        if self.tier != "development" and not self.token_pepper:
            out.append("BPW_TOKEN_PEPPER is unset outside development — participant "
                       "tokens are hashed without a pepper")
        if self.access_mode not in ("authenticated", "open_read", "invite", "public"):
            out.append(f"BPW_ACCESS_MODE={self.access_mode!r} is not one of "
                       f"authenticated | open_read | invite | public")
        if self.access_mode == "invite" and not self.invite_code:
            out.append("BPW_ACCESS_MODE=invite but BPW_INVITE_CODE is unset — "
                       "registration would be open to anyone")
        if self.is_public and not self.geometry_is_public:
            out.append("tier=public but access_mode is not public — geometry "
                       "endpoints require authentication (licensing gate G1)")
        if self.geometry_is_public:
            out.append(f"access_mode={self.access_mode} — source-derived geometry is "
                       "served to anonymous readers. This is redistribution of Town of "
                       "Blacksburg GIS data; licensing gate G1 is unresolved. Set "
                       "BPW_ACCESS_MODE=authenticated to require sign-in "
                       "(docs/05-licensing-status.md).")
        if self.database_url.startswith("sqlite") and self.tier == "public":
            out.append("sqlite database on a public tier")
        return out


@lru_cache
def settings() -> Settings:
    return Settings()
