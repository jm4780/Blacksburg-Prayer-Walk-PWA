"""Recording what was actually walked (§14, §15), and the aggregate metrics (§4).

Two rules govern this module.

**Idempotency.** Submitting the same walk twice must not move any number. The unique
constraint on (walk_id, segment_id) does the work; the service reports how many rows
were genuinely new so a double-tap is visible as "0 new" rather than silently
succeeding.

**The plan is not the record.** `Walk.planned_segment_ids` is never rewritten. If a
walker reports they went somewhere else, that becomes `completions` rows against the
segments they picked, and the original plan survives beside it. Anyone auditing a
coverage claim can see both what was offered and what was reported.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Completion, Walk
from .network_state import NetworkService

M_PER_MILE = 1609.344

OUTCOMES = {
    "AS_PLANNED": "Walked the route as planned.",
    "PARTIAL": "Walked part of the route.",
    "DIFFERENT_ROUTE": "Walked somewhere different.",
}


def record(db: Session, ns: NetworkService, walk: Walk, outcome: str,
           segment_ids: list[str] | None, note: str | None = None) -> dict:
    """Write completions for one walk. Idempotent.

    `segment_ids` is ignored for AS_PLANNED (the plan is the answer) and required
    otherwise. Selection is always by segment, never freehand: §14 asks for segment or
    obligation selection, and a drawn line would have to be map-matched back onto the
    network anyway — with all the silent errors that implies.
    """
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown outcome {outcome!r}")

    if outcome == "AS_PLANNED":
        chosen = list(walk.planned_required_ids)
    else:
        chosen = [s for s in (segment_ids or []) if s in ns.idx_of_id]

    # Only REQUIRED segments earn coverage. A walker can legitimately report walking a
    # connector; it just does not move the town-wide number, because connectors are
    # not part of the obligation.
    idx = {ns.idx_of_id[s] for s in chosen}
    required_idx = {i for i in idx if ns.net.segments[i].required}

    # Campus corridors earned by walking the parallel walkway (network v1.2, §4.2).
    credited = {i for i in ns.net.credited(idx) if ns.net.segments[i].required}

    existing = set(db.execute(
        select(Completion.segment_id).where(Completion.walk_id == walk.id)
    ).scalars().all())

    new = 0
    for i in sorted(required_idx | credited):
        sid = ns.id_of_idx[i]
        if sid in existing:
            continue
        db.add(Completion(walk_id=walk.id, participant_id=walk.participant_id,
                          segment_id=sid, network_id=walk.network_id,
                          source=outcome, via_alternative=i in credited))
        new += 1

    walk.status = "COMPLETED"
    walk.outcome = outcome
    walk.note = (note or None)
    walk.resolved_at = datetime.now(timezone.utc)
    db.commit()

    return dict(
        walk_id=walk.id,
        outcome=outcome,
        segments_recorded=len(required_idx | credited),
        segments_newly_recorded=new,
        segments_already_recorded=len(required_idx | credited) - new,
        campus_credited_segments=len(credited),
        idempotent=new == 0,
        miles_credited=round(
            sum(ns.net.segments[i].length_m for i in required_idx | credited)
            / M_PER_MILE, 3),
    )


def completed_segment_ids(db: Session) -> set[str]:
    return set(db.execute(select(Completion.segment_id).distinct()).scalars().all())


def metrics(db: Session, ns: NetworkService) -> dict:
    """The three home-dashboard numbers (§4), each with its definition attached.

    The definitions travel with the numbers on purpose. "42% prayed for" means nothing
    without knowing what is in the denominator, and this project has spent two phases
    establishing that the denominator is contestable.
    """
    done_ids = completed_segment_ids(db)
    done_idx = ns.indices(done_ids)
    req_done = [ns.net.segments[i] for i in done_idx if ns.net.segments[i].required]

    miles_done = sum(s.length_m for s in req_done) / M_PER_MILE
    denom = ns.required_denominator_miles
    households = sum(s.households for s in req_done)

    walked = db.execute(
        select(func.coalesce(func.sum(Walk.distance_miles), 0.0))
        .where(Walk.status == "COMPLETED")).scalar() or 0.0
    walkers = db.execute(
        select(func.count(func.distinct(Walk.participant_id)))
        .where(Walk.status == "COMPLETED")).scalar() or 0
    walks = db.execute(
        select(func.count(Walk.id)).where(Walk.status == "COMPLETED")).scalar() or 0

    return dict(
        network_id=ns.net.network_id,
        network_version=ns.manifest["canonical_network_version"],
        percent_prayed_for=dict(
            value=round(100.0 * miles_done / denom, 1) if denom else 0.0,
            numerator_miles=round(miles_done, 2),
            denominator_miles=round(denom, 2),
            definition=(
                "Required mileage recorded as prayed for, divided by all required "
                "mileage in the denominator. Required means public streets, confirmed "
                "town trails, and one canonical pedestrian corridor per campus street. "
                "Excluded private drives, limited-access highways and the gated Smart "
                "Road are not in either half. Mileage in areas nobody may lawfully "
                "walk is removed from the denominator; mileage we simply cannot route "
                "to on its own is not."),
        ),
        total_miles_walked=dict(
            value=round(float(walked), 1),
            definition=(
                "The sum of the planned length of every completed walk. This counts "
                "the whole walk including approach and the way home, so it is larger "
                "than the required mileage covered — it is how far people walked, not "
                "how much ground was newly covered."),
        ),
        estimated_households_prayed_for=dict(
            value=households,
            total=ns.total_households_on_required,
            definition=(
                "An ESTIMATE. Dwelling units from the town's 911 address points, "
                "deduplicated, each associated with one required street or trail "
                "segment, counted once when that segment is recorded as prayed for. "
                "It is a count of residential units, not of occupied households, and "
                "no occupancy model is applied. Units inside apartment complexes with "
                "no mapped internal walkway are held out entirely rather than assigned "
                "to a frontage street."),
            held_for_review=ns.net.stats["households_held"],
        ),
        required_segments_total=ns.net.stats["required_segments"],
        required_segments_complete=len(req_done),
        completed_walks=walks,
        distinct_walkers=walkers,
        mileage_breakdown=ns.manifest["mileage"],
    )
