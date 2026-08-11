"""Mission recommendation endpoints.

    GET  /api/missions/recommend?minutes=45     the walk we suggest
    POST /api/missions/{id}/accept              turn it into a walk (identity required)

`recommend` is deliberately **anonymous-friendly**. Someone who has just opened the app
should be able to see the shared progress and a real suggested walk before being asked
who they are (Priority 2). Identity is requested at `accept`, which is the first moment
it means anything — that's when a walk is recorded against a person and segments are
held against everybody else.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_participant, optional_participant
from ..models import Participant, RouteRequest, Walk
from ..services import mission_service as svc
from ..services import reservations as res_svc
from ..services import routing_service as routing
from ..services.network_state import network_service
# The one-open-walk guard is shared with /api/walks/select rather than written twice:
# two copies of "how many walks may a participant have" is how they came to disagree.
from .routes import claim_walk_slot

router = APIRouter(prefix="/api/missions", tags=["missions"])


@router.get("/options")
def options():
    """What the time slider may offer."""
    return dict(min_minutes=svc.MIN_MINUTES, max_minutes=svc.MAX_MINUTES,
                step_minutes=svc.STEP_MINUTES, default_minutes=45,
                pace_mph=svc.DEFAULT_PACE_MPH,
                pace_note=("Walking time is an estimate. Distances come from the "
                           "canonical network; pace is assumed, not measured."))


@router.get("/recommend")
def recommend(minutes: int = Query(45, ge=5, le=240),
              p: Participant | None = Depends(optional_participant),
              db: Session = Depends(get_db)):
    """The suggested walk for this much time. No sign-in required."""
    ns = network_service()
    res_svc.purge_expired(db)

    held = ns.active_reservations(db, exclude_participant=(p.id if p else None))
    state = ns.completion_state(db, participant_id=(p.id if p else None))

    candidates = svc.slate(ns, state, minutes, reserved_indices=set(held), size=5)
    if not candidates:
        return dict(
            available=False,
            minutes=svc.clamp_minutes(minutes),
            reason=("Every required street is recorded as prayed for. There is nothing "
                    "left to assign."),
            mission=None, alternatives=[], network_version=f"v{ns.net.version}")

    chosen = svc.assign(candidates, p.id if p else None)
    payload = svc.to_payload(chosen, ns)
    payload["directions"] = svc.directions_links(chosen.start.lat, chosen.start.lon)

    return dict(
        available=True,
        minutes=svc.clamp_minutes(minutes),
        requested_minutes=minutes,
        mission=payload,
        # Enough to offer "show me a different one" without a second round trip.
        alternatives=[dict(id=m.id, title=svc.describe(m, ns)["title"],
                           estimated_minutes=svc.miles_to_minutes(m.distance_miles),
                           distance_miles=m.distance_miles, households=m.value)
                      for m in candidates if m.id != chosen.id],
        slate_size=len(candidates),
        network_version=f"v{ns.net.version}",
    )


@router.get("/{mission_id}")
def get_mission(mission_id: str, minutes: int = Query(45, ge=5, le=240),
                p: Participant | None = Depends(optional_participant),
                db: Session = Depends(get_db)):
    """Fetch one specific mission from the current slate, by id."""
    ns = network_service()
    state = ns.completion_state(db, participant_id=(p.id if p else None))
    held = ns.active_reservations(db, exclude_participant=(p.id if p else None))
    for m in svc.slate(ns, state, minutes, reserved_indices=set(held), size=5):
        if m.id == mission_id:
            payload = svc.to_payload(m, ns)
            payload["directions"] = svc.directions_links(m.start.lat, m.start.lon)
            return dict(available=True, minutes=svc.clamp_minutes(minutes),
                        mission=payload, alternatives=[],
                        network_version=f"v{ns.net.version}")
    raise HTTPException(status.HTTP_404_NOT_FOUND,
                        "That mission is no longer on offer — the town has moved on "
                        "since it was suggested. Ask for a new recommendation.")


@router.post("/{mission_id}/accept")
def accept(mission_id: str, minutes: int = Query(45, ge=5, le=240),
           p: Participant = Depends(current_participant),
           db: Session = Depends(get_db)):
    """Accept a mission and turn it into a walk. Identity required from here on.

    Reuses the existing walk, reservation and completion machinery unchanged — a
    mission becomes an ordinary `Walk`, so the active-walk screen, the confirmation
    flow and every metric keep working exactly as they did.
    """
    ns = network_service()
    state = ns.completion_state(db, participant_id=p.id)
    held = ns.active_reservations(db, exclude_participant=p.id)

    chosen = next((m for m in svc.slate(ns, state, minutes,
                                        reserved_indices=set(held), size=5)
                   if m.id == mission_id), None)
    if chosen is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "That walk is no longer available. Ask for a new "
                            "recommendation and we'll find you another.")

    # One open walk per participant, PREVIEW or ACTIVE, claimed under a row lock and
    # held until the single commit below. Accepting a second mission replaces a walk
    # that was only ever previewed — accepting is how you look at a mission, and a
    # walker who backs out of one and takes another has not committed to two. What the
    # claim adds is that two devices accepting at the same moment can no longer both
    # come away with a live walk: one of them waits, then sees the other's walk and is
    # told about it instead of quietly discarding it.
    claim_walk_slot(db, p.id)

    # A route request row keeps the mission reproducible on the same terms as any
    # other route: seed, network, engine, completion state.
    req = RouteRequest(
        participant_id=p.id, network_id=ns.net.network_id,
        engine_version=chosen.meta.get("engine", {}).get("engine_version")
        or _engine_version(),
        start_node=chosen.start.node_index, start_source="MISSION",
        seed=ns.engine.cfg.random_seed,
        coverage_area_id=f"mission-{chosen.id}",
        completion_state_version=routing.completion_state_version(state),
        requested_family=f"{svc.clamp_minutes(minutes)}min",
        active_reservation_count=len(held),
        variants=[], failure_reason=None)
    db.add(req)
    # Flush rather than commit: `req.id` is generated at INSERT and the walk below
    # needs it, but committing here would end the transaction and drop the claim.
    db.flush()

    connectors = sorted({sid for sid in chosen.segment_ids
                         if sid not in set(chosen.required_segment_ids)})
    walk = Walk(
        participant_id=p.id, request_id=req.id, network_id=ns.net.network_id,
        engine_version=req.engine_version, status="PREVIEW",
        band=f"{svc.clamp_minutes(minutes)}min",
        target_miles=svc.minutes_to_miles(svc.clamp_minutes(minutes)),
        distance_miles=chosen.distance_miles,
        estimated_minutes=svc.miles_to_minutes(chosen.distance_miles),
        planned_segment_ids=chosen.segment_ids,
        planned_required_ids=chosen.required_segment_ids,
        planned_connector_ids=connectors,
        seed=req.seed,
        score_components=(chosen.route.score.components if chosen.route.score else {}))
    db.add(walk)
    db.commit()
    res_svc.reserve(db, walk, chosen.required_segment_ids)

    return dict(walk_id=walk.id, mission_id=chosen.id,
                distance_miles=walk.distance_miles,
                estimated_minutes=walk.estimated_minutes)


def _engine_version() -> str:
    from ...routing.engine import ENGINE_VERSION
    return ENGINE_VERSION
