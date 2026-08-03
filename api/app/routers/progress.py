"""Home dashboard metrics and the public progress map (§4, §16).

What the progress map may show:
  - required street, trail and canonical campus geometry
  - whether each of those is recorded as prayed for
  - town-wide aggregate counts

What it must never show, and does not:
  - household point coordinates          (never sent; not even loaded here)
  - individual residential addresses     (never stored by this application)
  - per-segment household counts         (a count of 2 on a cul-de-sac identifies a
                                          household; only the town-wide total is sent)
  - participant routes tied to a name    (the map is one town-wide union, not a list
                                          of walks, and carries no participant field)
  - ALTERNATIVE campus walkways          (§16: canonical corridors only, so the map
                                          shows one obligation per corridor)
  - raw source layers                    (nothing from EXCLUDED private drives, the
                                          bypass, or the connector network)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import geometry_or_403
from ..schemas import MetricsOut
from ..services import completion as completion_svc
from ..services import reservations as res_svc
from ..services.network_state import network_service

router = APIRouter(prefix="/api/progress", tags=["progress"])


@router.get("/metrics", response_model=MetricsOut)
def metrics(db: Session = Depends(get_db)):
    """Aggregate only. Safe to serve unauthenticated: it contains no geometry and no
    residential data, just counts and their definitions."""
    return completion_svc.metrics(db, network_service())


@router.get("/map")
def progress_map(db: Session = Depends(get_db), _: bool = Depends(geometry_or_403)):
    ns = network_service()
    done = completion_svc.completed_segment_ids(db)
    held = res_svc.held_segment_ids(db)

    feats = []
    for s in ns.net.segments:
        if not s.required:
            continue
        if s.campus_obligation == "ALTERNATIVE":
            continue
        if not s.coords:
            continue
        feats.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": s.coords},
            "properties": {
                "id": s.id,
                "name": s.display_name,
                "kind": ("CAMPUS" if s.campus_obligation == "CANONICAL"
                         else s.segment_type),
                "done": s.id in done,
                # "held" carries no identity — §12 forbids exposing who holds it.
                "held": s.id in held and s.id not in done,
            },
        })
    return {
        "type": "FeatureCollection",
        "network_id": ns.net.network_id,
        "network_version": ns.manifest["canonical_network_version"],
        "features": feats,
        "excludes": ["household points", "residential addresses",
                     "per-segment household counts", "participant identity",
                     "parallel campus walkways (ALTERNATIVE)",
                     "excluded private drives and limited-access roads",
                     "the connector network"],
    }
