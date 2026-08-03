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

    def check(self) -> list[str]:
        """Deployment warnings, surfaced at startup and by /health."""
        out = []
        if self.tier not in TIERS:
            out.append(f"BPW_TIER={self.tier!r} is not one of {TIERS}")
        if self.tier != "development" and not self.token_pepper:
            out.append("BPW_TOKEN_PEPPER is unset outside development — participant "
                       "tokens are hashed without a pepper")
        if self.is_public and not self.public_geometry_enabled:
            out.append("tier=public but public_geometry_enabled is false — geometry "
                       "endpoints require authentication (licensing gate G1)")
        if self.public_geometry_enabled:
            out.append("public_geometry_enabled=true — source-derived geometry is "
                       "being served without authentication. This is redistribution "
                       "of Town of Blacksburg GIS data. Confirm licensing gate G1 is "
                       "resolved (docs/05-licensing-status.md).")
        if self.database_url.startswith("sqlite") and self.tier == "public":
            out.append("sqlite database on a public tier")
        return out


@lru_cache
def settings() -> Settings:
    return Settings()
