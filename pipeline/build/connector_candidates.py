"""Phase 3.1 item 3: a focused, prioritised review set for campus-edge connectors.

Network v1.2 leaves 12.858 mi of required mileage off the main component, most of it
campus. The campus components are near-trees — component 1 has 66 nodes and 66 edges,
one independent cycle across 5.6 miles — so they produce out-and-back walks rather
than loops, and they carry zero households. Joining them to the town network is
therefore worth real effort. Inventing a crossing to do it is not.

This module ranks the candidates and gathers the evidence. It does **not** promote
anything: promotion is a curation entry plus a new canonical-network version.

WHAT COUNTS AS EVIDENCE, given no aerial imagery is reachable from this environment:

  opposed sidewalk termini   a sidewalk ends at the kerb on one side and another
                             begins roughly opposite. Two independent digitisers
                             stopping at the same place is meaningful — it is what a
                             crossing looks like in a pedestrian layer.
  at a road intersection     the crossing point is within INTERSECTION_M of a
                             road-road junction. Marked crosswalks live at
                             intersections; mid-block crossings of an arterial mostly
                             do not exist.
  public ownership           both sides are Town or VT pedestrian facilities rather
                             than private drives.
  road class and speed       supporting, not deciding. A local street at 25 mph is a
                             different proposition from an arterial at 45.

Proximity alone is explicitly NOT evidence, and no candidate is recommended on it.

  python3 -m pipeline.build.connector_candidates [--date YYYY-MM-DD]
"""
import argparse
import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone

import networkx as nx
from shapely.geometry import Point, shape
from shapely.ops import transform
from shapely.strtree import STRtree

from . import geo

OUT_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out")
M_PER_MILE = 1609.344

# A crossing point this close to a road-road junction is at an intersection.
INTERSECTION_M = 30.0
# Sidewalk ends this close to opposite each other are an opposed pair.
OPPOSED_M = 40.0
# Households within this radius proxy "how often will somebody start near here".
START_PROXIMITY_M = 500.0
# Roads a pedestrian crossing needs real evidence for.
TRAFFICKED = {"Arterial", "Collector", "Secondary"}
UNWALKABLE = {"Ramp", "Primary"}

# The campus-edge corridors the brief names.
FOCUS_ROADS = ("prices fork", "n main", "north main", "main st", "college ave",
               "washington st", "stanger", "turner", "kent st", "otey")


def load(date):
    with open(os.path.join(OUT_ROOT, date, "segments.geojson")) as f:
        feats = json.load(f)["features"]
    segs = []
    for f in feats:
        p = dict(f["properties"])
        p["_geom"] = transform(geo._to_proj, shape(f["geometry"]))
        p["_wgs"] = f["geometry"]
        segs.append(p)
    return segs


def default_components(segs):
    """Component membership under the v1.2 routing rule."""
    G = nx.Graph()
    for s in segs:
        derived = s["source"]["dataset"] == "DERIVED"
        if derived:
            if s.get("connector_class") != "HIGH_CONFIDENCE":
                continue
        elif s["role"] == "EXCLUDED" or not s.get("walkable"):
            continue
        G.add_edge(s["start_node_id"], s["end_node_id"])
    comps = sorted(nx.connected_components(G), key=len, reverse=True)
    return {n: ci for ci, c in enumerate(comps) for n in c}, comps


def component_stats(segs, node_comp):
    out = defaultdict(lambda: dict(required_m=0.0, households=0, names=defaultdict(float),
                                   nodes=set(), edges=0))
    for s in segs:
        ci = node_comp.get(s["start_node_id"])
        if ci is None:
            continue
        e = out[ci]
        e["nodes"].add(s["start_node_id"])
        e["nodes"].add(s["end_node_id"])
        e["edges"] += 1
        if s["role"] == "REQUIRED":
            e["required_m"] += float(s["length_m"])
            e["households"] += int(s.get("estimated_household_count") or 0)
            if s["display_name"]:
                e["names"][s["display_name"]] += float(s["length_m"])
    return {ci: dict(component=ci,
                     required_miles=round(v["required_m"] / M_PER_MILE, 3),
                     households=v["households"],
                     nodes=len(v["nodes"]), edges=v["edges"],
                     independent_cycles=v["edges"] - len(v["nodes"]) + 1,
                     top_streets=[n for n, _ in
                                  sorted(v["names"].items(), key=lambda x: -x[1])[:5]])
            for ci, v in out.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = ap.parse_args()
    date = args.date
    geo.assert_metric()

    segs = load(date)
    node_comp, comps = default_components(segs)
    cstats = component_stats(segs, node_comp)

    roads = [s for s in segs if s["segment_type"] == "STREET"]
    peds = [s for s in segs if s["segment_type"] in ("TRAIL", "PEDESTRIAN_CONNECTOR")
            and s["source"]["dataset"] != "DERIVED"]

    # Street junctions: nodes where two or more distinct street names meet.
    #
    # "Street" has to include named CAMPUS CORRIDORS, not just the Roads layer. The
    # town's Roads layer contains no campus streets at all (technical plan §2.4a), so
    # West Campus Drive exists here only as a pedestrian way — and an earlier version
    # of this test, which looked at road-road junctions only, therefore called the
    # West Campus Drive / Prices Fork Rd entrance a *mid-block crossing*. It is a
    # street intersection. That single blind spot mislabelled the highest-value
    # candidate in the whole review.
    def is_street_like(seg):
        if seg["segment_type"] == "STREET":
            return True
        # A campus corridor carrying a street name represents a street.
        nm = (seg.get("display_name") or "").lower()
        return bool(seg.get("in_campus_core")
                    and any(w in nm for w in (" dr", " drive", " st", " street",
                                              " ave", " avenue", " rd", " road",
                                              " ln", " lane")))

    street_like = [s for s in segs if is_street_like(s)]

    # What street-like features touch each node. Used two ways below: to find existing
    # junctions, and — the test that actually matters — to ask whether a candidate
    # connector would *form* one.
    #
    # An existing-junction test alone cannot see the case we care about. The whole
    # reason a candidate exists is that the two sides do not share a node, so no
    # junction is there to detect until the connector is added. Asking "does this link
    # street A to a differently-named street B" is the same question asked in a way the
    # data can answer.
    node_streets = defaultdict(set)
    for s in street_like:
        for n in (s["start_node_id"], s["end_node_id"]):
            node_streets[n].add(s.get("normalized_name") or "?")
    junctions = {n for n, names in node_streets.items() if len(names) > 1}
    jgeom, seen_nodes = [], set()
    for s in street_like:
        for n, pt in ((s["start_node_id"], s["_geom"].coords[0]),
                      (s["end_node_id"], s["_geom"].coords[-1])):
            if n in junctions and n not in seen_nodes:
                seen_nodes.add(n)
                jgeom.append(Point(pt))
    jtree = STRtree(jgeom) if jgeom else None

    # Pedestrian termini, for the opposed-pair test.
    ped_ends = []
    for s in peds:
        ped_ends.append((s, Point(s["_geom"].coords[0]), s["start_node_id"]))
        ped_ends.append((s, Point(s["_geom"].coords[-1]), s["end_node_id"]))
    etree = STRtree([p for _, p, _ in ped_ends]) if ped_ends else None

    # Household density per node, for the "will people start here" proxy.
    hh_pts, hh_vals = [], []
    for s in segs:
        n = int(s.get("estimated_household_count") or 0)
        if n:
            hh_pts.append(s["_geom"].interpolate(0.5, normalized=True))
            hh_vals.append(n)
    htree = STRtree(hh_pts) if hh_pts else None

    rows = []
    for s in segs:
        if s["source"]["dataset"] != "DERIVED":
            continue
        if s.get("connector_class") == "HIGH_CONFIDENCE":
            continue
        a, b = node_comp.get(s["start_node_id"]), node_comp.get(s["end_node_id"])
        if a is None or b is None or a == b:
            continue                       # only component-joining candidates
        rows.append(_assess(s, a, b, cstats, roads, jtree, node_streets, etree,
                            ped_ends, htree, hh_vals))

    rows.sort(key=lambda r: -r["priority_score"])
    approved = [r for r in rows if r["recommendation"] == "PROMOTE"]

    report = dict(
        generated_at=datetime.now(timezone.utc).isoformat(),
        snapshot_date=date,
        network_version="1.2",
        basemap_evidence=(
            "NONE. No aerial or street-level imagery host is reachable from this "
            "environment. Every judgement below rests on geometry, endpoint "
            "alignment, road class, speed and ownership. That ceiling is why "
            "confidence is capped at MEDIUM for anything crossing a trafficked road."),
        evidence_rules=dict(
            opposed_sidewalk_termini=(
                f"a pedestrian way ends within {OPPOSED_M:.0f} m opposite another"),
            at_road_intersection=(
                f"crossing point within {INTERSECTION_M:.0f} m of a road-road junction"),
            proximity_alone="explicitly NOT evidence; no candidate is promoted on it",
        ),
        component_stats=cstats,
        candidates=len(rows),
        promoted=len(approved),
        promote_segment_ids=[r["segment_id"] for r in approved],
        rows=rows,
    )
    path = os.path.join(OUT_ROOT, date, "review", "connector-candidates.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    _print(rows, cstats, path)
    return report


def _assess(s, a, b, cstats, roads, jtree, node_streets, etree, ped_ends, htree,
            hh_vals):
    info = s["source"].get("derived_from") or {}
    g = s["_geom"]
    mid = g.interpolate(0.5, normalized=True)
    length = float(s["length_m"])

    sa, sb = cstats.get(a, {}), cstats.get(b, {})
    # What joining actually recovers: the smaller side's required mileage.
    recovered = min(sa.get("required_miles", 0.0), sb.get("required_miles", 0.0))

    # Which road is being crossed or stepped into?
    near_roads = [r for r in roads if r["_geom"].distance(mid) <= 25.0]
    worst = None
    for r in near_roads:
        rank = (2 if r.get("road_class") in UNWALKABLE else
                1 if r.get("road_class") in TRAFFICKED else 0, r.get("speed_limit") or 0)
        if worst is None or rank > worst[0]:
            worst = (rank, r)
    road = worst[1] if worst else None
    road_name = (road or {}).get("display_name")
    road_class = (road or {}).get("road_class")
    speed = (road or {}).get("speed_limit")

    # --- evidence -----------------------------------------------------------
    at_intersection = False
    if jtree is not None:
        for k in jtree.query(mid.buffer(INTERSECTION_M)):
            if jtree.geometries[k].distance(mid) <= INTERSECTION_M:
                at_intersection = True
                break

    # Would this connector form a street junction? True when its two ends touch
    # differently-named street-like features — i.e. it is the link between a street
    # and a cross street, which is where crosswalks are, rather than a hop over a
    # kerb in the middle of a block.
    near_names = node_streets.get(s["start_node_id"], set())
    far_names = node_streets.get(s["end_node_id"], set())
    forms_junction = bool(near_names and far_names and (near_names != far_names))
    junction_streets = sorted(near_names | far_names)

    opposed = False
    if etree is not None:
        ends = [Point(g.coords[0]), Point(g.coords[-1])]
        hits = []
        for e in ends:
            for k in etree.query(e.buffer(OPPOSED_M)):
                seg, pt, _ = ped_ends[k]
                if seg["id"] == s["id"]:
                    continue
                if pt.distance(e) <= OPPOSED_M:
                    hits.append(seg)
        # Opposed means pedestrian geometry terminating on BOTH sides, not just one.
        sides = {seg["id"] for seg in hits}
        opposed = len(sides) >= 2

    both_public = all(
        (n or {}).get("access_type") in (None, "PUBLIC")
        for n in (info,)) and s.get("access_type") in (None, "UNKNOWN", "PUBLIC")

    households_nearby = 0
    if htree is not None:
        for k in htree.query(mid.buffer(START_PROXIMITY_M)):
            if htree.geometries[k].distance(mid) <= START_PROXIMITY_M:
                households_nearby += hh_vals[k]

    focus = any(f in (road_name or "").lower() for f in FOCUS_ROADS) or \
        any(f in (info.get("joined_to_name") or "").lower() for f in FOCUS_ROADS)

    evidence = []
    if opposed:
        evidence.append("pedestrian ways terminate on both sides — an opposed pair, "
                        "which is what a crossing looks like in a sidewalk layer")
    if forms_junction:
        evidence.append(
            f"links two differently-named streets ({' / '.join(junction_streets)}) — "
            f"this is a street junction, not a mid-block hop. Campus corridors count "
            f"as streets here: the town Roads layer contains no campus streets, so "
            f"treating them otherwise labels a main campus entrance mid-block")
    if at_intersection:
        evidence.append("within 30 m of an existing street junction, where marked crosswalks are "
                        "placed. Campus corridors carrying street names count as "
                        "streets here — the town Roads layer has no campus streets, so "
                        "treating them as anything else labels a main campus entrance "
                        "a mid-block crossing")
    if road_class not in TRAFFICKED and road_class not in UNWALKABLE:
        evidence.append(f"crosses a {road_class or 'local'} street"
                        + (f" at {speed} mph" if speed else ""))
    against = []
    if road_class in UNWALKABLE:
        against.append(f"{road_class} — limited access, no lawful pedestrian crossing")
    if road_class in TRAFFICKED and not (at_intersection or forms_junction):
        against.append(f"mid-block crossing of a {road_class} road"
                       + (f" at {speed} mph" if speed else ""))
    if not opposed:
        against.append("no opposed pedestrian terminus — nothing on the far side "
                       "suggests a crossing was ever digitised here")
    if length > 20:
        against.append(f"{length:.0f} m gap — too long to be a kerb-to-kerb crossing")

    # --- priority -----------------------------------------------------------
    # Deliberately dominated by what is recovered, not by how plausible it looks: a
    # perfect-looking connector that unlocks nothing is not worth anyone's afternoon.
    priority = (recovered * 100
                + (2.0 if focus else 0.0)
                + min(households_nearby, 2000) / 200.0
                + (3.0 if opposed else 0.0)
                + (2.0 if at_intersection else 0.0)
                + (3.0 if forms_junction else 0.0))

    # --- recommendation -----------------------------------------------------
    junction_evidence = at_intersection or forms_junction
    if road_class in UNWALKABLE:
        rec, conf = "REJECT", "HIGH"
    elif opposed and junction_evidence and road_class not in UNWALKABLE:
        # The strongest case the available evidence can make. Still not HIGH: no
        # imagery has been seen, and "promote only clearly legitimate" means a human
        # confirms before the network changes.
        rec, conf = "REVIEW_ON_SITE", "MEDIUM"
    elif junction_evidence and length <= 15 and (speed or 99) <= 30:
        # A short link forming a junction on a slow street. The strongest case the
        # available evidence can make without an opposed terminus.
        rec, conf = "REVIEW_ON_SITE", "MEDIUM"
    elif opposed or junction_evidence:
        rec, conf = "REVIEW_ON_SITE", "LOW"
    else:
        rec, conf = "DO_NOT_PROMOTE_WITHOUT_EVIDENCE", "LOW"

    return dict(
        segment_id=s["id"],
        classification=s.get("connector_class"),
        priority_score=round(priority, 2),
        length_m=round(length, 1),
        map_location=dict(lon=round(_wgs(s)[0], 6), lat=round(_wgs(s)[1], 6),
                          osm_link=f"https://www.openstreetmap.org/#map=19/"
                                   f"{_wgs(s)[1]:.5f}/{_wgs(s)[0]:.5f}"),
        connects_components=[a, b],
        component_a=sa, component_b=sb,
        required_miles_recovered=round(recovered, 3),
        households_recovered=min(sa.get("households", 0), sb.get("households", 0)),
        households_within_500m=households_nearby,
        likely_start_area=bool(focus or households_nearby > 300),
        road_crossed=road_name, road_class=road_class, speed_limit=speed,
        crossing_type=("at intersection" if at_intersection else
                       "forms street junction" if forms_junction else
                       "mid-block" if road_class else "unknown"),
        forms_street_junction=forms_junction,
        junction_streets=junction_streets,
        evidence_for=evidence, evidence_against=against,
        opposed_sidewalk_termini=opposed, at_road_intersection=at_intersection,
        from_feature=info.get("stranded_name"), to_feature=info.get("joined_to_name"),
        recommendation=rec, confidence=conf,
        decision=None, decided_by=None, decided_at=None,
    )


def _wgs(s):
    c = s["_wgs"]["coordinates"]
    return c[len(c) // 2] if s["_wgs"]["type"] == "LineString" else c[0]


def _print(rows, cstats, path):
    print(f"{'segment':<12}{'pri':>7}{'recov mi':>9}{'comps':<9}{'road':<22}"
          f"{'cls':<11}{'sp':>4}  {'xing':<16}{'rec':<32}conf")
    print("-" * 132)
    for r in rows[:18]:
        print(f"{r['segment_id']:<12}{r['priority_score']:>7.1f}"
              f"{r['required_miles_recovered']:>9.3f}"
              f"{str(r['connects_components']):<9}{str(r['road_crossed'])[:21]:<22}"
              f"{str(r['road_class'])[:10]:<11}{str(r['speed_limit'] or ''):>4}  "
              f"{r['crossing_type']:<16}{r['recommendation']:<32}{r['confidence']}")
    print(f"\ncomponents carrying required mileage:")
    for ci, c in sorted(cstats.items(), key=lambda x: -x[1]["required_miles"])[:8]:
        if c["required_miles"] < 0.05:
            continue
        print(f"  comp {ci:<4} {c['required_miles']:>8.3f} mi  hh {c['households']:>6}  "
              f"nodes {c['nodes']:>5}  cycles {c['independent_cycles']:>4}  "
              f"{', '.join(c['top_streets'][:3])}")
    print(f"\n-> {path}")


if __name__ == "__main__":
    main()
