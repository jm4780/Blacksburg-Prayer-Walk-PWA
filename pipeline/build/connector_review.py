"""Classify synthetic connectors by how much we should trust them.

The connect stage stitches the pedestrian layer onto the streets, but a connector is
an assertion — "you can walk from here to there" — that no source made. Routing over
all of them equally would let the router invent mid-block crossings of Prices Fork Rd.

Four classes:

  HIGH_CONFIDENCE           the join is a digitising artefact, not a real gap. Safe to
                            route by default.
  CROSSING_REVIEW_REQUIRED  physically plausible but implies stepping into or across a
                            roadway that carries traffic. Needs human eyes.
  LIKELY_FALSE              asserts access onto something you cannot walk on, or across
                            a barrier. Should not route.
  UNRESOLVED                not enough signal either way.

Only HIGH_CONFIDENCE enters the default Phase 2b routing graph.

NOTE ON BASEMAP EVIDENCE: no aerial or basemap imagery was consulted. Every imagery
and tile host is denied by this environment's egress policy. Classification uses
geometry, endpoint alignment, road class, speed limit, name agreement and crossing
context only.

Usage: python3 -m pipeline.build.connector_review [--date YYYY-MM-DD]
"""
import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone

import networkx as nx
from shapely.geometry import shape
from shapely.ops import transform
from shapely.strtree import STRtree

from . import geo

OUT_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out")
M_PER_MILE = 1609.344

# Road classes you cannot legally or safely walk onto from a trail end.
UNWALKABLE_CLASSES = {"Ramp", "Primary"}
# Road classes where stepping off a path into the roadway needs a real crossing.
TRAFFICKED_CLASSES = {"Arterial", "Collector", "Secondary"}
# A connector this long is a genuine gap in the data, not a digitising offset.
LONG_CONNECTOR_M = 15.0
SHORT_CONNECTOR_M = 10.0


def load(date):
    with open(os.path.join(OUT_ROOT, date, "segments.geojson")) as f:
        feats = json.load(f)["features"]
    segs = []
    for f in feats:
        p = dict(f["properties"])
        p["_geom"] = transform(geo._to_proj, shape(f["geometry"]))
        segs.append(p)
    return segs


def classify(segs):
    by_node = defaultdict(list)
    for i, s in enumerate(segs):
        by_node[s["start_node_id"]].append(i)
        by_node[s["end_node_id"]].append(i)

    # Road centerlines, for the "does this connector cross a roadway" test.
    roads = [(i, s) for i, s in enumerate(segs) if s["segment_type"] == "STREET"]
    road_tree = STRtree([s["_geom"] for _, s in roads]) if roads else None

    results = []
    for i, s in enumerate(segs):
        if s["source"]["dataset"] != "DERIVED":
            continue
        info = s["source"].get("derived_from") or {}
        length = float(s["length_m"])

        # Neighbours at each end, excluding the connector itself and other connectors.
        neigh = []
        for nid in (s["start_node_id"], s["end_node_id"]):
            for j in by_node[nid]:
                if j != i and segs[j]["source"]["dataset"] != "DERIVED":
                    neigh.append(segs[j])

        streets = [n for n in neigh if n["segment_type"] == "STREET"]
        peds = [n for n in neigh if n["segment_type"] != "STREET"]

        # Worst-case road we are being asked to step onto.
        worst_class, worst_speed, worst_name, worst_role = None, 0, None, None
        for n in streets:
            sp = n.get("speed_limit") or 0
            rc = n.get("road_class")
            rank = (2 if rc in UNWALKABLE_CLASSES else 1 if rc in TRAFFICKED_CLASSES else 0,
                    sp)
            cur = (2 if worst_class in UNWALKABLE_CLASSES else 1 if worst_class in TRAFFICKED_CLASSES else 0,
                   worst_speed)
            if worst_class is None or rank > cur:
                worst_class, worst_speed = rc, sp
                worst_name, worst_role = n.get("display_name"), n.get("role")

        # Does the connector cross a road centerline somewhere other than its ends?
        crossed = []
        if road_tree is not None:
            for k in road_tree.query(s["_geom"]):
                idx, rs = roads[k]
                if idx == i:
                    continue
                inter = s["_geom"].intersection(rs["_geom"])
                if inter.is_empty:
                    continue
                # Touching at an endpoint is the normal join, not a crossing.
                ends = [s["_geom"].coords[0], s["_geom"].coords[-1]]
                pts = [inter] if inter.geom_type == "Point" else list(
                    getattr(inter, "geoms", []))
                for pt in pts:
                    if pt.geom_type != "Point":
                        continue
                    if min(((pt.x - e[0]) ** 2 + (pt.y - e[1]) ** 2) ** 0.5 for e in ends) > 0.5:
                        crossed.append(rs)

        # Name agreement: a sidewalk offset from the street it belongs to.
        sname = (info.get("stranded_name") or "").strip().lower()
        tname = (info.get("joined_to_name") or "").strip().lower()
        name_match = bool(sname and tname and (
            sname.startswith(tname[:8]) or tname.startswith(sname[:8])))

        cls, why = _rule(s, info, length, streets, peds, worst_class, worst_speed,
                         worst_role, worst_name, crossed, name_match)

        results.append(dict(
            id=s["id"], length_m=round(length, 2), miles=round(length / M_PER_MILE, 5),
            classification=cls, reasons=why,
            joins_stranded=info.get("stranded_name"),
            joins_target=info.get("joined_to_name"),
            target_dataset=info.get("joined_to_dataset"),
            target_road_class=worst_class, target_speed=worst_speed,
            target_role=worst_role, target_name=worst_name,
            crosses_roadways=[r.get("display_name") for r in crossed],
            name_match=name_match,
            neighbour_streets=len(streets), neighbour_paths=len(peds),
            start_node_id=s["start_node_id"], end_node_id=s["end_node_id"],
        ))
    return results


def _rule(s, info, length, streets, peds, worst_class, worst_speed, worst_role,
          worst_name, crossed, name_match):
    why = []

    # --- LIKELY_FALSE ------------------------------------------------------
    if worst_class in UNWALKABLE_CLASSES:
        why.append(f"joins onto {worst_class} ({info.get('joined_to_name')}) — "
                   f"limited-access facility, not walkable")
        return "LIKELY_FALSE", why
    if any(r.get("road_class") in UNWALKABLE_CLASSES for r in crossed):
        names = {r.get("display_name") for r in crossed
                 if r.get("road_class") in UNWALKABLE_CLASSES}
        why.append(f"crosses a limited-access roadway mid-block ({', '.join(sorted(map(str, names)))})")
        return "LIKELY_FALSE", why
    if worst_role == "EXCLUDED" and not name_match and streets:
        why.append(f"only reachable segment is EXCLUDED ({worst_class}, "
                   f"{info.get('joined_to_name')}) — asserts access onto a private drive")
        return "LIKELY_FALSE", why

    # --- HIGH_CONFIDENCE ---------------------------------------------------
    if not streets and peds:
        why.append("joins pedestrian geometry to pedestrian geometry — no roadway "
                   "involved, pure digitising offset")
        return "HIGH_CONFIDENCE", why
    if name_match and not crossed:
        why.append(f"stranded path and target street share a name "
                   f"({info.get('stranded_name')} / {info.get('joined_to_name')}) — "
                   f"the sidewalk belongs to this street, offset in digitising")
        return "HIGH_CONFIDENCE", why
    if (length <= SHORT_CONNECTOR_M and not crossed
            and worst_class not in TRAFFICKED_CLASSES and worst_speed <= 25):
        why.append(f"{length:.1f} m onto a low-speed {worst_class or 'local'} street "
                   f"({worst_speed or '?'} mph), no roadway crossed")
        return "HIGH_CONFIDENCE", why

    # --- CROSSING_REVIEW_REQUIRED -----------------------------------------
    if crossed:
        why.append(f"crosses {len(crossed)} roadway centerline(s) mid-block: "
                   f"{', '.join(sorted({str(r.get('display_name')) for r in crossed}))}")
        return "CROSSING_REVIEW_REQUIRED", why
    if worst_class in TRAFFICKED_CLASSES or worst_speed >= 35:
        why.append(f"steps into a {worst_class or '?'} roadway "
                   f"({worst_name}, {worst_speed or '?'} mph) — needs a real crossing")
        return "CROSSING_REVIEW_REQUIRED", why
    if length > LONG_CONNECTOR_M:
        why.append(f"{length:.1f} m gap — too long to be a digitising offset; "
                   f"something is genuinely missing here")
        return "CROSSING_REVIEW_REQUIRED", why

    # --- UNRESOLVED --------------------------------------------------------
    why.append(f"insufficient signal: {length:.1f} m, target class "
               f"{worst_class or 'unknown'}, speed {worst_speed or 'unknown'}, "
               f"no name agreement")
    return "UNRESOLVED", why


def connectivity(segs, routable_ids, label):
    """Component analysis over a graph restricted to `routable_ids` + all non-derived."""
    G = nx.Graph()
    for s in segs:
        if not s["walkable"] or s["role"] == "EXCLUDED":
            continue
        if s["source"]["dataset"] == "DERIVED" and s["id"] not in routable_ids:
            continue
        G.add_edge(s["start_node_id"], s["end_node_id"], id=s["id"])

    comps = sorted(nx.connected_components(G), key=len, reverse=True)
    node_comp = {n: ci for ci, c in enumerate(comps) for n in c}

    stats = []
    for ci, comp in enumerate(comps):
        req_m = tot_m = 0.0
        req_n = tot_n = 0
        names = set()
        for s in segs:
            if s["start_node_id"] not in comp:
                continue
            if s["source"]["dataset"] == "DERIVED" and s["id"] not in routable_ids:
                continue
            if not s["walkable"] or s["role"] == "EXCLUDED":
                continue
            L = float(s["length_m"])
            tot_m += L
            tot_n += 1
            if s["role"] == "REQUIRED":
                req_m += L
                req_n += 1
                if s["display_name"]:
                    names.add(s["display_name"])
        stats.append(dict(component=ci, nodes=len(comp), segments=tot_n,
                          miles=round(tot_m / M_PER_MILE, 3),
                          required_segments=req_n,
                          required_miles=round(req_m / M_PER_MILE, 3),
                          sample_names=sorted(names)[:6]))

    total_req_m = sum(float(s["length_m"]) for s in segs if s["role"] == "REQUIRED")
    main = stats[0] if stats else dict(required_miles=0, nodes=0)
    return dict(
        label=label,
        components=len(comps),
        main_component=main,
        total_required_miles=round(total_req_m / M_PER_MILE, 3),
        main_component_required_share=round(
            main["required_miles"] / (total_req_m / M_PER_MILE), 4) if total_req_m else 0,
        largest_disconnected=stats[1:11],
        unresolved_required_miles=round(
            sum(c["required_miles"] for c in stats[1:]), 3),
    ), node_comp, comps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = ap.parse_args()
    date = args.date
    geo.assert_metric()

    segs = load(date)
    results = classify(segs)

    counts = defaultdict(lambda: {"n": 0, "m": 0.0})
    for r in results:
        counts[r["classification"]]["n"] += 1
        counts[r["classification"]]["m"] += r["length_m"]

    high = {r["id"] for r in results if r["classification"] == "HIGH_CONFIDENCE"}

    all_ids = {r["id"] for r in results}
    conn_all, _, _ = connectivity(segs, all_ids, "all connectors routable")
    conn_high, _, _ = connectivity(segs, high, "HIGH_CONFIDENCE only (Phase 2b default)")
    conn_none, _, _ = connectivity(segs, set(), "no connectors (pre-connect baseline)")

    # Attribute the disconnected required mileage.
    attribution = attribute_disconnection(segs, results, conn_high, conn_all)

    report = dict(
        generated_at=datetime.now(timezone.utc).isoformat(),
        snapshot_date=date,
        basemap_evidence=("NONE — all imagery/tile hosts are denied by this "
                          "environment's egress policy. Classification uses geometry, "
                          "endpoint alignment, road class, speed limit, name agreement "
                          "and crossing context only."),
        connectors_proposed_across_passes=426,
        connectors_in_network=len(results),
        note=("426 connectors were proposed across five connect passes; 262 survive as "
              "distinct segments after duplicate-geometry dedup. Classification below "
              "covers the 262 in the network."),
        counts={k: {"connectors": v["n"], "miles": round(v["m"] / M_PER_MILE, 4)}
                for k, v in sorted(counts.items())},
        connectivity=dict(all_connectors=conn_all, high_confidence_only=conn_high,
                          no_connectors=conn_none),
        disconnection_attribution=attribution,
        connectors=sorted(results, key=lambda r: (r["classification"], -r["length_m"])),
    )

    path = os.path.join(OUT_ROOT, date, "review", "connector-classification.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"connectors in network: {len(results)}  (426 proposed across passes)")
    for k, v in sorted(counts.items()):
        print(f"  {k:<26} {v['n']:>4}  {v['m']/M_PER_MILE:>7.4f} mi")
    print()
    for c in (conn_none, conn_all, conn_high):
        m = c["main_component"]
        print(f"  {c['label']:<42} components={c['components']:<4} "
              f"main={m['nodes']} nodes / {m['required_miles']:.2f} req mi "
              f"({c['main_component_required_share']:.1%})  "
              f"stranded req={c['unresolved_required_miles']:.2f} mi")
    print("\ntop disconnected components (HIGH_CONFIDENCE-only graph):")
    for c in conn_high["largest_disconnected"][:10]:
        print(f"   comp {c['component']:<3} {c['segments']:>3} segs "
              f"{c['miles']:>6.3f} mi  req {c['required_miles']:>6.3f} mi  "
              f"{', '.join(c['sample_names'][:3])}")
    print(f"\nattribution: {json.dumps(attribution['summary'], indent=1)}")
    print(f"\n-> {path}")


def attribute_disconnection(segs, results, conn_high, conn_all):
    """Why is required mileage stranded: isolation, missing data, or a rejected connector?"""
    rejected = {r["id"] for r in results if r["classification"] != "HIGH_CONFIDENCE"}
    high = {r["id"] for r in results if r["classification"] == "HIGH_CONFIDENCE"}

    _, node_comp_all, comps_all = connectivity(segs, high | rejected, "x")[0], None, None
    # Recompute membership maps directly.
    def comp_map(routable):
        G = nx.Graph()
        for s in segs:
            if not s["walkable"] or s["role"] == "EXCLUDED":
                continue
            if s["source"]["dataset"] == "DERIVED" and s["id"] not in routable:
                continue
            G.add_edge(s["start_node_id"], s["end_node_id"])
        comps = sorted(nx.connected_components(G), key=len, reverse=True)
        return {n: ci for ci, c in enumerate(comps) for n in c}

    m_high = comp_map(high)
    m_all = comp_map(high | rejected)

    recovered_by_rejected = 0.0   # in main only if rejected connectors are allowed
    truly_isolated = 0.0          # off main even with every connector
    off_main_high = []
    for s in segs:
        if s["role"] != "REQUIRED":
            continue
        L = float(s["length_m"]) / M_PER_MILE
        in_main_high = m_high.get(s["start_node_id"]) == 0
        in_main_all = m_all.get(s["start_node_id"]) == 0
        if in_main_high:
            continue
        off_main_high.append(dict(id=s["id"], name=s["display_name"],
                                  type=s["segment_type"], miles=round(L, 4),
                                  recovered_by_rejected_connector=bool(in_main_all)))
        if in_main_all:
            recovered_by_rejected += L
        else:
            truly_isolated += L

    return dict(
        summary=dict(
            required_miles_off_main_high_confidence=round(recovered_by_rejected + truly_isolated, 3),
            caused_by_rejected_connectors=round(recovered_by_rejected, 3),
            caused_by_isolation_or_missing_data=round(truly_isolated, 3),
        ),
        interpretation=(
            "'caused_by_rejected_connectors' is required mileage that WOULD reach the "
            "main graph if we routed over connectors we do not trust — recoverable by "
            "reviewing those specific connectors. 'caused_by_isolation_or_missing_data' "
            "is off-main even with every connector allowed: either a genuinely isolated "
            "stub, or a real gap in the source data."),
        segments=sorted(off_main_high, key=lambda x: -x["miles"]),
    )


if __name__ == "__main__":
    main()
