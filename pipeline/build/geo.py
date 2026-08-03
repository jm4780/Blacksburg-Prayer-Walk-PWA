"""Geometry loading, reprojection, and network noding.

All length and distance math happens in EPSG:6594 (NAD83(2011) / Virginia South,
**metres**). Source snapshots are EPSG:4326; the town publishes in EPSG:2284 (survey
feet), which is why nothing here trusts a source length field.

CRS WARNING: the technical plan §2.2 originally specified EPSG:6595. That code is
NAD83(2011) / Virginia South **(ftUS)** — survey feet, not metres. Using it made every
length 3.28x too large and shrank every tolerance to a third of its intended size.
The metre-based code for this zone is EPSG:6594. Do not "fix" this back.
"""
import json
import math
import os

from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, Point, shape
from shapely.ops import linemerge, transform, unary_union
from shapely.strtree import STRtree

SNAP_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "snapshots")

WGS84 = "EPSG:4326"
PROJ = "EPSG:6594"  # NAD83(2011) / Virginia South — METRES (6595 is ftUS)

_to_proj = Transformer.from_crs(WGS84, PROJ, always_xy=True).transform
_to_wgs = Transformer.from_crs(PROJ, WGS84, always_xy=True).transform

# Endpoints closer than this become one node. Snaps larger than LOG_SNAP_M are
# reported for review rather than applied quietly.
SNAP_TOLERANCE_M = 1.0
LOG_SNAP_M = 0.3

# Two vertices closer than this are the same point for splitting purposes.
SPLIT_EPS_M = 0.05


def assert_metric():
    """Guard: refuse to run if PROJ is not metre-based.

    A foot-based projected CRS produces plausible-looking numbers that are all wrong
    by 3.28x, and every downstream tolerance silently shrinks. Fail loudly instead.
    """
    from pyproj import CRS
    units = {a.unit_name for a in CRS.from_user_input(PROJ).axis_info}
    if units != {"metre"}:
        raise RuntimeError(f"{PROJ} has units {units}, expected metre. "
                           "All lengths and tolerances in this pipeline assume metres.")


def load(dataset, date_str):
    """Load a snapshot as [(attrs, shapely geom in EPSG:6594, metres)]."""
    path = os.path.join(SNAP_ROOT, dataset, f"{date_str}.geojson")
    with open(path) as f:
        gj = json.load(f)
    out = []
    for feat in gj["features"]:
        if not feat.get("geometry"):
            continue
        g = transform(_to_proj, shape(feat["geometry"]))
        if g.is_empty:
            continue
        out.append((dict(feat.get("properties") or {}), g))
    return out


def load_meta(dataset, date_str):
    with open(os.path.join(SNAP_ROOT, dataset, f"{date_str}.meta.json")) as f:
        return json.load(f)


def to_wgs84_geojson(geom):
    return transform(_to_wgs, geom).__geo_interface__


def explode_lines(geom):
    """Yield LineStrings from a LineString or MultiLineString."""
    if geom.geom_type == "LineString":
        if geom.length > 0:
            yield geom
    elif geom.geom_type == "MultiLineString":
        for g in geom.geoms:
            if g.length > 0:
                yield g


def split_line_at(line, points):
    """Split `line` at each point that lies on it. Returns a list of LineStrings."""
    if not points:
        return [line]
    dists = sorted({
        round(line.project(p), 3) for p in points
        if SPLIT_EPS_M < line.project(p) < line.length - SPLIT_EPS_M
    })
    if not dists:
        return [line]

    coords = list(line.coords)
    cuts = [0.0] + dists + [line.length]
    pieces = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        if b - a <= SPLIT_EPS_M:
            continue
        seg = _substring(line, coords, a, b)
        if seg is not None and seg.length > SPLIT_EPS_M:
            pieces.append(seg)
    return pieces or [line]


def _substring(line, coords, start, end):
    """Extract the portion of `line` between two measures along it."""
    pts = [line.interpolate(start)]
    run = 0.0
    for i in range(len(coords) - 1):
        seg_len = math.dist(coords[i], coords[i + 1])
        nxt = run + seg_len
        if run > start and nxt < end:
            pts.append(Point(coords[i]))
        elif start < nxt <= end and run <= start:
            pass
        run = nxt
    # Re-walk cleanly: collect every original vertex strictly inside (start, end).
    pts = [line.interpolate(start)]
    run = 0.0
    for i in range(len(coords) - 1):
        run += math.dist(coords[i], coords[i + 1])
        if start < run < end:
            pts.append(Point(coords[i + 1]))
    pts.append(line.interpolate(end))

    xy, last = [], None
    for p in pts:
        c = (p.x, p.y)
        if last is None or math.dist(c, last) > 1e-9:
            xy.append(c)
            last = c
    return LineString(xy) if len(xy) >= 2 else None


def node_network(features):
    """Planarize: split every line where it meets another line.

    `features` is [(attrs, LineString)]. Returns (pieces, stats) where pieces is
    [(attrs, LineString)] with attrs carried through to every child piece.
    """
    geoms = [g for _, g in features]
    tree = STRtree(geoms)
    pieces, split_count = [], 0

    for idx, (attrs, line) in enumerate(features):
        cut_points = []
        for other_idx in tree.query(line):
            if other_idx == idx:
                continue
            other = geoms[other_idx]
            if not line.intersects(other):
                continue
            inter = line.intersection(other)
            cut_points.extend(_intersection_points(inter))

        parts = split_line_at(line, cut_points)
        if len(parts) > 1:
            split_count += 1
        for part in parts:
            pieces.append((attrs, part))

    return pieces, {"inputs": len(features), "split": split_count, "outputs": len(pieces)}


def _intersection_points(inter):
    """Reduce an intersection result to the points we should cut at."""
    t = inter.geom_type
    if t == "Point":
        return [inter]
    if t == "MultiPoint":
        return list(inter.geoms)
    if t in ("LineString", "MultiLineString"):
        # Collinear overlap (divided roadways, duplicated geometry). Cut at the ends
        # of the shared run; the overlap itself is handled by dedup downstream.
        out = []
        for g in explode_lines(inter):
            out.append(Point(g.coords[0]))
            out.append(Point(g.coords[-1]))
        return out
    if t == "GeometryCollection":
        out = []
        for g in inter.geoms:
            out.extend(_intersection_points(g))
        return out
    return []


def build_nodes(pieces):
    """Assign integer node ids to segment endpoints, snapping near-misses.

    Returns (node_ids, node_points, snap_log) where node_ids is a list of
    (start_id, end_id) parallel to `pieces`.
    """
    endpoints = []
    for _, g in pieces:
        endpoints.append(Point(g.coords[0]))
        endpoints.append(Point(g.coords[-1]))

    tree = STRtree(endpoints)
    assigned = [None] * len(endpoints)
    node_points, snap_log = [], []

    for i, p in enumerate(endpoints):
        if assigned[i] is not None:
            continue
        nid = len(node_points)
        cluster = [j for j in tree.query(p.buffer(SNAP_TOLERANCE_M))
                   if assigned[j] is None and p.distance(endpoints[j]) <= SNAP_TOLERANCE_M]
        if i not in cluster:
            cluster.append(i)
        xs = ys = 0.0
        for j in cluster:
            assigned[j] = nid
            xs += endpoints[j].x
            ys += endpoints[j].y
            d = p.distance(endpoints[j])
            if d > LOG_SNAP_M:
                snap_log.append({"node_id": nid, "distance_m": round(d, 3)})
        node_points.append(Point(xs / len(cluster), ys / len(cluster)))

    node_ids = [(assigned[2 * k], assigned[2 * k + 1]) for k in range(len(pieces))]
    return node_ids, node_points, snap_log


def node_degrees(node_ids, node_count):
    deg = [0] * node_count
    for a, b in node_ids:
        deg[a] += 1
        if b != a:
            deg[b] += 1
    return deg


def dedupe_collinear(pieces, node_ids, tolerance_m=3.0):
    """Drop duplicate-geometry segments (divided-roadway dual centerlines).

    Two segments are duplicates when they share both endpoints *and* their midpoints
    are within `tolerance_m`. Keeps the first, records the rest. Walking one side of
    a divided road counts (spec §4.2), so two parallel required edges would
    double-count mileage and make coverage impossible to finish.
    """
    seen, keep, dropped = {}, [], []
    for i, ((attrs, g), (a, b)) in enumerate(zip(pieces, node_ids)):
        key = (min(a, b), max(a, b))
        mid = g.interpolate(0.5, normalized=True)
        hit = None
        for j in seen.get(key, []):
            if pieces[j][1].interpolate(0.5, normalized=True).distance(mid) <= tolerance_m:
                hit = j
                break
        if hit is None:
            seen.setdefault(key, []).append(i)
            keep.append(i)
        else:
            dropped.append({"dropped_index": i, "kept_index": hit,
                            "length_m": round(g.length, 2)})
    return keep, dropped


def merge_geometry(geoms):
    merged = linemerge(unary_union(geoms))
    return merged
