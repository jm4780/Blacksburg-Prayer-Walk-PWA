"""Build a routable Blacksburg street network from the committed basemap archive.

This is the PROVISIONAL source. No geodata host is reachable from the build
environment (Overpass, Geofabrik, Town/County ArcGIS, Census TIGER and Supabase
are all denied at the egress proxy), so the only real geometry available is the
self-hosted Protomaps archive already committed at
web/public/basemap/blacksburg.pmtiles, plus the town boundary polygon at
pipeline/basemap/blacksburg-limits.json.

What that archive gives us, and what it does not:

  gives  - real centreline geometry, ~0.95 m quantisation at z13
         - street names (504 distinct inside town limits)
         - a three-value class field: motorway | link | minor

  lacks  - any access / private / surface / service attribute
         - any footway or path layer at all
         - address points of any kind

So classification below is a documented heuristic, not an authoritative
attribute read. Every rule states its evidence and its residual risk, and
classify_report() quantifies the gap against the known-good figures from the
previous build (124.848 required street mi + 11.359 campus mi).

Geometry is reassembled at the EDGE level rather than the feature level. Vector
tiles clip features at tile borders and repeat them in the neighbouring tile's
buffer, so "features" are not stable objects. Edges are. Because the z13/4096
quantisation grid aligns exactly across tile boundaries, the same physical edge
snaps to identical integer coordinates in every tile that carries it, and a set
keyed on the endpoint pair deduplicates it exactly.

Usage:  python3 -m rebuild.data.pipeline.extract_network
"""
from __future__ import annotations

import gzip
import json
import math
import os
from collections import Counter, defaultdict

import mapbox_vector_tile as mvt
import pyproj
from pmtiles.reader import MmapSource, Reader
from shapely.geometry import LineString, Polygon, shape
from shapely.ops import transform, unary_union

Z = 13
EXTENT = 4096
WORLD = 2 ** Z * EXTENT  # 2**25 integer units across the world at this grid

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PMTILES = os.path.join(REPO, "web", "public", "basemap", "blacksburg.pmtiles")
LIMITS = os.path.join(REPO, "pipeline", "basemap", "blacksburg-limits.json")
OUT = os.path.join(REPO, "rebuild", "data", "out")

GEOD = pyproj.Geod(ellps="WGS84")

# Ground truth carried forward from the previous build's frozen metrics. Used
# only to measure how far this provisional network sits from the authoritative
# one; never to tune the rules until they match, which would be fitting noise.
TRUTH_REQUIRED_STREET_MI = 124.848
TRUTH_CAMPUS_MI = 11.359


# --------------------------------------------------------------------------
# grid
# --------------------------------------------------------------------------
def to_grid(lon: float, lat: float) -> tuple[int, int]:
    """Longitude/latitude to the native z13/4096 integer grid."""
    x = (lon + 180.0) / 360.0 * WORLD
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * WORLD
    return int(round(x)), int(round(y))


def to_lonlat(gx: int, gy: int) -> tuple[float, float]:
    lon = gx / WORLD * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * gy / WORLD))))
    return lon, lat


def tile_of(lon: float, lat: float, z: int) -> tuple[int, int]:
    n = 2 ** z
    la = math.radians(lat)
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1 - math.log(math.tan(la) + 1 / math.cos(la)) / math.pi) / 2 * n)
    return x, y


# --------------------------------------------------------------------------
# classification
# --------------------------------------------------------------------------
# Name patterns that mark a carriageway we must not ask anyone to walk, or that
# is not a public street. Matched case-insensitively against the whole name.
PRIVATE_HINTS = (
    "parking",
    "garage",
    "access rd",
    "access road",
    "service rd",
    "service road",
    "loading",
    "maintenance",
)


# Street names the previous, authoritative build ruled EXCLUDED or PRIVATE,
# harvested from the review artefacts that survive in git even though that
# build's geometry does not. These are real rulings made against real Town GIS
# ownership attributes, so they beat anything inferable from tile data.
PRIOR_EXCLUSIONS = set(
    json.load(open(os.path.join(os.path.dirname(__file__), "prior_exclusions.json")))
)


def classify(cls: str | None, name: str | None, ref: str | None) -> tuple[str, str]:
    """Return (status, reason). status in {coverable, excluded}."""
    n = (name or "").strip()
    lower = n.lower()

    if n in PRIOR_EXCLUSIONS:
        return "excluded", "prior-build-ruled-private"

    if cls == "link":
        return "excluded", "ramp"

    if cls == "motorway":
        # US 460 proper is the limited-access bypass and is not walkable.
        # US 460 Business is Main Street through downtown: a normal town street
        # carrying a highway designation, and one of the most walked streets in
        # Blacksburg. Excluding it on class alone would be plainly wrong.
        tag = (ref or n or "").strip().lower()
        if "bus" in tag:
            return "coverable", "us-460-business-is-main-street"
        return "excluded", "limited-access-highway"

    if cls in ("trunk", "primary", "secondary", "tertiary"):
        return "coverable", "through-street"

    if cls == "minor":
        if not n:
            # 23% of minor mileage carries no name. In this archive an unnamed
            # minor way is a parking aisle, a driveway or a service spur; named
            # public residential streets are named. This is the single largest
            # heuristic in the build and the largest source of residual error.
            return "excluded", "unnamed-service-way"
        if n.startswith("(") and n.endswith(")"):
            # The archive parenthesises descriptive non-names, e.g.
            # "(Gilbert Linkous Elem School Access Rd)".
            return "excluded", "descriptive-non-name"
        if any(h in lower for h in PRIVATE_HINTS):
            return "excluded", "private-or-service-by-name"
        return "coverable", "named-public-street"

    return "excluded", f"unknown-class:{cls}"


# --------------------------------------------------------------------------
# extraction
# --------------------------------------------------------------------------
def read_edges(limits: Polygon):
    """Every deduplicated edge in the archive, as {(a,b): attrs}."""
    fh = open(PMTILES, "rb")
    reader = Reader(MmapSource(fh))
    w, s, e, n = limits.bounds
    x0, y1 = tile_of(w, s, Z)
    x1, y0 = tile_of(e, n, Z)

    edges: dict[tuple, dict] = {}
    features = 0
    for tx in range(x0, x1 + 1):
        for ty in range(y0, y1 + 1):
            raw = reader.get(Z, tx, ty)
            if not raw:
                continue
            try:
                raw = gzip.decompress(raw)
            except Exception:
                pass
            layer = mvt.decode(raw).get("roads")
            if not layer:
                continue
            ntile = 2 ** Z
            for feat in layer["features"]:
                props = feat["properties"]

                def to_ll(x, y, z=None, tx=tx, ty=ty, ntile=ntile):
                    lon = (tx + x / EXTENT) / ntile * 360.0 - 180.0
                    yy = (ty + (EXTENT - y) / EXTENT) / ntile
                    return lon, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yy))))

                geom = transform(to_ll, shape(feat["geometry"]))
                parts = geom.geoms if geom.geom_type == "MultiLineString" else [geom]
                for part in parts:
                    features += 1
                    pts = [to_grid(x, y) for x, y in part.coords]
                    for a, b in zip(pts, pts[1:]):
                        if a == b:
                            continue
                        key = (a, b) if a <= b else (b, a)
                        prev = edges.get(key)
                        if prev is None:
                            edges[key] = {
                                "class": props.get("class"),
                                "name": props.get("name"),
                                "ref": props.get("ref"),
                            }
                        elif prev["name"] is None and props.get("name"):
                            # A tile-buffer copy may carry attributes the
                            # clipped copy lost. Prefer the richer one.
                            prev["name"] = props.get("name")
                            prev["ref"] = props.get("ref")
    fh.close()
    return edges, features


def edge_len(a, b) -> float:
    (lon1, lat1), (lon2, lat2) = to_lonlat(*a), to_lonlat(*b)
    return GEOD.line_length([lon1, lon2], [lat1, lat2])


# --------------------------------------------------------------------------
# segmentation
# --------------------------------------------------------------------------
def build_segments(edges: dict, limits: Polygon):
    """Chain coverable edges into segments broken at intersections.

    A segment runs from one junction node to the next. Junctions are nodes where
    three or more ways meet, where the street name changes, or where the way
    simply ends. Chaining stops at every one of them, so a segment is always
    "one named street between two cross streets" -- the unit a walker confirms.
    """
    adj: dict[tuple, list] = defaultdict(list)
    for (a, b), attrs in edges.items():
        status, reason = classify(attrs["class"], attrs["name"], attrs["ref"])
        attrs["status"], attrs["reason"] = status, reason
        if status != "coverable":
            continue
        adj[a].append((b, (a, b)))
        adj[b].append((a, (a, b)))

    def name_at(key):
        return edges[key]["name"]

    def is_junction(node) -> bool:
        links = adj[node]
        if len(links) != 2:
            return True
        return name_at(links[0][1]) != name_at(links[1][1])

    used: set = set()
    segments = []
    starts = [n for n in adj if is_junction(n)]
    # Rings with no junction anywhere still need a seed.
    for node in starts + list(adj.keys()):
        for nxt, key in adj[node]:
            if key in used:
                continue
            chain_keys = [key]
            used.add(key)
            pts = [node, nxt]
            cur, came = nxt, key
            while not is_junction(cur):
                step = next((l for l in adj[cur] if l[1] != came and l[1] not in used), None)
                if step is None:
                    break
                nxt2, k2 = step
                used.add(k2)
                chain_keys.append(k2)
                pts.append(nxt2)
                cur, came = nxt2, k2
            attrs = edges[chain_keys[0]]
            coords = [to_lonlat(*p) for p in pts]
            line = LineString(coords)
            length = sum(edge_len(a, b) for a, b in zip(pts, pts[1:]))
            segments.append(
                {
                    "name": attrs["name"],
                    "ref": attrs["ref"],
                    "class": attrs["class"],
                    "reason": attrs["reason"],
                    "geometry": line,
                    "length_m": length,
                    "nodes": (pts[0], pts[-1]),
                }
            )
    # Clip to the town limit. The GEOMETRY is clipped too, not just the length:
    # storing a full-length line beside an inside-only length draws street the
    # town does not claim and prices a walk at less than it costs. A segment
    # crossing the boundary can also come back as several disjoint pieces, and
    # each piece is its own segment because you cannot walk between them without
    # leaving town.
    kept = []
    for seg in segments:
        inside = seg["geometry"].intersection(limits)
        if inside.is_empty:
            continue
        parts = inside.geoms if hasattr(inside, "geoms") else [inside]
        for part in parts:
            if part.geom_type != "LineString" or len(part.coords) < 2:
                continue
            length = GEOD.geometry_length(part)
            if length < 1.0:
                continue
            # Node ids come from the clipped endpoints. An endpoint that moved
            # because of the boundary becomes a dead end, which is the truth:
            # the road continues, but not anywhere this app asks anyone to walk.
            a = to_grid(*part.coords[0])
            b = to_grid(*part.coords[-1])
            kept.append(
                {
                    **seg,
                    "geometry": part,
                    "length_m": length,
                    "nodes": (a, b),
                }
            )
    return kept


def group_carriageways(segments: list[dict]) -> None:
    """Give both sides of a divided road one shared coverage identity.

    A dual carriageway is drawn as two parallel lines. Left alone, that breaks
    the app's central promise twice over: the denominator counts the road twice,
    so the town can never reach 100%, and a walker who walks Prices Fork Rd
    covers one line while the other stays unprayed for ever, because nobody can
    walk the far side of a median separately.

    Both lines stay in the graph, because routing needs the real topology. They
    simply share a `carriageway_id`, and coverage is counted per carriageway
    rather than per segment. Walk either side, the road is prayed for.

    Pairing is deliberately strict: same street name, at least 60% of the
    shorter line lying within 20 m of the longer, and both over 40 m. Two
    segments running end to end along one carriageway barely overlap laterally,
    so they never pair, which is what keeps this from chaining down a whole road.
    """
    from shapely.strtree import STRtree

    geoms = [s["geometry"] for s in segments]
    tree = STRtree(geoms)
    tol = 20.0 / 111_320.0

    # Score every candidate counterpart, then keep only MUTUAL BEST pairs.
    #
    # Transitive grouping is wrong here and the data proves it: along Prices Fork
    # Rd, the north line of one block also lies within tolerance of the south
    # line of the next, so a union-find walks the length of the road and ends up
    # claiming two miles are prayed for because somebody walked one block.
    # Requiring each side to be the other's single best match makes a group of
    # two the only thing that can form, which is exactly what a divided road is.
    best_for: dict[int, tuple[float, int]] = {}
    for i, g in enumerate(geoms):
        name_i = segments[i]["name"]
        buf = g.buffer(tol)
        for j in tree.query(buf):
            if j == i or segments[j]["name"] != name_i:
                continue
            li, lj = segments[i]["length_m"], segments[j]["length_m"]
            if min(li, lj) <= 40:
                continue
            overlap = buf.intersection(geoms[j])
            if overlap.is_empty:
                continue
            score = GEOD.geometry_length(overlap) / min(li, lj)
            if score <= 0.6:
                continue
            if score > best_for.get(i, (0.0, -1))[0]:
                best_for[i] = (score, j)

    merged_m = 0.0
    groups = 0
    for s in segments:
        s["carriageway"] = None
    for i, (score, j) in best_for.items():
        if best_for.get(j, (0.0, -1))[1] != i:
            continue  # not mutual: one of them has a better counterpart
        if segments[i]["carriageway"] is not None:
            continue
        # Store the REPRESENTATIVE'S seg_id, which is its list index + 1, not the
        # index itself. Downstream this is compared as
        # coalesce(carriageway, seg_id), so a raw 0-based index would collide
        # with an unrelated segment's 1-based seg_id and drag it into the group.
        cw = min(i, j) + 1
        segments[i]["carriageway"] = cw
        segments[j]["carriageway"] = cw
        groups += 1
        merged_m += min(segments[i]["length_m"], segments[j]["length_m"])

    print(f"\ncarriageway candidates  : {len(best_for)}")
    print(f"divided roads paired    : {groups}")
    print(f"double-counted mileage  : {merged_m / 1609.34:.2f} mi removed from the denominator")


def main():
    limits = Polygon(json.load(open(LIMITS))["coordinates"][0])
    edges, features = read_edges(limits)
    print(f"tile features read : {features}")
    print(f"deduplicated edges : {len(edges)}")

    segments = build_segments(edges, limits)

    # Report: mileage by disposition, inside town limits only.
    by_reason = defaultdict(float)
    for (a, b), attrs in edges.items():
        mid = LineString([to_lonlat(*a), to_lonlat(*b)])
        if not limits.intersects(mid):
            continue
        clipped = mid.intersection(limits)
        if clipped.is_empty:
            continue
        by_reason[attrs.get("reason", "?")] += GEOD.geometry_length(clipped)

    print("\ndisposition inside town limits")
    for reason, metres in sorted(by_reason.items(), key=lambda kv: -kv[1]):
        print(f"  {reason:34s} {metres / 1609.34:8.2f} mi")

    group_carriageways(segments)

    # The denominator counts each carriageway once: the longest line in a group
    # stands for the road, the other side rides along with it.
    best: dict[int, float] = {}
    solo = 0.0
    for s in segments:
        cw = s.get("carriageway")
        if cw is None:
            solo += s["length_m"]
        else:
            best[cw] = max(best.get(cw, 0.0), s["length_m"])
    effective = (solo + sum(best.values())) / 1609.34

    total = sum(s["length_m"] for s in segments) / 1609.34
    names = {s["name"] for s in segments}
    print(f"\ncoverable segments : {len(segments)}")
    print(f"drawn miles        : {total:.2f}")
    print(f"countable miles    : {effective:.2f}   (each carriageway once)")
    print(f"distinct streets   : {len(names)}")
    truth = TRUTH_REQUIRED_STREET_MI + TRUTH_CAMPUS_MI
    print(f"previous build     : {truth:.2f} mi required street + campus")
    print(f"delta              : {effective - truth:+.2f} mi "
          f"({100 * (effective - truth) / truth:+.1f}%)")

    os.makedirs(OUT, exist_ok=True)
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": i + 1,
                "properties": {
                    "seg_id": i + 1,
                    "name": s["name"],
                    "ref": s["ref"],
                    "class": s["class"],
                    "reason": s["reason"],
                    "length_m": round(s["length_m"], 2),
                    "node_a": f"{s['nodes'][0][0]}_{s['nodes'][0][1]}",
                    "node_b": f"{s['nodes'][1][0]}_{s['nodes'][1][1]}",
                    # Both sides of a divided road share this. Null means the
                    # segment stands alone, which is the ordinary case.
                    "carriageway": s.get("carriageway"),
                },
                "geometry": json.loads(json.dumps(s["geometry"].__geo_interface__)),
            }
            for i, s in enumerate(segments)
        ],
    }
    path = os.path.join(OUT, "network.geojson")
    with open(path, "w") as fh:
        json.dump(fc, fh)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
