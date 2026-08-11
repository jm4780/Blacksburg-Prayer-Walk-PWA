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

import math
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

# What an administrator may record that a walker may not. `DIFFERENT_ROUTE` is a walk
# that happened without the app at all — somebody walked, told us afterwards, and an
# administrator entered it. It is already written to `Walk.outcome` by
# /api/admin/completions/record, so the vocabulary has always contained it; only this
# allow-list did not, which meant that endpoint raised ValueError and returned a 500
# every time it was called. It is kept out of OUTCOMES rather than added to it so the
# walker-facing handler cannot accept it from a request body.
ADMIN_OUTCOMES = {
    "DIFFERENT_ROUTE": "Recorded by an administrator for a walk taken without the app.",
}

# How far off the planned route an edited submission may reach: a quarter of a mile.
#
# An EDITED submission used to be unbounded. It was filtered to segment ids that exist
# and are REQUIRED, and nothing checked that they had anything to do with the walk — a
# reviewer credited three streets on the far side of Blacksburg against a downtown walk
# by naming them in the request. The screen only ever offers streets on and around the
# route, so this is not something a walker does by accident; what it means is that the
# town's coverage record could be moved by a request that no walk supports.
#
# A quarter mile is chosen to be generous to the walk that actually happened. Skipping
# the planned block and walking the next street over, cutting through to the parallel
# road, finishing along the far side of the park: all of those are a hundred metres or
# two from the route and all of them stay allowed. Nothing three streets away is
# refused. What is refused is a claim about somewhere the walker demonstrably was not.
EDIT_RADIUS_M = 402.0

# Anchors are taken every 200 m along the planned route, so a long straight segment with
# only two vertices is measured from along its length rather than from its ends.
_ANCHOR_STEP_M = 200.0

_M_PER_DEG_LAT = 111_320.0


def _lon_scale(lat: float) -> float:
    return _M_PER_DEG_LAT * math.cos(math.radians(lat))


def _route_anchors(ns: NetworkService, walk: Walk) -> tuple[dict, float, float]:
    """Points along the planned route, bucketed into quarter-mile cells.

    Returns the buckets, the metres-per-degree-of-longitude used to build them, and the
    cell size, so a candidate can be tested against the nine cells around it rather than
    against every point on the route.
    """
    pts: list[tuple[float, float]] = []
    for sid in walk.planned_segment_ids:
        i = ns.idx_of_id.get(sid)
        if i is None:
            continue
        coords = ns.net.segments[i].coords
        for a, b in zip(coords, coords[1:]):
            pts.append((a[0], a[1]))
            # Densify: a two-vertex segment half a mile long would otherwise only be
            # measured from its endpoints.
            scale = _lon_scale(a[1])
            dx = (b[0] - a[0]) * scale
            dy = (b[1] - a[1]) * _M_PER_DEG_LAT
            span = math.hypot(dx, dy)
            for k in range(1, int(span // _ANCHOR_STEP_M) + 1):
                t = k * _ANCHOR_STEP_M / span
                pts.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
        if coords:
            pts.append((coords[-1][0], coords[-1][1]))

    if not pts:
        return {}, _lon_scale(37.23), EDIT_RADIUS_M
    scale = _lon_scale(sum(p[1] for p in pts) / len(pts))
    cell = EDIT_RADIUS_M
    buckets: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for lon, lat in pts:
        x, y = lon * scale, lat * _M_PER_DEG_LAT
        buckets.setdefault((int(x // cell), int(y // cell)), []).append((x, y))
    return buckets, scale, cell


def unsupported_edits(ns: NetworkService, walk: Walk,
                      segment_ids: list[str] | None) -> list[str]:
    """Which of these segment ids this walk cannot support (§14).

    In bounds: anything the walk planned — required obligations and the connectors it
    was routed along — plus anything whose own geometry comes within `EDIT_RADIUS_M` of
    that route. Out of bounds: everything else, returned in the order it was submitted.

    Ids the network does not know are not reported here. They earn nothing either way —
    `record` drops them — and a walker cannot act on "this id does not exist".

    A pure function of the frozen network and the stored plan, so the rule can be
    checked before anything is written and asserted directly in a test.
    """
    ids = [s for s in (segment_ids or []) if s in ns.idx_of_id]
    planned = set(walk.planned_segment_ids) | set(walk.planned_required_ids)
    candidates = [s for s in ids if s not in planned]
    if not candidates:
        return []

    buckets, scale, cell = _route_anchors(ns, walk)
    if not buckets:
        return candidates

    return [sid for sid in candidates
            if not _near_route(ns.net.segments[ns.idx_of_id[sid]].coords,
                               buckets, scale, cell)]


def _near_route(coords, buckets: dict, scale: float, cell: float) -> bool:
    """Does any point of this street come within the radius of the route?

    Only the nine cells around each point are examined, so a street on the far side of
    town costs nine dictionary misses rather than a scan of the whole route.
    """
    r2 = EDIT_RADIUS_M ** 2
    for lon, lat in coords:
        x, y = lon * scale, lat * _M_PER_DEG_LAT
        cx, cy = int(x // cell), int(y // cell)
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for ax, ay in buckets.get((gx, gy), ()):
                    if (ax - x) ** 2 + (ay - y) ** 2 <= r2:
                        return True
    return False


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
    if outcome not in OUTCOMES and outcome not in ADMIN_OUTCOMES:
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
        if outcome == "EDITED":
            # The router refuses an out-of-bounds submission outright, so the walker
            # hears about it rather than having part of their answer quietly dropped.
            # This is the backstop: no path through this module may credit a street the
            # walk cannot support, whoever calls it and whatever they were told.
            # DIFFERENT_ROUTE is exempt — an administrator recording a walk taken
            # without the app has no route to be near.
            unsupported = set(unsupported_edits(ns, walk, chosen))
            chosen = [s for s in chosen if s not in unsupported]

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
