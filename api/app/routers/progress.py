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

import json
import os
from functools import lru_cache

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import geometry_or_403
from ..schemas import MetricsOut
from ..services import completion as completion_svc
from ..services import reservations as res_svc
from ..services.network_state import network_service

router = APIRouter(prefix="/api/progress", tags=["progress"])


# Road classes worth drawing as context. US 460 and its ramps are the single most
# recognisable thing in Blacksburg; the Smart Road and the service drives orient the
# campus edge. Everything here is a public road.
_CONTEXT_CLASSES = {"Primary", "Ramp", "Service Drive", "Local", "Arterial",
                    "Secondary", "Collector"}


@lru_cache
def _context_roads() -> dict:
    """Roads that are NOT part of the obligation, drawn only so the town is legible.

    The map drew the 1,582 required segments and nothing else, which made Blacksburg
    look like a network diagram rather than a place — the bypass, the ramps and the
    campus service roads simply absent. You cannot orient yourself in a town whose
    landmarks have been deleted, and removing the world is not the same as letting the
    prayer data lead it.

    **Public roads only.** The 224 private drives and everything marked PRIVATE or
    GATED are left out: they lead to individual houses, they add nothing anybody
    navigates by, and drawing them would put residential specificity on a public map
    to no purpose.

    These carry no id and no name. They are never selectable, never routable, never
    counted. The one attribute is whether a road is big enough to navigate by, which
    is all the cartography needs to know to decide how faintly to draw it.
    """
    import glob

    from ...routing import network as net_mod
    files = sorted(glob.glob(os.path.join(net_mod.OUT_ROOT, "*", "segments.geojson")))
    if not files:
        return {"type": "FeatureCollection", "features": []}
    try:
        with open(files[-1]) as f:
            fc = json.load(f)
    except (OSError, ValueError):
        return {"type": "FeatureCollection", "features": []}

    feats = []
    for feat in fc.get("features", []):
        p = feat.get("properties") or {}
        if p.get("role") == "REQUIRED":
            continue                      # drawn as prayer data, not as ground
        if p.get("access_type") in ("PRIVATE", "GATED"):
            continue
        rc = p.get("road_class")
        keep = rc in _CONTEXT_CLASSES or p.get("role") == "OPTIONAL_CONNECTOR"
        if not keep:
            continue
        g = feat.get("geometry") or {}
        if g.get("type") != "LineString":
            continue
        feats.append({
            "type": "Feature",
            # Half the precision. This is a background wash; six decimal places of a
            # road nobody can tap is bytes a phone downloads on a hillside.
            "geometry": {"type": "LineString",
                         "coordinates": [[round(x, 5), round(y, 5)]
                                         for x, y in g["coordinates"]]},
            "properties": {"major": rc in ("Primary", "Arterial", "Ramp")},
        })
    return {"type": "FeatureCollection", "features": feats}


@lru_cache
def _open_space() -> dict | None:
    """Public parks, for map context (Prayer Walk map system, docs/20 §3).

    Only Town-owned open space — 96 of the 375 polygons in the source. The rest are
    HOA and privately owned, which are neither places a walker may go nor things
    worth drawing on a map about public streets.

    Simplified hard on the way out. This is a background wash at town scale, not a
    parcel boundary: full precision would triple the payload to render a shape nobody
    reads. Same snapshot-at-runtime rule as the boundary below — never committed.
    """
    import glob

    from ...routing import network as net_mod
    root = os.path.join(os.path.dirname(net_mod.OUT_ROOT), "snapshots", "openspace")
    files = sorted(glob.glob(os.path.join(root, "*.geojson")))
    if not files:
        return None

    def thin(ring: list) -> list:
        out = [[round(x, 5), round(y, 5)] for i, (x, y) in enumerate(ring)
               if i % 3 == 0 or i == len(ring) - 1]
        # A ring with fewer than four points is not a polygon any more.
        return out if len(out) >= 4 else [[round(x, 5), round(y, 5)] for x, y in ring]

    try:
        with open(files[-1]) as f:
            fc = json.load(f)
        feats = []
        for feat in fc.get("features", []):
            if not str((feat.get("properties") or {}).get("Type", "")).startswith("Town"):
                continue
            g = feat.get("geometry") or {}
            t = g.get("type")
            if t == "Polygon":
                coords = [thin(r) for r in g["coordinates"]]
            elif t == "MultiPolygon":
                coords = [[thin(r) for r in poly] for poly in g["coordinates"]]
            else:
                continue
            feats.append({"type": "Feature", "properties": {},
                          "geometry": {"type": t, "coordinates": coords}})
        return {"type": "FeatureCollection", "features": feats} if feats else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


@lru_cache
def _boundary() -> dict | None:
    """The town outline, for map context (§16).

    Read from the source snapshot at runtime rather than committed. The snapshot is an
    internal application dependency — a deployment runs `pipeline.sources.fetch` and
    has it; the repository does not carry a copy. If it is absent the map simply draws
    without an outline, which is a cosmetic loss, not a broken screen.
    """
    import glob

    from ...routing import network as net_mod
    root = os.path.join(os.path.dirname(net_mod.OUT_ROOT), "snapshots", "boundary")
    files = sorted(glob.glob(os.path.join(root, "*.geojson")))
    if not files:
        return None
    try:
        with open(files[-1]) as f:
            fc = json.load(f)
        rings: list = []
        for feat in fc.get("features", []):
            g = feat.get("geometry") or {}
            if g.get("type") == "Polygon":
                rings.append(g["coordinates"][0])
            elif g.get("type") == "MultiPolygon":
                rings.extend(poly[0] for poly in g["coordinates"])
        # Thin the outline: the source ring runs to thousands of vertices and the map
        # is drawn a few hundred pixels wide.
        return {"type": "MultiLineString",
                "coordinates": [r[::4] + [r[-1]] for r in rings if len(r) > 8]} or None
    except (OSError, ValueError, KeyError, IndexError):
        return None


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
                # Cartography, not routing: the map system's width ramp and label
                # filter read these. See docs/20 §4.
                "road_class": s.road_class,
                "path_type": s.path_type,
                # The neighbourhood this street sits in, for the map's own labels —
                # TOM'S CREEK, GRISSOM / HIGHLAND. It is a name, not a geometry: the
                # map derives each label's anchor from the segments that carry it, so
                # no neighbourhood boundary is ever sent. It rides this endpoint
                # because this endpoint is already the G1 gate; a static file next to
                # the basemap would publish Town-derived data (docs/05).
                "neighborhood": s.neighborhood,
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
        "boundary": _boundary(),
        "open_space": _open_space(),
        "context": _context_roads(),
        "excludes": ["household points", "residential addresses",
                     "per-segment household counts", "participant identity",
                     "parallel campus walkways (ALTERNATIVE)",
                     "excluded private drives and limited-access roads",
                     "the connector network"],
    }
