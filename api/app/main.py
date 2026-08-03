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
from .routers import admin, identity, progress, routes
from .schemas import HealthOut
from .services.network_state import network_service

log = logging.getLogger("bpw")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    ns = network_service()
    for w in settings().check():
        log.warning("DEPLOYMENT: %s", w)
    log.info("network %s (%s) engine %s", ns.net.network_id,
             ns.manifest["canonical_network_version"], ENGINE_VERSION)
    yield


app = FastAPI(title="Blacksburg Prayer Walk", version="0.3.0",
              description=__doc__, lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=settings().origins,
                   allow_credentials=False,
                   allow_methods=["GET", "POST", "OPTIONS"],
                   allow_headers=["Authorization", "Content-Type"])

app.include_router(identity.router)
app.include_router(routes.router)
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
        licensing_gate=admin._licensing_gate())


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
