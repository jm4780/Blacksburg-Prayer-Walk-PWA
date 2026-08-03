"""Focused review artifact for the connectors that isolate the Corporate Research Center.

Phase 2b claimed the CRC was cut off by the US-460 bypass. That was wrong, and the
correction is the reason this file exists: the CRC is not severed by a limited-access
highway, it is separated by a handful of short at-grade links that the connector
classifier marked CROSSING_REVIEW_REQUIRED because they step into or across a
trafficked roadway. Nobody has looked at them.

This module does not promote anything. Network v1.2 keeps the CRC as a valid
independent routing area and keeps every one of these connectors out of the default
routing graph. The artifact exists so a human with local knowledge — or, later, aerial
imagery — can answer one question per row: *is there actually a crossing here?*

Promotion, if it ever happens, is a curation entry plus a new network version, never
an edit to this file's output.

  python3 -m pipeline.build.crc_review [--date YYYY-MM-DD]
"""
import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone

import networkx as nx
from shapely.geometry import shape
from shapely.ops import transform

from . import geo

OUT_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out")
M_PER_MILE = 1609.344

# Street names that identify Corporate Research Center geometry. Matched
# case-insensitively as substrings of display_name.
CRC_MARKERS = ("research center", "kraft dr", "kraft drive", "rimrock",
               "innovation dr", "pratt dr", "knollwood", "smoot", "crc ")

# Membership is decided by *name*, not by component. An earlier version selected
# crossings by "has an endpoint in the CRC component", which missed SEG-000156 — a
# connector that starts on Research Center Drive Trail but whose both endpoints fall
# outside the CRC component in the default graph, so it looked like somebody else's
# problem. It is a CRC crossing; it belongs in the CRC review.


def default_graph_components(feats):
    """Component membership under the v1.2 default routing rule.

    In: REQUIRED and walkable OPTIONAL_CONNECTOR from authoritative sources, plus
    HIGH_CONFIDENCE derived connectors. Out: everything else. Same rule as
    api/routing/network.in_routing_graph, restated here because the pipeline does not
    import the routing package.
    """
    G = nx.Graph()
    for f in feats:
        p = f["properties"]
        derived = p["source"]["dataset"] == "DERIVED"
        if derived:
            if p.get("connector_class") != "HIGH_CONFIDENCE":
                continue
        else:
            if p["role"] == "EXCLUDED" or not p.get("walkable"):
                continue
        G.add_edge(p["start_node_id"], p["end_node_id"])
    comps = sorted(nx.connected_components(G), key=len, reverse=True)
    return {n: ci for ci, c in enumerate(comps) for n in c}, comps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = ap.parse_args()
    date = args.date
    geo.assert_metric()

    with open(os.path.join(OUT_ROOT, date, "segments.geojson")) as f:
        feats = json.load(f)["features"]
    by_id = {f["properties"]["id"]: f for f in feats}
    node_comp, comps = default_graph_components(feats)

    # Which component is the CRC? The one holding the most CRC-named required mileage.
    crc_score = defaultdict(float)
    for f in feats:
        p = f["properties"]
        nm = (p.get("display_name") or "").lower()
        if p["role"] != "REQUIRED" or not any(m in nm for m in CRC_MARKERS):
            continue
        ci = node_comp.get(p["start_node_id"])
        if ci is not None:
            crc_score[ci] += float(p["length_m"])
    crc_ci = max(crc_score, key=crc_score.get) if crc_score else None

    # Component profiles, so the artifact says what is on each side of a crossing.
    profile = {}
    for ci, comp in enumerate(comps):
        req_m = tot_m = 0.0
        hh = 0
        names = defaultdict(float)
        for f in feats:
            p = f["properties"]
            if node_comp.get(p["start_node_id"]) != ci:
                continue
            L = float(p["length_m"])
            tot_m += L
            if p["role"] == "REQUIRED":
                req_m += L
                hh += int(p.get("estimated_household_count") or 0)
                if p.get("display_name"):
                    names[p["display_name"]] += L
        profile[ci] = dict(
            component=ci, nodes=len(comp),
            required_miles=round(req_m / M_PER_MILE, 3),
            total_miles=round(tot_m / M_PER_MILE, 3), households=hh,
            top_streets=[n for n, _ in sorted(names.items(), key=lambda x: -x[1])[:5]])

    # Every rejected derived connector that either bridges two components or touches
    # the CRC. A connector with one dangling end still belongs in the CRC review — it
    # is a crossing somebody asserted at the CRC boundary, and "it leads nowhere in the
    # current graph" is a review finding, not a reason to hide it.
    rejected = []
    for f in feats:
        p = f["properties"]
        if p["source"]["dataset"] != "DERIVED" or p.get("connector_class") == "HIGH_CONFIDENCE":
            continue
        a, b = node_comp.get(p["start_node_id"]), node_comp.get(p["end_node_id"])
        rejected.append((p, a, b))

    # Nodes belonging to CRC-named authoritative geometry.
    crc_nodes = set()
    for f in feats:
        p = f["properties"]
        if p["source"]["dataset"] == "DERIVED":
            continue
        if any(m in (p.get("display_name") or "").lower() for m in CRC_MARKERS):
            crc_nodes.add(p["start_node_id"])
            crc_nodes.add(p["end_node_id"])

    rows = []
    for p, a, b in rejected:
        sides = [x for x in (a, b) if x is not None]
        touches_crc = (p["start_node_id"] in crc_nodes
                       or p["end_node_id"] in crc_nodes)
        bridges = a is not None and b is not None and a != b
        if not bridges and not touches_crc:
            continue
        info = p["source"].get("derived_from") or {}
        other = next((x for x in sides if x != crc_ci), None) if touches_crc else None
        rows.append(dict(
            segment_id=p["id"], classification=p.get("connector_class"),
            length_m=round(float(p["length_m"]), 1),
            joins_components=[a, b], bridges_components=bridges,
            touches_crc=touches_crc,
            other_side_component=other,
            from_feature=info.get("stranded_name"),
            to_feature=info.get("joined_to_name"),
            side_a=profile.get(a), side_b=profile.get(b),
            required_miles_on_smaller_side=round(
                min(profile[a]["required_miles"], profile[b]["required_miles"]), 3)
            if bridges else 0.0,
            classifier_reasons=[r for r in (p.get("review_reasons") or [])
                                if "cross" in r.lower() or "steps into" in r.lower()
                                or "m gap" in r.lower() or "insufficient signal" in r.lower()],
            geometry=by_id[p["id"]]["geometry"],
            review_question=(
                "Is there a lawful, physically usable pedestrian crossing at this "
                "point? Answer YES only with direct evidence — a marked crosswalk, a "
                "signal, a curb ramp pair, or first-hand local knowledge. Absence of "
                "evidence is not a yes."),
            decision=None, decided_by=None, decided_at=None, evidence=None,
        ))

    crc_rows = [r for r in rows if r["touches_crc"]]
    rows.sort(key=lambda r: (not r["touches_crc"], -r["required_miles_on_smaller_side"]))

    # What would promoting the CRC crossings actually buy? Answered by rebuilding the
    # component map with them allowed. This is the fact that decides whether the review
    # is worth anyone's afternoon — and the answer turns out to be "not connection to
    # downtown", which is not what the crossing names suggest.
    crc_ids = {r["segment_id"] for r in crc_rows}
    G2 = nx.Graph()
    for f in feats:
        p = f["properties"]
        derived = p["source"]["dataset"] == "DERIVED"
        if derived and p.get("connector_class") != "HIGH_CONFIDENCE" and p["id"] not in crc_ids:
            continue
        if not derived and (p["role"] == "EXCLUDED" or not p.get("walkable")):
            continue
        G2.add_edge(p["start_node_id"], p["end_node_id"])
    c2 = sorted(nx.connected_components(G2), key=len, reverse=True)
    nc2 = {n: ci for ci, c in enumerate(c2) for n in c}
    crc_node = next((n for n in comps[crc_ci]), None) if crc_ci is not None else None
    main_node = next((n for n in comps[0]), None) if comps else None
    joins_main = (crc_node is not None and main_node is not None
                  and nc2.get(crc_node) == nc2.get(main_node))
    gained_m = 0.0
    if crc_node is not None:
        merged = {n for n in nc2 if nc2[n] == nc2.get(crc_node)}
        for f in feats:
            p = f["properties"]
            if p["role"] == "REQUIRED" and p["start_node_id"] in merged \
                    and node_comp.get(p["start_node_id"]) != crc_ci:
                gained_m += float(p["length_m"])
    if_promoted = dict(
        crc_would_join_main_component=bool(joins_main),
        additional_required_miles_reachable_from_crc=round(gained_m / M_PER_MILE, 3),
        finding=(
            "Promoting every CRC crossing would join the CRC to the main network."
            if joins_main else
            "Promoting every CRC crossing would NOT join the CRC to the main network. "
            "Each of these links the CRC to a small isolated fragment, not to the town "
            "graph — so the review is worth doing for local CRC walkability, but it is "
            "not the thing that would let someone walk from the CRC to downtown. "
            "Whatever separates the CRC from the main component is not in this list."),
    )

    report = dict(
        generated_at=datetime.now(timezone.utc).isoformat(),
        snapshot_date=date,
        network_version="1.2",
        status="OPEN — no connector below is promoted, and none is in the routing graph",
        policy=(
            "Network v1.2 keeps every connector below out of the default routing graph "
            "and keeps the Corporate Research Center classified as a valid independent "
            "routing area. A walker starting in the CRC routes the CRC. The router "
            "never invents a crossing. Promoting any row here requires a curation "
            "entry with evidence and a new canonical-network version."),
        correction_of_record=(
            "Phase 2b reported the CRC as severed by the US-460 bypass. That was wrong. "
            "The bypass is EXCLUDED and unwalkable, but it is not what separates the "
            "CRC — these short at-grade links are. Corrected in docs/12; restated here "
            "so the review artifact does not inherit the error."),
        basemap_evidence=(
            "NONE. Every imagery and tile host is denied by this environment's egress "
            "policy, so no row below has been checked against an aerial. That is "
            "exactly why these are review items and not decisions."),
        crc_component=crc_ci,
        crc_profile=profile.get(crc_ci),
        if_all_crc_crossings_were_promoted=if_promoted,
        counts=dict(
            bridging_connectors_total=len(rows),
            crc_crossings=len(crc_rows),
            by_classification={
                k: sum(1 for r in rows if r["classification"] == k)
                for k in sorted({r["classification"] for r in rows})},
        ),
        crossings=rows,
    )

    path = os.path.join(OUT_ROOT, date, "review", "crc-crossings.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"CRC component: {crc_ci}  "
          f"{report['crc_profile']['required_miles'] if report['crc_profile'] else 0} required mi, "
          f"{report['crc_profile']['households'] if report['crc_profile'] else 0} households")
    print(f"bridging connectors held out of the routing graph: {len(rows)} "
          f"({len(crc_rows)} touching the CRC)")
    print(f"\n{'segment':<12}{'class':<26}{'m':>6}  {'comps':<10}{'req mi':>8}  link")
    for r in rows[:14]:
        mark = "*" if r["touches_crc"] else " "
        print(f"{mark}{r['segment_id']:<11}{r['classification']:<26}{r['length_m']:>6.1f}  "
              f"{str(r['joins_components']):<10}{r['required_miles_on_smaller_side']:>8.3f}  "
              f"{r['from_feature']} -> {r['to_feature']}")
    print(f"\nif all CRC crossings were promoted: {if_promoted['finding']}")
    print(f"\n-> {path}")


if __name__ == "__main__":
    main()
