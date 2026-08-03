"""Route generation and walk lifecycle.

The documented contract for POST /api/routes/generate:

  INPUT
    lat, lon           one-time device fix, or a point the walker tapped on the map
    start_source       DEVICE_LOCATION | MAP — recorded, because a tapped start is a
                       different kind of evidence from a GPS fix
    seed               optional, to reproduce an earlier request exactly
    Authorization      Bearer <opaque participant token>

  IMPLICIT INPUT (server-side, never sent by the browser)
    completion state   every segment recorded as prayed for, town-wide
    reservations       live soft holds from other walkers, as prize multipliers
    network            the frozen canonical network named in the response

  OUTPUT
    request_id, network_id, network_version, engine_version, seed, component,
    available_bands, state, and one VariantOut per band carrying the 17 documented
    per-variant fields (see schemas.VariantOut).

  NOT IN THE OUTPUT, ever
    any address, household coordinate, per-segment household count, participant
    identity other than the caller's own, or the identity of whoever holds a
    reservation.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_participant
from ..models import Participant, RouteRequest, Walk
from ..schemas import (CompleteWalkIn, RouteRequestIn, RouteResponseOut, SelectWalkIn,
                       WalkOut)
from ..services import completion as completion_svc
from ..services import reservations as res_svc
from ..services import routing_service as routing
from ..services.network_state import network_service

router = APIRouter(prefix="/api", tags=["routes"])

BLACKSBURG_BBOX = (-80.55, 37.15, -80.33, 37.30)   # lon_min, lat_min, lon_max, lat_max


@router.post("/routes/generate", response_model=RouteResponseOut)
def generate(body: RouteRequestIn, p: Participant = Depends(current_participant),
             db: Session = Depends(get_db)):
    if body.lat is None or body.lon is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "a start point is required: either a one-time device "
                            "location or a point selected on the map")
    lo, la = float(body.lon), float(body.lat)
    if not (BLACKSBURG_BBOX[0] <= lo <= BLACKSBURG_BBOX[2]
            and BLACKSBURG_BBOX[1] <= la <= BLACKSBURG_BBOX[3]):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "that start point is outside the Blacksburg area")

    ns = network_service()
    res_svc.purge_expired(db)
    state = ns.completion_state(db, participant_id=p.id)
    seed = body.seed if body.seed is not None else routing.new_seed()

    result = routing.generate(ns, lo, la, state, seed)

    req = RouteRequest(participant_id=p.id, network_id=result["network_id"],
                       engine_version=result["engine_version"],
                       start_node=result["start_node"], start_source=body.start_source,
                       seed=seed,
                       component_index=(result["component"] or {}).get("index"),
                       variants=result["variants"])
    db.add(req)
    db.commit()

    return RouteResponseOut(
        request_id=req.id, network_id=result["network_id"],
        network_version=ns.manifest["canonical_network_version"],
        engine_version=result["engine_version"], seed=seed, state=result["state"],
        component=result["component"], available_bands=result["available_bands"],
        variants=result["variants"])


@router.post("/walks/select", response_model=WalkOut)
def select_walk(body: SelectWalkIn, p: Participant = Depends(current_participant),
                db: Session = Depends(get_db)):
    """Preview a variant. Creates the walk and takes short soft holds on its segments."""
    ns = network_service()
    req = db.get(RouteRequest, body.request_id)
    if req is None or req.participant_id != p.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown route request")
    v = next((x for x in req.variants if x["band"] == body.band and x["available"]), None)
    if v is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"the {body.band} size is not available for this request")

    # One walk at a time per participant, and previewing is treated differently from
    # starting. Browsing sizes replaces the previous PREVIEW and releases its holds, so
    # trying five sizes does not hold five routes. An ACTIVE walk is a commitment and
    # is never discarded silently — the caller has to finish or cancel it.
    #
    # Without this, a participant could leave an ACTIVE walk behind on any error path
    # and then start another, holding both sets of segments against everyone else for
    # the full active-reservation window. Found by test ordering in
    # tests/test_completion.py, not by design.
    active = db.execute(select(Walk).where(Walk.participant_id == p.id,
                                           Walk.status == "ACTIVE")).scalars().first()
    if active is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"You already have a walk in progress ({active.band}, "
            f"{active.distance_miles} mi). Finish or cancel it before starting another.")

    for old in db.execute(select(Walk).where(Walk.participant_id == p.id,
                                             Walk.status == "PREVIEW")).scalars():
        res_svc.release(db, old)
        old.status = "DISCARDED"
        old.resolved_at = datetime.now(timezone.utc)
    db.commit()

    walk = Walk(participant_id=p.id, request_id=req.id, network_id=req.network_id,
                engine_version=req.engine_version, status="PREVIEW", band=v["band"],
                target_miles=v["target_miles"], distance_miles=v["distance_miles"],
                estimated_minutes=v["estimated_minutes"],
                planned_segment_ids=v["segment_ids"],
                planned_required_ids=v["required_segment_ids"],
                score_components=v["score_components"] or {})
    db.add(walk)
    db.commit()
    res_svc.reserve(db, walk, v["required_segment_ids"])
    return _walk_out(ns, walk, v)


@router.post("/walks/{walk_id}/start", response_model=WalkOut)
def start_walk(walk_id: str, p: Participant = Depends(current_participant),
               db: Session = Depends(get_db)):
    walk = _own_walk(db, walk_id, p)
    if walk.status not in ("PREVIEW", "ACTIVE"):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"walk is {walk.status}, cannot be started")
    walk.status = "ACTIVE"
    walk.started_at = walk.started_at or datetime.now(timezone.utc)
    db.commit()
    res_svc.extend(db, walk)
    return _walk_out(network_service(), walk)


@router.post("/walks/{walk_id}/discard", response_model=WalkOut)
def discard_walk(walk_id: str, p: Participant = Depends(current_participant),
                 db: Session = Depends(get_db)):
    walk = _own_walk(db, walk_id, p)
    if walk.status == "COMPLETED":
        raise HTTPException(status.HTTP_409_CONFLICT, "walk is already completed")
    res_svc.release(db, walk)
    walk.status = "DISCARDED"
    walk.resolved_at = datetime.now(timezone.utc)
    db.commit()
    return _walk_out(network_service(), walk)


@router.post("/walks/{walk_id}/complete")
def complete_walk(walk_id: str, body: CompleteWalkIn,
                  p: Participant = Depends(current_participant),
                  db: Session = Depends(get_db)):
    """Post-walk confirmation (§14). Idempotent (§15)."""
    ns = network_service()
    walk = _own_walk(db, walk_id, p)
    if walk.status == "DISCARDED":
        raise HTTPException(status.HTTP_409_CONFLICT, "walk was discarded")
    if body.outcome != "AS_PLANNED" and not body.segment_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "select the segments you walked")
    if body.outcome == "PARTIAL":
        # A partial walk is a subset of the plan. Anything else is a different route,
        # and calling it partial would put segments in the record that this walk never
        # offered.
        planned = set(walk.planned_required_ids)
        stray = [s for s in (body.segment_ids or []) if s not in planned]
        if stray:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"{len(stray)} of the selected segments are not part of this walk's "
                f"plan; report those as 'walked somewhere different'")

    result = completion_svc.record(db, ns, walk, body.outcome, body.segment_ids,
                                   body.note)
    res_svc.release(db, walk)
    return result


@router.get("/walks/current", response_model=WalkOut | None)
def current_walk(p: Participant = Depends(current_participant),
                 db: Session = Depends(get_db)):
    walk = db.execute(
        select(Walk).where(Walk.participant_id == p.id,
                           Walk.status.in_(("PREVIEW", "ACTIVE")))
        .order_by(Walk.created_at.desc())).scalars().first()
    return _walk_out(network_service(), walk) if walk else None


@router.get("/walks/{walk_id}", response_model=WalkOut)
def get_walk(walk_id: str, p: Participant = Depends(current_participant),
             db: Session = Depends(get_db)):
    return _walk_out(network_service(), _own_walk(db, walk_id, p))


def _own_walk(db: Session, walk_id: str, p: Participant) -> Walk:
    walk = db.get(Walk, walk_id)
    if walk is None or walk.participant_id != p.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown walk")
    return walk


def _walk_out(ns, walk: Walk, variant: dict | None = None) -> WalkOut:
    geom = variant.get("geometry") if variant else _geometry_for(ns, walk)
    return WalkOut(
        id=walk.id, status=walk.status, band=walk.band,
        target_miles=walk.target_miles, distance_miles=walk.distance_miles,
        estimated_minutes=walk.estimated_minutes, network_id=walk.network_id,
        engine_version=walk.engine_version,
        required_segment_count=len(walk.planned_required_ids),
        created_at=walk.created_at.isoformat(),
        started_at=walk.started_at.isoformat() if walk.started_at else None,
        resolved_at=walk.resolved_at.isoformat() if walk.resolved_at else None,
        outcome=walk.outcome, geometry=geom,
        directions=_directions(ns, walk))


def _geometry_for(ns, walk: Walk) -> dict | None:
    """Rebuild the walk's line from stored segment ids.

    Geometry is never persisted — the frozen network is the single source of it, and
    storing a copy would mean a stored walk could silently disagree with the network
    it names.
    """
    coords: list = []
    for sid in walk.planned_segment_ids:
        i = ns.idx_of_id.get(sid)
        if i is None:
            continue
        pts = list(ns.net.segments[i].coords)
        if not pts:
            continue
        if coords and _far(coords[-1], pts[0]) and not _far(coords[-1], pts[-1]):
            pts.reverse()
        if coords and coords[-1] == pts[0]:
            pts = pts[1:]
        coords.extend(pts)
    return {"type": "LineString", "coordinates": coords} if coords else None


def _far(a, b, tol=1e-7) -> bool:
    return abs(a[0] - b[0]) > tol or abs(a[1] - b[1]) > tol


def _directions(ns, walk: Walk) -> list[dict]:
    """A static turn list for the active-walk screen (§13).

    Consecutive segments sharing a street name collapse into one instruction, so the
    walk reads as "Draper Rd, 0.3 mi" rather than as forty segment ids. Derived
    connectors are called out, because they are links no source asserted and a walker
    should know they are crossing on our inference, not on the town's.
    """
    steps: list[dict] = []
    for sid in walk.planned_segment_ids:
        i = ns.idx_of_id.get(sid)
        if i is None:
            continue
        seg = ns.net.segments[i]
        name = seg.display_name or ("crossing" if seg.is_derived else "unnamed path")
        if steps and steps[-1]["name"] == name and steps[-1]["derived"] == seg.is_derived:
            steps[-1]["miles"] = round(steps[-1]["miles"] + seg.miles, 2)
            continue
        steps.append(dict(name=name, miles=round(seg.miles, 2),
                          derived=seg.is_derived, required=seg.required,
                          campus_alternative=seg.campus_obligation == "ALTERNATIVE"))
    return [s for s in steps if s["miles"] >= 0.01]
