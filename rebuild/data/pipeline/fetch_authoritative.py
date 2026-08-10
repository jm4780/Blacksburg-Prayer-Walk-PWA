"""Replace the provisional network with the authoritative one, and light the home counter.

Run this on any host that can reach the Town of Blacksburg ArcGIS services. It
produces exactly the same artefact as extract_network.py -- rebuild/data/out/
network.geojson, same property names -- plus a real `homes` count per segment.
Nothing downstream changes. Load it with the same rebuild/db/load_network.py.

    python3 rebuild/data/pipeline/fetch_authoritative.py
    python3 rebuild/db/load_network.py

WHY THIS EXISTS
The build environment this was written in cannot reach any geodata host:
Overpass, Geofabrik, planet.osm, Town and County ArcGIS, VGIN and Census TIGER
are all refused at the egress proxy. So the shipped network is derived from the
committed Protomaps basemap, which carries real geometry and real street names
but only a three-value class field. That provisional build measures 156.54 mi
against a known-good 136.21 mi, an over-inclusion of about 14.9%, because tile
data cannot distinguish a public residential street from an apartment drive.

This module closes that gap, because the Town roads layer publishes the
ownership and classification attributes the tiles threw away.

STATUS: WRITTEN BUT NEVER EXECUTED. No host reachable from the build
environment serves these endpoints, so this code has never made a live request.
The endpoint URLs and field semantics are carried over from the previous build's
verified registry, but treat the first real run as a test run: it prints a
reconciliation against the known-good figures and refuses to overwrite the
network if the numbers come out absurd.
"""
from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

import pyproj
from shapely.geometry import LineString, Point, Polygon, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT = os.path.join(REPO, "rebuild", "data", "out")
GEOD = pyproj.Geod(ellps="WGS84")

TOB = "https://services1.arcgis.com/rAuQoDGA22NtJdmg/arcgis/rest/services"
LAYERS = {
    "roads": f"{TOB}/Address_Road_Building/FeatureServer/1",
    "address": f"{TOB}/Address_Road_Building/FeatureServer/0",
    "boundary": f"{TOB}/Administrative_Reference_Boundaries/FeatureServer/4",
}

# Sanity envelope. The town is not going to double in size between builds; if the
# authoritative fetch lands outside this, something is wrong with the request or
# the schema changed, and silently shipping it would corrupt the shared map.
SANE_MIN_MI, SANE_MAX_MI = 90.0, 190.0

UA = {"User-Agent": "blacksburg-prayer-walk/2.0"}


def _post(url: str, params: dict, tries: int = 4):
    body = urllib.parse.urlencode(params).encode()
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, data=body, headers=UA)
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read().decode())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = e
            if attempt < tries - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"{url}: {last}")


def fetch_layer(url: str) -> list:
    """Page through an ArcGIS layer. These services advertise Query but not Extract."""
    meta = _post(url, {"f": "json"})
    page = min(meta.get("maxRecordCount") or 1000, 2000)
    feats, offset = [], 0
    while True:
        d = _post(
            url + "/query",
            {
                "where": "1=1",
                "outFields": "*",
                "returnGeometry": "true",
                "outSR": "4326",
                "f": "geojson",
                "resultRecordCount": page,
                "resultOffset": offset,
                "orderByFields": "OBJECTID",
            },
        )
        if "error" in d:
            raise RuntimeError(f"{url}: {d['error']}")
        got = d.get("features", [])
        feats.extend(got)
        offset += len(got)
        more = d.get("exceededTransferLimit") or (d.get("properties") or {}).get(
            "exceededTransferLimit"
        )
        if not got or not more:
            break
    return feats


# ---------------------------------------------------------------------------
# classification, from real attributes this time
# ---------------------------------------------------------------------------
def coverable(props: dict) -> tuple[bool, str]:
    """Decide from the Town's own ownership and class fields.

    Field names vary between service revisions, so every read is defensive and
    an unrecognised value fails CLOSED (excluded) rather than open. Over-
    excluding costs a street somebody has to add by hand. Over-including puts a
    private apartment drive on the shared map and it can never be taken back off
    honestly.
    """
    g = {k.lower(): (v if v is not None else "") for k, v in props.items()}

    def field(*names):
        for n in names:
            if n in g and str(g[n]).strip():
                return str(g[n]).strip().upper()
        return ""

    owner = field("owner", "ownership", "maintenance", "maint", "jurisdiction")
    rclass = field("class", "roadclass", "rd_class", "functional_class", "type")
    status = field("status", "lifecycle")
    name = field("name", "rd_name", "fullname", "street")

    if not name:
        return False, "unnamed"
    if status and status not in ("EXISTING", "ACTIVE", "OPEN", "BUILT"):
        return False, f"status:{status}"
    if any(w in owner for w in ("PRIVATE", "HOA", "APARTMENT")):
        return False, f"owner:{owner}"
    if any(w in rclass for w in ("DRIVEWAY", "PARKING", "ALLEY", "SERVICE", "RAMP", "PRIVATE")):
        return False, f"class:{rclass}"
    if "INTERSTATE" in rclass or "LIMITED" in rclass or "FREEWAY" in rclass:
        return False, f"class:{rclass}"
    if owner and any(w in owner for w in ("TOWN", "VDOT", "STATE", "COUNTY", "PUBLIC", "VT",
                                          "VIRGINIA TECH", "UNIVERSITY")):
        return True, f"owner:{owner}"
    if not owner:
        return False, "owner-unknown-fails-closed"
    return False, f"owner:{owner}"


def split_at_intersections(lines: list[tuple[dict, LineString]]):
    """Split every road at every point another road touches it."""
    geoms = [g for _, g in lines]
    tree = STRtree(geoms)
    out = []
    for props, g in lines:
        cuts = []
        for j in tree.query(g):
            other = geoms[j]
            if other is g:
                continue
            inter = g.intersection(other)
            if inter.is_empty:
                continue
            for pt in (inter.geoms if hasattr(inter, "geoms") else [inter]):
                if pt.geom_type == "Point":
                    cuts.append(g.project(pt))
        cuts = sorted({0.0, g.length, *[c for c in cuts if 0 < c < g.length]})
        for a, b in zip(cuts, cuts[1:]):
            if b - a <= 0:
                continue
            piece = LineString(
                [g.interpolate(a)]
                + [
                    g.interpolate(d)
                    for d in _between(g, a, b)
                ]
                + [g.interpolate(b)]
            )
            out.append((props, piece))
    return out


def _between(g: LineString, a: float, b: float) -> list[float]:
    """Distances of the original vertices strictly between a and b."""
    ds = []
    run = 0.0
    coords = list(g.coords)
    for p, q in zip(coords, coords[1:]):
        run += Point(p).distance(Point(q))
        if a < run < b:
            ds.append(run)
    return ds


def node_id(pt) -> str:
    return f"{round(pt[0], 7)}_{round(pt[1], 7)}"


def main():
    print("fetching town boundary ...")
    boundary = fetch_layer(LAYERS["boundary"])
    limits = unary_union([shape(f["geometry"]) for f in boundary])

    print("fetching roads ...")
    roads = fetch_layer(LAYERS["roads"])
    print(f"  {len(roads)} road features")

    kept, dropped = [], defaultdict(float)
    for f in roads:
        ok, reason = coverable(f["properties"])
        g = shape(f["geometry"])
        for part in (g.geoms if g.geom_type == "MultiLineString" else [g]):
            if ok:
                kept.append((f["properties"], part))
            else:
                dropped[reason] += GEOD.geometry_length(part)

    print("splitting at intersections ...")
    pieces = split_at_intersections(kept)

    segments = []
    for i, (props, g) in enumerate(pieces, start=1):
        inside = g.intersection(limits)
        if inside.is_empty:
            continue
        for part in (inside.geoms if hasattr(inside, "geoms") else [inside]):
            if part.geom_type != "LineString" or len(part.coords) < 2:
                continue
            length = GEOD.geometry_length(part)
            if length < 1.0:
                continue
            name = next(
                (str(props[k]) for k in props if k.lower() in ("name", "rd_name", "fullname", "street") and props[k]),
                "",
            )
            segments.append(
                {
                    "seg_id": len(segments) + 1,
                    "name": name,
                    "ref": None,
                    "class": "street",
                    "reason": "town-gis-authoritative",
                    "length_m": round(length, 2),
                    "node_a": node_id(part.coords[0]),
                    "node_b": node_id(part.coords[-1]),
                    "geometry": part,
                    "homes": 0,
                }
            )

    # ---- homes -----------------------------------------------------------
    # Every address point is assigned to exactly ONE segment: the nearest one
    # within 75 m. Exactly one, so no home is ever counted twice, which is the
    # same rule the network itself obeys. Points further than 75 m from any
    # coverable street belong to something we do not ask anyone to walk, and are
    # reported rather than silently dropped.
    print("fetching address points ...")
    addrs = fetch_layer(LAYERS["address"])
    print(f"  {len(addrs)} address points")

    seg_geoms = [s["geometry"] for s in segments]
    tree = STRtree(seg_geoms)
    CAP_DEG = 75.0 / 111_320.0
    unassigned = 0
    for a in addrs:
        p = shape(a["geometry"])
        if p.is_empty or not limits.contains(p):
            continue
        idx = tree.query_nearest(p, max_distance=CAP_DEG, return_distance=False)
        if len(idx) == 0:
            unassigned += 1
            continue
        best = min(idx, key=lambda j: seg_geoms[j].distance(p))
        segments[best]["homes"] += 1

    total_mi = sum(s["length_m"] for s in segments) / 1609.34
    homes = sum(s["homes"] for s in segments)

    print("\ndropped mileage by reason")
    for r, m in sorted(dropped.items(), key=lambda kv: -kv[1])[:12]:
        print(f"  {r:36s} {m / 1609.34:8.2f} mi")
    print(f"\nsegments      : {len(segments)}")
    print(f"miles         : {total_mi:.2f}")
    print(f"homes         : {homes}  ({unassigned} address points beyond the 75 m cap)")
    print(f"provisional   : 156.54 mi  (basemap-derived, +14.9% over known-good)")
    print(f"known-good    : 136.21 mi  (previous authoritative build)")

    if not (SANE_MIN_MI <= total_mi <= SANE_MAX_MI):
        raise SystemExit(
            f"REFUSING TO WRITE: {total_mi:.2f} mi is outside the sane range "
            f"{SANE_MIN_MI}-{SANE_MAX_MI}. The service schema probably changed. "
            f"Inspect the dropped-reason table above before trusting this run."
        )

    os.makedirs(OUT, exist_ok=True)
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": s["seg_id"],
                "properties": {k: v for k, v in s.items() if k != "geometry"},
                "geometry": json.loads(json.dumps(s["geometry"].__geo_interface__)),
            }
            for s in segments
        ],
    }
    path = os.path.join(OUT, "network.geojson")
    with open(path, "w") as fh:
        json.dump(fc, fh)
    print(f"\nwrote {path}")
    print("now run: python3 rebuild/db/load_network.py")


if __name__ == "__main__":
    main()
