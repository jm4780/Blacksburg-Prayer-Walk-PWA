"""Blacksburg Prayer Walk — API.

Serves the routing engine and the PWA. Start with:

    BPW_TOKEN_PEPPER=... uvicorn api.app.main:app --reload

The built frontend, if present at web/dist, is mounted at / so the whole slice runs
from one process. In a real deployment the static bundle belongs on a CDN and this
mount is inert.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..routing.engine import ENGINE_VERSION
from .config import settings
from .db import init_db
from .routers import admin, identity, missions, progress, routes
from .schemas import HealthOut
from .services.network_state import network_service
from .version import build_id, build_info

log = logging.getLogger("bpw")
# Uvicorn configures its own loggers and leaves ours at the root default, so INFO from
# this application was being dropped — including the line naming the running build,
# which is the first thing anybody debugging a stale preview looks for.
log.setLevel(logging.INFO)
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
    log.addHandler(_h)
    log.propagate = False


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    ns = network_service()
    for w in settings().check():
        log.warning("DEPLOYMENT: %s", w)
    log.info("network %s (%s) engine %s", ns.net.network_id,
             ns.manifest["canonical_network_version"], ENGINE_VERSION)
    info = build_info()
    log.info("BUILD %s (%s) branch=%s%s", build_id(), info["source"], info["branch"],
             "  UNCOMMITTED EDITS" if info["dirty"] else "")
    if not _network_data_state(ns)["neighborhoods"]:
        log.warning("DEPLOYMENT: the street network on disk predates neighbourhood "
                    "names. Missions will not name neighbourhoods. Re-run: "
                    "python3 -m pipeline.build.run")
    yield


app = FastAPI(title="Blacksburg Prayer Walk", version="0.3.0",
              description=__doc__, lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=settings().origins,
                   allow_credentials=False,
                   allow_methods=["GET", "POST", "OPTIONS"],
                   allow_headers=["Authorization", "Content-Type"])

app.include_router(identity.router)
app.include_router(routes.router)
app.include_router(missions.router)
app.include_router(progress.router)
app.include_router(admin.router)


@app.get("/api/health", response_model=HealthOut)
def health():
    ns = network_service()
    s = settings()
    return HealthOut(
        status="ok", tier=s.tier, network_id=ns.net.network_id,
        network_version=ns.manifest["canonical_network_version"],
        engine_version=ENGINE_VERSION, warnings=s.check(),
        public_geometry_enabled=s.public_geometry_enabled,
        licensing_gate=admin._licensing_gate(),
        build=build_info(),
        network_data=_network_data_state(ns))


def _network_data_state(ns) -> dict:
    """Whether the built network on disk matches what the code expects.

    `network_version` comes from a constant in the code, so it reports v1.3 even when
    the segments file on disk was built before v1.3 existed. Neighbourhood names are
    the observable difference: v1.3 adds them, v1.2 has none. A v1.3 server reading
    v1.2 data still runs — every mission just loses its neighbourhood name and falls
    back to naming streets — which is quiet enough to waste an afternoon on.
    """
    # `stats["neighborhoods"]` is the list of names. The browser wants the count —
    # sending 25 names to render a one-line badge would be silly, and React would
    # happily concatenate them into it.
    names = ns.net.stats.get("neighborhoods") or []
    neighbourhoods = len(names) if isinstance(names, (list, tuple, set)) else int(names)
    return dict(
        built_at=ns.net.built_at,
        snapshot_date=ns.net.snapshot_date,
        neighborhoods=neighbourhoods,
        matches_code_version=bool(neighbourhoods),
        note=(None if neighbourhoods else
              "The street network on disk was built before neighbourhood names were "
              "added. Re-run: python3 -m pipeline.build.run"),
    )


@app.get("/api/version")
def version():
    """Deliberately tiny and dependency-free — the one call that always answers.

    `/api/health` loads the network, so if the data is missing or broken it fails, and
    the first question during a stale-preview hunt ("which commit is this?") goes
    unanswered exactly when it matters most.
    """
    return build_info()


_DIST = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "web", "dist")

if os.path.isdir(_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(_DIST, "assets")),
              name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        """Serve the PWA, falling back to index.html for client-side routes."""
        candidate = os.path.join(_DIST, path)
        if path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_DIST, "index.html"))
