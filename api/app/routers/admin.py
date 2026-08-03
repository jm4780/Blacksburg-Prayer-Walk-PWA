"""Minimal administration (§17).

Eleven capabilities, all of them read-mostly. The two that can move the town-wide
number — reversing a completion and recording one walked offline — write an
AdminAction row first, because a number that can be edited without a trace is a number
nobody can defend.

  1  view submitted walks
  2  view manual route edits
  3  correct a walk submission
  4  correct segment completion (reverse, or record one walked offline)
  5  release or inspect reservations
  6  review participant duplicates
  7  inspect route-generation failures
  8  view network and engine versions
  9  review the eight Corporate Research Center crossings
 10  export aggregate pilot data
 11  town-wide progress and deployment posture, including the licensing gate

Deliberately absent: anything that reads one named participant's routes. An
administrator can see that Jane has completed four walks; they cannot pull up where
she walked. That is not an oversight — §16 forbids tying routes to names, and an
admin screen is the obvious place that rule would leak.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ...routing import network as net_mod
from ..config import settings
from ..db import get_db
from ..deps import require_admin
from ..models import (AdminAction, Completion, Participant, Reservation,
                      RouteFeedback, RouteRequest, Walk, WalkEdit)
from ..services import completion as completion_svc
from ..services import reservations as res_svc
from ..services.network_state import network_service

router = APIRouter(prefix="/api/admin", tags=["admin"],
                   dependencies=[Depends(require_admin)])


def _audit(db: Session, actor: Participant, action: str, target: str | None,
           detail: dict) -> None:
    db.add(AdminAction(actor_id=actor.id, action=action, target=target, detail=detail))


# 1 ---------------------------------------------------------------------------
@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    ns = network_service()
    return dict(metrics=completion_svc.metrics(db, ns),
                components=ns.component_summary,
                participants=db.execute(select(func.count(Participant.id))).scalar(),
                walks_by_status=dict(db.execute(
                    select(Walk.status, func.count(Walk.id)).group_by(Walk.status)).all()))


# 2 --- view manual route edits ------------------------------------------------
@router.get("/walk-edits")
def walk_edits(limit: int = 200, db: Session = Depends(get_db)):
    """Every manual change a walker made to a plan, as a diff.

    This is the screen that answers "is anyone gaming the numbers?" — not by naming
    people, but by showing whether manual additions are concentrated somewhere odd.
    """
    rows = db.execute(select(WalkEdit).order_by(WalkEdit.created_at.desc())
                      .limit(min(limit, 1000))).scalars().all()
    by_walk: dict = {}
    for e in rows:
        w = by_walk.setdefault(e.walk_id, dict(walk_id=e.walk_id, added=[], removed=[],
                                               at=e.created_at.isoformat()))
        (w["added"] if e.kind == "ADDED" else w["removed"]).append(e.segment_id)
    return dict(edited_walks=len(by_walk), edits=len(rows),
                walks=sorted(by_walk.values(), key=lambda w: w["at"], reverse=True))


# 3 --- correct a walk submission ----------------------------------------------
@router.post("/walks/{walk_id}/correct")
def correct_walk(walk_id: str, outcome: str, reason: str,
                 segment_ids: list[str] | None = None,
                 actor: Participant = Depends(require_admin),
                 db: Session = Depends(get_db)):
    """Re-record a walk's outcome. Audited, and the plan is still never rewritten.

    Existing completions for the walk are cleared first, because a correction that
    could only ever *add* would make an over-claim uncorrectable.
    """
    from ..services import completion as csvc
    if not reason or len(reason.strip()) < 5:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "a reason is required to correct a walk")
    walk = db.get(Walk, walk_id)
    if walk is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown walk")
    if outcome not in csvc.OUTCOMES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"outcome must be one of {sorted(csvc.OUTCOMES)}")
    before = db.execute(select(func.count(Completion.id))
                        .where(Completion.walk_id == walk_id)).scalar() or 0
    _audit(db, actor, "correct_walk", walk_id,
           dict(from_outcome=walk.outcome, to_outcome=outcome,
                completions_cleared=before, reason=reason.strip()))
    db.execute(delete(Completion).where(Completion.walk_id == walk_id))
    walk.manual_additions, walk.manual_removals = [], []
    db.commit()
    result = csvc.record(db, network_service(), walk, outcome, segment_ids, reason)
    db.commit()
    return dict(corrected=walk_id, completions_cleared=before, **result)


# 6 --- review participant duplicates ------------------------------------------
@router.get("/participant-duplicates")
def participant_duplicates(db: Session = Depends(get_db)):
    """Likely duplicate people.

    Normalized email already prevents exact duplicates, so what is left is the cases
    the normalizer deliberately does NOT merge: same name on two addresses, and
    plus-tagged variants of one mailbox. Both are surfaced for a human, because
    merging them automatically would risk attributing one person's walks to another.
    """
    people = db.execute(select(Participant)).scalars().all()
    by_name: dict = {}
    by_mailbox: dict = {}
    for p in people:
        by_name.setdefault(
            f"{p.first_name.strip().lower()} {p.last_name.strip().lower()}", []).append(p)
        local, _, domain = p.email_normalized.partition("@")
        by_mailbox.setdefault(f"{local.split('+')[0]}@{domain}", []).append(p)

    def pack(group):
        return [dict(id=x.id, first_name=x.first_name, last_name=x.last_name,
                     email=x.email, created_at=x.created_at.isoformat()) for x in group]

    return dict(
        same_name=[dict(key=k, participants=pack(v))
                   for k, v in by_name.items() if len(v) > 1],
        same_mailbox_different_tag=[dict(key=k, participants=pack(v))
                                    for k, v in by_mailbox.items() if len(v) > 1],
        note=("Nothing here is merged automatically. Plus-tagged addresses are treated "
              "as distinct people on purpose — collapsing them is provider-specific "
              "and getting it wrong attributes one person's walks to another."),
    )


# 7 --- inspect route-generation failures --------------------------------------
@router.get("/route-failures")
def route_failures(limit: int = 100, db: Session = Depends(get_db)):
    """Requests that produced no usable route, with everything needed to reproduce."""
    rows = db.execute(
        select(RouteRequest).where(RouteRequest.failure_reason.isnot(None))
        .order_by(RouteRequest.created_at.desc()).limit(min(limit, 500))).scalars().all()
    return dict(
        failures=len(rows),
        by_reason=_count_rows(rows, "failure_reason"),
        by_coverage_area=_count_rows(rows, "coverage_area_id"),
        requests=[dict(id=r.id, reason=r.failure_reason,
                       coverage_area_id=r.coverage_area_id,
                       start_node=r.start_node, start_source=r.start_source,
                       seed=r.seed, network_id=r.network_id,
                       engine_version=r.engine_version,
                       completion_state_version=r.completion_state_version,
                       active_reservations=r.active_reservation_count,
                       created_at=r.created_at.isoformat())
                  for r in rows],
        reproduce=("POST /api/routes/generate with the same seed from the same start "
                   "node reproduces the failure, provided completion_state_version "
                   "still matches."))


def _count_rows(rows, attr):
    out: dict = {}
    for r in rows:
        k = getattr(r, attr)
        out[str(k)] = out.get(str(k), 0) + 1
    return out


@router.get("/participants")
def participants(db: Session = Depends(get_db)):
    rows = db.execute(
        select(Participant.id, Participant.first_name, Participant.last_name,
               Participant.email, Participant.is_admin, Participant.created_at,
               Participant.last_seen_at,
               func.count(Walk.id).filter(Walk.status == "COMPLETED"))
        .outerjoin(Walk, Walk.participant_id == Participant.id)
        .group_by(Participant.id).order_by(Participant.created_at.desc())).all()
    return [dict(id=r[0], first_name=r[1], last_name=r[2], email=r[3], is_admin=r[4],
                 created_at=r[5].isoformat(), last_seen_at=r[6].isoformat(),
                 completed_walks=r[7]) for r in rows]


# 3 ---------------------------------------------------------------------------
@router.get("/walks")
def walks(status_filter: str | None = None, limit: int = 100,
          db: Session = Depends(get_db)):
    q = select(Walk).order_by(Walk.created_at.desc()).limit(min(limit, 500))
    if status_filter:
        q = q.where(Walk.status == status_filter)
    return [dict(id=w.id, status=w.status, band=w.band,
                 distance_miles=w.distance_miles, outcome=w.outcome,
                 network_id=w.network_id, engine_version=w.engine_version,
                 required_segments=len(w.planned_required_ids),
                 created_at=w.created_at.isoformat(),
                 # participant id only — never the name, see the module docstring
                 participant_id=w.participant_id)
            for w in db.execute(q).scalars()]


# 4 ---------------------------------------------------------------------------
@router.get("/reservations")
def reservations(db: Session = Depends(get_db)):
    res_svc.purge_expired(db)
    now = datetime.now(timezone.utc)
    rows = db.execute(select(Reservation).where(Reservation.released_at.is_(None),
                                                Reservation.expires_at > now)).scalars()
    by_walk: dict[str, dict] = {}
    for r in rows:
        e = by_walk.setdefault(r.walk_id, dict(walk_id=r.walk_id, segments=0,
                                               expires_at=r.expires_at.isoformat()))
        e["segments"] += 1
    return list(by_walk.values())


@router.post("/reservations/release/{walk_id}")
def release_reservation(walk_id: str, actor: Participant = Depends(require_admin),
                        db: Session = Depends(get_db)):
    walk = db.get(Walk, walk_id)
    if walk is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown walk")
    n = res_svc.release(db, walk)
    _audit(db, actor, "release_reservations", walk_id, dict(released=n))
    db.commit()
    return dict(walk_id=walk_id, released=n)


# 5 ---------------------------------------------------------------------------
@router.post("/completions/reverse")
def reverse_completion(segment_id: str, reason: str,
                       actor: Participant = Depends(require_admin),
                       db: Session = Depends(get_db)):
    """Remove every completion of one segment. Moves the town-wide number, so it is
    audited before it is applied."""
    if not reason or len(reason.strip()) < 5:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "a reason is required to reverse a completion")
    n = db.execute(select(func.count(Completion.id))
                   .where(Completion.segment_id == segment_id)).scalar() or 0
    if not n:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"{segment_id} is not recorded as prayed for")
    _audit(db, actor, "reverse_completion", segment_id,
           dict(rows_removed=n, reason=reason.strip()))
    db.execute(delete(Completion).where(Completion.segment_id == segment_id))
    db.commit()
    return dict(segment_id=segment_id, rows_removed=n)


# 6 ---------------------------------------------------------------------------
@router.post("/completions/record")
def record_offline(segment_ids: list[str], reason: str,
                   actor: Participant = Depends(require_admin),
                   db: Session = Depends(get_db)):
    """Record segments walked without the app — a paper sign-up sheet, a group walk.

    Attributed to a synthetic walk owned by the administrator, so these rows are
    distinguishable from app-recorded ones rather than blended into them.
    """
    ns = network_service()
    valid = [s for s in segment_ids
             if s in ns.idx_of_id and ns.net.segments[ns.idx_of_id[s]].required]
    if not valid:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "no valid REQUIRED segment ids in the request")
    walk = Walk(participant_id=actor.id, request_id="", network_id=ns.net.network_id,
                engine_version="ADMIN", status="COMPLETED", band="OFFLINE",
                target_miles=0.0,
                distance_miles=round(sum(ns.net.segments[ns.idx_of_id[s]].miles
                                         for s in valid), 3),
                estimated_minutes=0, planned_segment_ids=valid,
                planned_required_ids=valid, score_components={},
                outcome="DIFFERENT_ROUTE", note=f"Recorded by administrator: {reason}",
                resolved_at=datetime.now(timezone.utc))
    db.add(walk)
    db.commit()
    result = completion_svc.record(db, ns, walk, "DIFFERENT_ROUTE", valid, reason)
    _audit(db, actor, "record_offline_completion", walk.id,
           dict(segments=len(valid), reason=reason))
    db.commit()
    return result


# 7 ---------------------------------------------------------------------------
@router.get("/network")
def network_manifest():
    ns = network_service()
    return dict(manifest=ns.manifest,
                components=[dict(index=c.index, description=c.description,
                                 classification=c.classification,
                                 required_miles=round(c.required_miles, 3),
                                 households=c.households,
                                 supported_bands=list(c.supports_bands or []),
                                 in_denominator=c.in_denominator)
                            for c in ns.components if c.required_miles > 0.0005])


# 8 ---------------------------------------------------------------------------
@router.get("/review-queues")
def review_queues():
    """Open review items, read from the pipeline's own artifacts."""
    root = os.path.join(net_mod.OUT_ROOT, settings().snapshot_date, "review")

    def load(name):
        path = os.path.join(root, name)
        return json.load(open(path)) if os.path.exists(path) else None

    crc = load("crc-crossings.json")
    needing = load("segments-needing-review.json") or []
    return dict(
        crc_crossings=dict(
            status=crc["status"] if crc else "artifact missing",
            count=crc["counts"]["crc_crossings"] if crc else 0,
            if_promoted=crc.get("if_all_crc_crossings_were_promoted") if crc else None,
            rows=[{k: v for k, v in r.items() if k != "geometry"}
                  for r in (crc["crossings"] if crc else []) if r["touches_crc"]],
        ) if crc else None,
        segments_needing_review=dict(
            count=len(needing),
            by_status=_count_by(needing, "role_status"),
            by_role=_count_by(needing, "role"),
        ),
    )


def _count_by(rows, key):
    out: dict = {}
    for r in rows:
        out[r.get(key)] = out.get(r.get(key), 0) + 1
    return out


# 9 ---------------------------------------------------------------------------
@router.get("/deployment")
def deployment():
    s = settings()
    return dict(
        tier=s.tier,
        warnings=s.check(),
        public_geometry_enabled=s.public_geometry_enabled,
        database="sqlite" if s.database_url.startswith("sqlite") else "external",
        token_pepper_set=bool(s.token_pepper),
        licensing_gate=_licensing_gate(),
    )


def _licensing_gate() -> dict:
    return dict(
        gate="G1",
        status="UNRESOLVED — release blocker",
        summary=("No Town of Blacksburg dataset used by this project publishes any "
                 "reuse licence; copyrightText is empty on every layer. Serving "
                 "geometry derived from them to the general public is redistribution."),
        blocks=["public release of source-derived geometry",
                "publishing the progress map without authentication"],
        does_not_block=["private development deployment",
                        "a limited authenticated pilot",
                        "aggregate metrics, which contain no source geometry"],
        reference="docs/05-licensing-status.md",
    )


# 10 --------------------------------------------------------------------------
@router.get("/export")
def export_progress(db: Session = Depends(get_db)):
    """Aggregate export. Segment ids and counts — no participant, no household."""
    ns = network_service()
    done = completion_svc.completed_segment_ids(db)
    return dict(
        generated_at=datetime.now(timezone.utc).isoformat(),
        network_id=ns.net.network_id,
        metrics=completion_svc.metrics(db, ns),
        completed_segment_ids=sorted(done),
        contains=["segment ids", "aggregate counts"],
        excludes=["participant identity", "household coordinates", "addresses",
                  "per-segment household counts"],
    )


# --- pilot summary (Phase 3.1 §6) --------------------------------------------
@router.get("/pilot-summary")
def pilot_summary(db: Session = Depends(get_db)):
    """One screen for running a three-to-five-person pilot.

    Everything here is a count or an average. No participant appears by name against a
    route, and no starting point is reported more precisely than the routing component
    it fell in — §8 forbids exposing precise participant location, and a coverage-area
    id is the coarsest thing that still answers "where are people walking?".
    """
    ns = network_service()

    walks = db.execute(select(Walk)).scalars().all()
    by_status = _tally(w.status for w in walks)
    resolved = [w for w in walks if w.status in ("COMPLETED", "DISCARDED")]
    completed = [w for w in walks if w.status == "COMPLETED"]
    did_not = [w for w in completed if w.outcome == "DID_NOT_COMPLETE"]
    edited = [w for w in completed if w.outcome == "EDITED"]

    fb = db.execute(select(RouteFeedback)).scalars().all()
    ratings = [f.rating for f in fb]
    flagged = [f for f in fb if f.had_bad_connection]
    # Response rate needs a denominator that can actually contain its numerator.
    # Dividing all feedback by submitted walks gave 200% in the pilot screenshot,
    # because feedback can be left from the active-walk screen before the walk is
    # submitted — and a rate above 100% discredits every other number beside it.
    completed_ids = {w.id for w in completed}
    fb_on_completed = {f.walk_id for f in fb if f.walk_id in completed_ids}

    reqs = db.execute(select(RouteRequest)).scalars().all()
    failures = [r for r in reqs if r.failure_reason]

    # Late-opportunity states actually served, read off the stored variant payloads.
    states: dict = {}
    for r in reqs:
        for v in (r.variants or []):
            st = v.get("state")
            if st:
                states[st] = states.get(st, 0) + 1

    edits = db.execute(select(WalkEdit)).scalars().all()

    return dict(
        network=dict(id=ns.net.network_id,
                     version=ns.manifest["canonical_network_version"],
                     engine_version=_engine_version()),
        participants=dict(
            total=db.execute(select(func.count(Participant.id))).scalar() or 0,
            with_a_completed_walk=len({w.participant_id for w in completed}),
        ),
        walks=dict(
            total=len(walks), by_status=by_status,
            submitted=len(completed),
            discarded=by_status.get("DISCARDED", 0),
            in_progress=by_status.get("ACTIVE", 0) + by_status.get("PREVIEW", 0),
            completion_rate=(round(len(completed) / len(resolved), 3)
                             if resolved else None),
            completion_rate_definition=(
                "submitted walks divided by walks that reached a terminal state "
                "(submitted + discarded). Walks still in progress are excluded rather "
                "than counted as failures."),
            reported_not_completed=len(did_not),
            edited=len(edited),
            by_band=_tally(w.band for w in completed),
        ),
        manual_edits=dict(
            walks_with_edits=len({e.walk_id for e in edits}),
            segments_added=sum(1 for e in edits if e.kind == "ADDED"),
            segments_removed=sum(1 for e in edits if e.kind == "REMOVED"),
        ),
        feedback=dict(
            responses=len(fb),
            responses_on_submitted_walks=len(fb_on_completed),
            responses_on_walks_still_in_progress=len(fb) - len(fb_on_completed),
            response_rate=(round(len(fb_on_completed) / len(completed), 3)
                           if completed else None),
            response_rate_definition=(
                "submitted walks that have feedback, divided by submitted walks. "
                "Feedback left mid-walk on a walk that has not been submitted is "
                "counted in `responses` but not in this rate."),
            average_rating=(round(sum(ratings) / len(ratings), 2) if ratings else None),
            rating_distribution=_tally(str(r) for r in ratings),
            easy_to_follow=_tally_bool(f.easy_to_follow for f in fb),
            time_felt_accurate=_tally_bool(f.time_felt_accurate for f in fb),
            flagged_unsafe_or_incorrect=len(flagged),
            flagged=[dict(walk_id=f.walk_id, band=f.band,
                          coverage_area_id=f.coverage_area_id,
                          detail=f.bad_connection_detail,
                          reproduce=dict(seed=f.seed, start_node=f.start_node,
                                         network_version=f.network_version,
                                         engine_version=f.engine_version,
                                         band=f.band))
                     for f in flagged],
        ),
        route_generation=dict(
            requests=len(reqs),
            failures=len(failures),
            failure_rate=(round(len(failures) / len(reqs), 3) if reqs else None),
            by_reason=_tally(r.failure_reason for r in failures),
        ),
        late_opportunity_states=states,
        coverage_areas=_tally(r.coverage_area_id for r in reqs),
        starting_areas_note=(
            "Reported as routing components, never as coordinates. A component is "
            "hundreds of acres; a start point is somebody's front door."),
    )


def _tally(values):
    out: dict = {}
    for v in values:
        if v is None:
            continue
        out[str(v)] = out.get(str(v), 0) + 1
    return dict(sorted(out.items(), key=lambda x: -x[1]))


def _tally_bool(values):
    vals = [v for v in values if v is not None]
    return dict(yes=sum(1 for v in vals if v), no=sum(1 for v in vals if not v),
                unanswered=0)


def _engine_version():
    from ...routing.engine import ENGINE_VERSION
    return ENGINE_VERSION


# --- pilot route feedback ----------------------------------------------------
@router.get("/feedback")
def all_feedback(limit: int = 200, db: Session = Depends(get_db)):
    rows = db.execute(select(RouteFeedback).order_by(RouteFeedback.created_at.desc())
                      .limit(min(limit, 1000))).scalars().all()
    return [dict(id=f.id, walk_id=f.walk_id, rating=f.rating,
                 easy_to_follow=f.easy_to_follow,
                 time_felt_accurate=f.time_felt_accurate,
                 had_bad_connection=f.had_bad_connection,
                 bad_connection_detail=f.bad_connection_detail,
                 completed_as_planned=f.completed_as_planned,
                 comment=f.comment, band=f.band,
                 submitted_from=f.submitted_from,
                 coverage_area_id=f.coverage_area_id,
                 created_at=f.created_at.isoformat(),
                 reproduce=dict(network_id=f.network_id,
                                network_version=f.network_version,
                                engine_version=f.engine_version, seed=f.seed,
                                start_node=f.start_node, band=f.band))
            for f in rows]


# --- connector candidates ----------------------------------------------------
@router.get("/connector-candidates")
def connector_candidates():
    """The prioritised campus-edge connector review (Phase 3.1 §3)."""
    path = os.path.join(net_mod.OUT_ROOT, settings().snapshot_date, "review",
                        "connector-candidates.json")
    if not os.path.exists(path):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "run python3 -m pipeline.build.connector_candidates")
    data = json.load(open(path))
    return dict(
        generated_at=data["generated_at"],
        network_version=data["network_version"],
        basemap_evidence=data["basemap_evidence"],
        candidates=data["candidates"], promoted=data["promoted"],
        component_stats=data["component_stats"],
        rows=[{k: v for k, v in r.items() if k not in ("component_a", "component_b")}
              for r in data["rows"]],
    )


# 11 --------------------------------------------------------------------------
@router.get("/audit")
def audit_log(limit: int = 200, db: Session = Depends(get_db)):
    rows = db.execute(select(AdminAction).order_by(AdminAction.created_at.desc())
                      .limit(min(limit, 1000))).scalars()
    return [dict(id=a.id, actor_id=a.actor_id, action=a.action, target=a.target,
                 detail=a.detail, created_at=a.created_at.isoformat()) for a in rows]
