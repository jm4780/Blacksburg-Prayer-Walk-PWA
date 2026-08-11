"""Route generation and walk lifecycle.

The documented contract for POST /api/routes/generate:

  INPUT
    lat, lon           one-time device fix, or a point the walker tapped on the map
    start_source       DEVICE_LOCATION | MAP — recorded, because a tapped start is a
                       different kind of evidence from a GPS fix
    requested_family   optional band name; omitted returns every variant in one
                       response, which is what the size control needs
    seed               optional, to reproduce an earlier request exactly
    Authorization      Bearer <opaque participant token> — the participant ID

  RESOLVED SERVER-SIDE, NEVER SENT BY THE BROWSER
    coverage-area ID          the routing component the start snapped into. Derived,
                              not supplied: a browser that could name its own coverage
                              area could ask for a route in one it is not standing in.
    completion-state version  fingerprint of every segment recorded as prayed for.
                              Echoed back and stored, so a failure to reproduce a
                              route is explainable rather than mysterious.
    active reservations       live soft holds from other walkers, applied as prize
                              multipliers. Count echoed back; holders never named.
    network                   the frozen canonical network named in the response.

  OUTPUT
    request_id, network_id, network_version, engine_version, seed, coverage_area_id,
    completion_state_version, component, available_bands, state, and one VariantOut
    per band carrying: route-size label, geometry, start/end point, ordered traversed
    segments, canonical REQUIRED obligations, connector segments, total distance,
    estimated walking time, estimated households passed, expected new required
    mileage, route status, availability reason, route score, walk-quality score,
    reproducibility seed, network version, engine version.

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
from ..models import Participant, RouteFeedback, RouteRequest, Walk
from ..schemas import (CompleteWalkIn, FeedbackIn, FeedbackOut, RouteRequestIn,
                       RouteResponseOut, SelectWalkIn, WalkOut)
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

    result = routing.generate(ns, lo, la, state, seed,
                              requested_family=body.requested_family)

    req = RouteRequest(participant_id=p.id, network_id=result["network_id"],
                       engine_version=result["engine_version"],
                       start_node=result["start_node"], start_source=body.start_source,
                       seed=seed,
                       coverage_area_id=result["coverage_area_id"],
                       component_index=(result["component"] or {}).get("index"),
                       completion_state_version=result["completion_state_version"],
                       requested_family=body.requested_family,
                       active_reservation_count=len(state.reserved),
                       variants=result["variants"],
                       # §17: a request that produced nothing is a route-generation
                       # failure worth inspecting, not just an empty response.
                       failure_reason=(None if result["available_bands"]
                                       else result["state"]))
    db.add(req)
    db.commit()

    return RouteResponseOut(
        request_id=req.id, network_id=result["network_id"],
        network_version=ns.manifest["canonical_network_version"],
        engine_version=result["engine_version"], seed=seed, state=result["state"],
        coverage_area_id=result["coverage_area_id"],
        completion_state_version=result["completion_state_version"],
        component=result["component"], available_bands=result["available_bands"],
        variants=result["variants"])


def claim_walk_slot(db: Session, participant_id: str) -> None:
    """Take the participant's one open-walk slot, ready for a new walk to be inserted.

    "Open" means PREVIEW **or** ACTIVE: both states hold segments against everybody
    else, and a participant may be in exactly one of them at a time. The two are not
    treated the same way, because they mean different things.

      ACTIVE   a commitment. Never replaced silently — the caller has to finish or
               cancel it, so this refuses and nothing is written. Without it, a
               participant could leave an ACTIVE walk behind on any error path and
               then start another, holding both sets of segments for the full
               active-reservation window. Found by test ordering in
               tests/test_completion.py, not by design.
      PREVIEW  browsing. Replaced, with its holds released, so trying five sizes or
               three missions does not hold three routes.

    Deliberately **not committed here**. The row lock taken on the participant is what
    makes the claim atomic, and a lock lasts only as long as the transaction: the
    caller inserts its new walk and commits once, so two devices accepting at the same
    moment queue up behind each other instead of both finding an empty slot and both
    ending up with a live walk. Before this, the guard was a plain read followed by an
    unrelated write, and two simultaneous accepts could both pass it.

    PostgreSQL, which the pilot runs, makes `FOR UPDATE` a real per-participant mutex.
    SQLite's dialect drops the clause, and its single writer serialises the same work
    at the cost of the loser seeing a busy database rather than a clean 409.

    Lives here rather than in a service because a refusal is an HTTP answer, and the
    services layer deliberately knows nothing about HTTP. Shared with
    `routers/missions.py` so the two ways of starting a walk cannot drift apart again.
    """
    db.execute(select(Participant.id)
               .where(Participant.id == participant_id).with_for_update())

    open_walks = db.execute(
        select(Walk).where(Walk.participant_id == participant_id,
                           Walk.status.in_(("PREVIEW", "ACTIVE")))).scalars().all()

    active = next((w for w in open_walks if w.status == "ACTIVE"), None)
    if active is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"You already have a walk in progress ({active.band}, "
            f"{active.distance_miles} mi). Finish or cancel it before starting another.")

    now = datetime.now(timezone.utc)
    for old in open_walks:
        res_svc.release(db, old, commit=False)
        old.status = "DISCARDED"
        old.resolved_at = now


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

    # One walk at a time per participant. The claim stays open until the commit below,
    # so the walk that replaces the previous preview lands in the same transaction that
    # let the previous one go.
    claim_walk_slot(db, p.id)

    walk = Walk(participant_id=p.id, request_id=req.id, network_id=req.network_id,
                engine_version=req.engine_version, status="PREVIEW", band=v["band"],
                target_miles=v["target_miles"], distance_miles=v["distance_miles"],
                estimated_minutes=v["estimated_minutes"],
                planned_segment_ids=v["segment_ids"],
                planned_required_ids=v["required_segment_ids"],
                planned_connector_ids=v.get("connector_segment_ids") or [],
                seed=req.seed,
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
    """Post-walk confirmation (§14).

    §15 asks that submitting the same walk twice moves no number. The way that promise
    is kept is by refusing the second submission outright, before anything is written.
    Letting a COMPLETED walk be recorded again meant a walker who reloaded the
    confirmation screen was offered the three-way question a second time, and
    answering "I didn't complete it" zeroed the walk's distance while leaving the
    street completions it had already earned standing. The town's own numbers then
    disagreed about a single walk: the streets counted as prayed for, the miles did
    not, and a second set of REMOVED rows was written into the audit trail.

    Correcting a submitted walk is an administrator's job
    (`POST /api/admin/completions/reverse`), where it is audited before it is applied.
    It is not something the confirmation screen can do by being visited twice.
    """
    ns = network_service()
    walk = _own_walk(db, walk_id, p)
    if walk.status == "COMPLETED":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This walk is already recorded, so there is nothing left to submit. If "
            "what we recorded is wrong, tell us and we will correct it.")
    if walk.status == "DISCARDED":
        raise HTTPException(status.HTTP_409_CONFLICT, "walk was discarded")
    if walk.status == "PREVIEW":
        # §14 confirms a walk that happened. A PREVIEW is a route being looked at:
        # nobody has set off, so there is nothing to confirm and no mileage to credit.
        # Discarding a preview is still the ordinary way to put one down.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This walk was never started, so there is nothing to record. Tap Start "
            "when you set off, and confirm it when you are back.")
    if body.outcome == "EDITED" and not body.segment_ids:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "select the streets you covered, or report that you did not complete "
            "the walk")

    result = completion_svc.record(db, ns, walk, body.outcome, body.segment_ids,
                                   body.note)
    res_svc.release(db, walk)
    return result


@router.post("/walks/{walk_id}/feedback", response_model=FeedbackOut)
def submit_feedback(walk_id: str, body: FeedbackIn,
                    p: Participant = Depends(current_participant),
                    db: Session = Depends(get_db)):
    """Pilot feedback (§5). Available from the active-walk screen and after submission.

    One row per walk, updated in place if sent twice — a walker who rates the route
    mid-walk and again at the end has one opinion, not two. Everything needed to
    regenerate the exact route is stored alongside, so a complaint is reproducible.
    """
    walk = _own_walk(db, walk_id, p)
    req = db.get(RouteRequest, walk.request_id) if walk.request_id else None
    ns = network_service()

    row = db.execute(select(RouteFeedback)
                     .where(RouteFeedback.walk_id == walk.id)).scalar_one_or_none()
    updated = row is not None
    if row is None:
        row = RouteFeedback(walk_id=walk.id, participant_id=p.id,
                            network_id=walk.network_id,
                            network_version=ns.manifest["canonical_network_version"],
                            engine_version=walk.engine_version,
                            seed=walk.seed,
                            coverage_area_id=(req.coverage_area_id if req else None),
                            start_node=(req.start_node if req else None),
                            band=walk.band)
        db.add(row)
    row.rating = body.rating
    row.easy_to_follow = body.easy_to_follow
    row.time_felt_accurate = body.time_felt_accurate
    row.had_bad_connection = body.had_bad_connection
    row.bad_connection_detail = body.bad_connection_detail
    row.completed_as_planned = body.completed_as_planned
    row.comment = body.comment
    row.submitted_from = body.submitted_from
    db.commit()
    db.refresh(row)

    return FeedbackOut(
        id=row.id, walk_id=walk.id, rating=row.rating, updated=updated,
        reproduce=dict(network_id=row.network_id, network_version=row.network_version,
                       engine_version=row.engine_version, seed=row.seed,
                       coverage_area_id=row.coverage_area_id,
                       start_node=row.start_node, band=row.band))


@router.get("/walks/{walk_id}/feedback", response_model=FeedbackOut | None)
def get_feedback(walk_id: str, p: Participant = Depends(current_participant),
                 db: Session = Depends(get_db)):
    walk = _own_walk(db, walk_id, p)
    row = db.execute(select(RouteFeedback)
                     .where(RouteFeedback.walk_id == walk.id)).scalar_one_or_none()
    if row is None:
        return None
    return FeedbackOut(id=row.id, walk_id=walk.id, rating=row.rating, updated=True,
                       reproduce=dict(network_id=row.network_id,
                                      network_version=row.network_version,
                                      engine_version=row.engine_version,
                                      seed=row.seed,
                                      coverage_area_id=row.coverage_area_id,
                                      start_node=row.start_node, band=row.band))


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
        planned_required_ids=list(walk.planned_required_ids),
        households=_households(ns, walk),
        start_point=_start_point(ns, walk),
        created_at=walk.created_at.isoformat(),
        started_at=walk.started_at.isoformat() if walk.started_at else None,
        resolved_at=walk.resolved_at.isoformat() if walk.resolved_at else None,
        outcome=walk.outcome, geometry=geom,
        directions=_directions(ns, walk))


def _households(ns, walk: Walk) -> int:
    """Estimated dwelling units passed by the plan (§13).

    Summed over the walk's own required segments — an aggregate for one route, never
    a per-segment figure, and never anything that identifies a dwelling.
    """
    return sum(ns.net.segments[ns.idx_of_id[s]].households
               for s in walk.planned_required_ids if s in ns.idx_of_id)


def _start_point(ns, walk: Walk) -> list | None:
    """WGS84 [lon, lat] where the walk begins and ends (§13). A closed walk, so one
    point serves as both."""
    for sid in walk.planned_segment_ids:
        i = ns.idx_of_id.get(sid)
        if i is not None and ns.net.segments[i].coords:
            return list(ns.net.segments[i].coords[0])
    return None


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
