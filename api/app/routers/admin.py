"""Minimal administration (§17).

Eleven capabilities, all of them read-mostly. The two that can move the town-wide
number — reversing a completion and recording one walked offline — write an
AdminAction row first, because a number that can be edited without a trace is a number
nobody can defend.

  1  town-wide progress, with definitions
  2  participant roster (counts and activity, no walk-level detail per person)
  3  walk log, filterable by status
  4  live reservations, and release one
  5  reverse a completion
  6  record a segment walked offline
  7  the frozen network manifest and version
  8  review queues: CRC crossings, segments still needing review
  9  deployment posture and the licensing gate
 10  aggregate progress export
 11  the admin audit log

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
from ..models import AdminAction, Completion, Participant, Reservation, Walk
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


# 2 ---------------------------------------------------------------------------
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


# 11 --------------------------------------------------------------------------
@router.get("/audit")
def audit_log(limit: int = 200, db: Session = Depends(get_db)):
    rows = db.execute(select(AdminAction).order_by(AdminAction.created_at.desc())
                      .limit(min(limit, 1000))).scalars()
    return [dict(id=a.id, actor_id=a.actor_id, action=a.action, target=a.target,
                 detail=a.detail, created_at=a.created_at.isoformat()) for a in rows]
