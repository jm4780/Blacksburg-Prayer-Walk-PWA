"""Blacksburg Prayer Walk API. Contract section 4.

No auth. A device id is a claim, not a credential, and nothing in the schema can
be damaged by a forged one.

The only endpoint that ever receives a raw coordinate is POST /api/match, and it
stores nothing: the trace is held in memory for the length of one request and
then dropped.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from . import db, engines

# Walking pace used to turn minutes into metres. 4.8 km/h, which is an ordinary
# adult walk with stops to pray.
METRES_PER_MINUTE = 80.0

app = FastAPI(title="Blacksburg Prayer Walk", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# request bodies
# --------------------------------------------------------------------------


class RouteRequest(BaseModel):
    lon: float
    lat: float
    minutes: float = Field(gt=0, le=600)
    seed: int | None = None


class WalkRequest(BaseModel):
    device_id: str
    client_walk_id: str
    display_name: str | None = None
    started_at: str | None = None
    seg_ids: list[int]


class Fix(BaseModel):
    lat: float
    lon: float
    accuracy_m: float | None = None
    t: float


class MatchRequest(BaseModel):
    trace: list[Fix]


# --------------------------------------------------------------------------
# endpoints
# --------------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict[str, Any]:
    out: dict[str, Any] = {"api": "ok"}
    try:
        out["segments"] = len(db.load_network())
        out["db"] = "ok"
    except Exception as exc:  # pragma: no cover - only when Postgres is down
        out["db"] = f"down: {exc}"
    for name, probe in (("route", _route_ready), ("coverage", _coverage_ready)):
        out[f"engine_{name}"] = probe()
    return out


def _route_ready() -> str:
    try:
        engines._load("engine.route", "generate")
        return "ok"
    except engines.EngineUnavailable as exc:
        return exc.detail


def _coverage_ready() -> str:
    try:
        engines._load("engine.coverage", "propose")
        return "ok"
    except engines.EngineUnavailable as exc:
        return exc.detail


_network_body: bytes | None = None
_network_etag: str | None = None


@app.get("/api/network")
def network(request: Request) -> Response:
    """Every segment with its geometry. Immutable between builds, so it is
    cached hard on both ends."""
    global _network_body, _network_etag
    if _network_body is None:
        segments = [
            {
                "seg_id": s["seg_id"],
                "name": s["name"],
                "length_m": s["length_m"],
                "geometry": s["geometry"],
            }
            for s in db.load_network()
        ]
        _network_body = db.json_dumps({"segments": segments}).encode()
        _network_etag = f'W/"net-{len(segments)}-{len(_network_body)}"'

    if request.headers.get("if-none-match") == _network_etag:
        return Response(status_code=304, headers={"ETag": _network_etag or ""})

    return Response(
        content=_network_body,
        media_type="application/json",
        headers={"ETag": _network_etag or "", "Cache-Control": "public, max-age=604800"},
    )


@app.get("/api/progress")
def progress() -> dict[str, Any]:
    return db.progress()


@app.get("/api/coverage")
def coverage() -> dict[str, Any]:
    return {"covered": db.covered_ids()}


@app.post("/api/route")
def route(body: RouteRequest) -> dict[str, Any]:
    target_m = engines.metres_for_minutes(body.minutes, METRES_PER_MINUTE)
    try:
        r = engines.generate(
            (body.lon, body.lat),
            target_m,
            db.load_network(),
            set(db.covered_ids()),
            seed=body.seed,
        )
    except engines.EngineUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "route_engine_unavailable",
                "message": "Route planning is not running yet. You can still pick streets yourself and walk.",
                "engine": exc.engine,
                "detail": exc.detail,
            },
        )

    seg_ids = [int(x) for x in r.get("seg_ids", [])]
    new_ids = [int(x) for x in r.get("new_seg_ids", [])]
    return {
        "seg_ids": seg_ids,
        "new_seg_ids": new_ids,
        "geometry": engines.to_geojson(r.get("geometry")),
        "length_m": float(r.get("length_m", 0.0)),
        "new_m": float(r.get("new_m", 0.0)),
        "target_m": target_m,
        "minutes": body.minutes,
    }


@app.post("/api/walk")
def walk(body: WalkRequest) -> dict[str, Any]:
    """Commit a confirmed walk. Idempotent on (device_id, client_walk_id):
    replaying the same pair returns the original walk and covers nothing new."""
    if not body.seg_ids:
        raise HTTPException(status_code=400, detail="A walk needs at least one street.")
    try:
        walk_id, newly = db.commit_walk(
            body.device_id,
            body.client_walk_id,
            body.display_name,
            body.started_at,
            sorted(set(int(x) for x in body.seg_ids)),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"walk_id": walk_id, "newly_covered": newly}


@app.post("/api/match")
def match(body: MatchRequest) -> dict[str, Any]:
    """The one endpoint that sees raw coordinates. It stores none of them.

    The trace is turned into a list of segment proposals and forgotten when the
    response is written. Nothing here touches the database.
    """
    trace = [
        {"lat": f.lat, "lon": f.lon, "accuracy_m": f.accuracy_m or 30.0, "t": f.t}
        for f in body.trace
    ]
    if not trace:
        return {"proposals": []}
    try:
        proposals = engines.propose(trace, db.load_network())
    except engines.EngineUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "coverage_engine_unavailable",
                "message": "Street matching is not running yet. Tick the streets you walked and they will still count.",
                "engine": exc.engine,
                "detail": exc.detail,
            },
        )
    out = []
    for p in proposals:
        out.append(
            {
                "seg_id": int(p["seg_id"]),
                "name": p.get("name", ""),
                "confidence": float(p.get("confidence", 0.0)),
                "matched_m": float(p.get("matched_m", 0.0)),
                "reason": p.get("reason", ""),
            }
        )
    return {"proposals": out}


@app.exception_handler(HTTPException)
def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, str):
        detail = {"message": detail}
    return JSONResponse(status_code=exc.status_code, content=detail)


@app.middleware("http")
async def timing(request: Request, call_next):
    t0 = time.time()
    resp = await call_next(request)
    resp.headers["X-Elapsed-Ms"] = f"{(time.time() - t0) * 1000:.1f}"
    return resp
