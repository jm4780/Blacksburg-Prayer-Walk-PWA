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

from ..models import Completion, Walk, WalkEdit
from .network_state import NetworkService

M_PER_MILE = 1609.344

OUTCOMES = {
    "AS_PLANNED": "Walked the route as shown.",
    "EDITED": "Walked it with changes — some obligations skipped, others added.",
    "DID_NOT_COMPLETE": "Did not complete the walk.",
}


def record(db: Session, ns: NetworkService, walk: Walk, outcome: str,
           segment_ids: list[str] | None, note: str | None = None) -> dict:
    """Write completions for one walk. Idempotent (§15).

    Three outcomes, matching the three actions §14 offers:

      AS_PLANNED        the plan is the answer; `segment_ids` is ignored
      EDITED            `segment_ids` is the walker's final list. It may drop planned
                        obligations and add nearby ones in the same submission — the
                        diff against the plan is stored as manual removals and
                        additions, so an administrator sees what changed rather than
                        two opaque lists.
      DID_NOT_COMPLETE  nothing is recorded, reservations are released by the caller,
                        and only the minimal audit trail survives.

    Selection is always by segment or canonical obligation, never freehand: a drawn
    line would have to be map-matched back onto the network, and every match would be
    a silent guess about what somebody prayed for.
    """
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown outcome {outcome!r}")

    planned = list(walk.planned_required_ids)
    now = datetime.now(timezone.utc)

    if outcome == "DID_NOT_COMPLETE":
        # No completions, no coverage, no distance. §14: preserve only the minimal
        # audit data needed for debugging.
        walk.status = "COMPLETED"
        walk.outcome = outcome
        walk.note = note or None
        walk.resolved_at = now
        walk.final_segment_ids = []
        walk.manual_removals = planned
        walk.manual_additions = []
        walk.final_distance_miles = 0.0
        for sid in planned:
            db.add(WalkEdit(walk_id=walk.id, participant_id=walk.participant_id,
                            kind="REMOVED", segment_id=sid))
        db.commit()
        return dict(walk_id=walk.id, outcome=outcome, segments_recorded=0,
                    segments_newly_recorded=0, segments_already_recorded=0,
                    campus_credited_segments=0, idempotent=True, miles_credited=0.0,
                    manual_additions=0, manual_removals=len(planned),
                    final_distance_miles=0.0)

    if outcome == "AS_PLANNED":
        chosen = planned
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

    planned_set = set(planned)
    final_required = {ns.id_of_idx[i] for i in required_idx | credited}
    additions = sorted(final_required - planned_set)
    removals = sorted(planned_set - final_required)

    new = 0
    for i in sorted(required_idx | credited):
        sid = ns.id_of_idx[i]
        if sid in existing:
            continue
        db.add(Completion(
            walk_id=walk.id, participant_id=walk.participant_id, segment_id=sid,
            network_id=walk.network_id,
            source=("AS_PLANNED" if outcome == "AS_PLANNED"
                    else "MANUAL_ADDITION" if sid in additions else "EDITED"),
            via_alternative=i in credited))
        new += 1

    # Only record edit rows once — a repeat submission must not duplicate the audit
    # trail any more than it duplicates the completions.
    if not walk.manual_additions and not walk.manual_removals:
        for sid in additions:
            db.add(WalkEdit(walk_id=walk.id, participant_id=walk.participant_id,
                            kind="ADDED", segment_id=sid))
        for sid in removals:
            db.add(WalkEdit(walk_id=walk.id, participant_id=walk.participant_id,
                            kind="REMOVED", segment_id=sid))

    # §4: total miles walked is the *submitted route distance*, including repeated
    # travel and connectors. For an unedited walk that is the plan's full distance.
    # For an edited one it is the required mileage actually claimed plus the plan's
    # connector mileage, which is the closest honest figure available without a trace.
    if outcome == "AS_PLANNED":
        final_distance = walk.distance_miles
    else:
        conn_m = sum(ns.net.segments[ns.idx_of_id[s]].length_m
                     for s in walk.planned_connector_ids if s in ns.idx_of_id)
        req_m = sum(ns.net.segments[i].length_m for i in required_idx)
        final_distance = round((req_m + conn_m) / M_PER_MILE, 3)

    walk.status = "COMPLETED"
    walk.outcome = outcome
    walk.note = note or None
    walk.resolved_at = now
    walk.final_segment_ids = sorted(final_required)
    walk.manual_additions = additions
    walk.manual_removals = removals
    walk.final_distance_miles = final_distance
    db.commit()

    # The town has moved, so any cached mission slate is stale.
    from . import mission_service
    mission_service.invalidate()

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
        manual_additions=len(additions),
        manual_removals=len(removals),
        final_distance_miles=final_distance,
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

    # §4: the sum of *final submitted* route distance across completed walks,
    # including repeated travel and connector mileage. Falls back to the planned
    # distance for walks recorded before final_distance_miles existed.
    walked = db.execute(
        select(func.coalesce(
            func.sum(func.coalesce(Walk.final_distance_miles, Walk.distance_miles)),
            0.0)).where(Walk.status == "COMPLETED")).scalar() or 0.0
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
