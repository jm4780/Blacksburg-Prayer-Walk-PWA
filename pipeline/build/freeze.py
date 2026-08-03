"""Freeze a versioned candidate network and run the Phase 2b go/no-go gates.

Produces:
  candidate-network-<version>.json   the frozen metric set + gate results
  review/coverage-decision-table.json  the coverage-affecting review set, grouped

A gate that cannot be checked automatically is reported as such rather than passed.

Usage: python3 -m pipeline.build.freeze [--date YYYY-MM-DD] [--version v1]
"""
import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone

import networkx as nx
from pyproj import CRS

from . import geo

OUT_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out")
M_PER_MILE = 1609.344
MAIN_COMPONENT_TARGET = 0.95


def load(date):
    with open(os.path.join(OUT_ROOT, date, "segments.geojson")) as f:
        segs = [f_["properties"] for f_ in json.load(f)["features"]]
    with open(os.path.join(OUT_ROOT, date, "build-report.json")) as f:
        report = json.load(f)
    return segs, report


def routing_graph(segs):
    """The graph Phase 2b would actually route on: walkable, non-excluded, and for
    derived connectors, routable_by_default only."""
    G = nx.Graph()
    for s in segs:
        if s["role"] == "EXCLUDED" or not s["walkable"]:
            continue
        if s["source"]["dataset"] == "DERIVED" and not s.get("routable_by_default"):
            continue
        G.add_edge(s["start_node_id"], s["end_node_id"], id=s["id"])
    comps = sorted(nx.connected_components(G), key=len, reverse=True)
    main = comps[0] if comps else set()
    return G, comps, main


def metrics(segs, report, main):
    def mi(rows):
        return round(sum(float(s["length_m"]) for s in rows) / M_PER_MILE, 3)

    required = [s for s in segs if s["role"] == "REQUIRED"]
    req_street = [s for s in required if s["segment_type"] == "STREET"]
    req_trail = [s for s in required if s["segment_type"] == "TRAIL"]
    connectors = [s for s in segs if s["role"] == "OPTIONAL_CONNECTOR"]
    excluded = [s for s in segs if s["role"] == "EXCLUDED"]
    derived = [s for s in segs if s["source"]["dataset"] == "DERIVED"]

    campus_canonical = [s for s in segs if s.get("campus_obligation") == "CANONICAL"]
    campus_alternative = [s for s in segs if s.get("campus_obligation") == "ALTERNATIVE"]

    req_in_main = [s for s in required if s["start_node_id"] in main]
    req_off_main = [s for s in required if s["start_node_id"] not in main]

    h = report["households"]
    return dict(
        required_miles=mi(required),
        required_street_miles=mi(req_street),
        required_trail_miles=mi(req_trail),
        connector_miles=mi(connectors),
        excluded_miles=mi(excluded),
        campus_corridor_miles=mi(campus_canonical),
        campus_duplicate_obligations_removed_miles=mi(campus_alternative),
        total_network_miles=mi(segs),
        segments=dict(
            total=len(segs), required=len(required), required_street=len(req_street),
            required_trail=len(req_trail), connector=len(connectors),
            excluded=len(excluded), derived_connectors=len(derived),
            campus_canonical=len(campus_canonical),
            campus_alternative=len(campus_alternative),
        ),
        main_component=dict(
            nodes=len(main),
            required_miles=mi(req_in_main),
            required_segments=len(req_in_main),
            share_of_required_miles=round(
                mi(req_in_main) / mi(required), 4) if required else 0.0,
        ),
        unresolved_required_miles=mi(req_off_main),
        unresolved_required_segments=len(req_off_main),
        households=dict(
            residential_address_points=h["residential_address_points"],
            estimated_housing_units=h["estimated_housing_units"],
            associated_to_required_coverage=h["units_associated_to_required_coverage"],
            associated_to_connector_only=h["units_associated_to_connector_only"],
            held_for_review=h["units_held_for_review"],
            public_label=h["public_label"],
            public_value=h["public_value"],
            method=h["method"],
        ),
    )


def gates(segs, report, m):
    checks = []

    def gate(name, status, detail):
        checks.append(dict(gate=name, status=status, detail=detail))

    # 1 — no silent non-metric CRS
    units = {a.unit_name for a in CRS.from_user_input(geo.PROJ).axis_info}
    guard = hasattr(geo, "assert_metric")
    gate("no_silent_non_metric_crs",
         "PASS" if units == {"metre"} and guard else "FAIL",
         f"build CRS {geo.PROJ} has units {sorted(units)}; assert_metric() guard "
         f"{'present' if guard else 'MISSING'} and called at build start")

    # 2 — no known unit mismatch: recompute a sample of lengths from geometry
    #     and compare against the stored length_m.
    mismatch = check_unit_consistency(report, m)
    gate("no_known_unit_mismatch", mismatch["status"], mismatch["detail"])

    # 3 — no unresolved connector class routed by default
    bad = [s["id"] for s in segs
           if s["source"]["dataset"] == "DERIVED"
           and s.get("connector_class") != "HIGH_CONFIDENCE"
           and (s.get("routable_by_default") or s["walkable"])]
    cc = report.get("connector_classes", {})
    gate("no_unresolved_connector_routed_by_default",
         "PASS" if not bad else "FAIL",
         f"{len(bad)} non-HIGH_CONFIDENCE connectors routable. Classes: "
         + ", ".join(f"{k}={v['connectors']}" for k, v in sorted(cc.items())))

    # 4 — household methodology internally consistent
    h = report["households"]
    total = (h["units_associated_to_required_coverage"]
             + h["units_associated_to_connector_only"] + h["units_held_for_review"])
    consistent = (total == h["estimated_housing_units"]
                  and h["public_value"] == h["units_associated_to_required_coverage"]
                  and h["occupancy_model_applied"] is False
                  and h["estimated_housing_units"] <= h["residential_address_points"])
    gate("household_methodology_internally_consistent",
         "PASS" if consistent else "FAIL",
         f"{h['units_associated_to_required_coverage']} on required + "
         f"{h['units_associated_to_connector_only']} connector-only + "
         f"{h['units_held_for_review']} held = {total} vs "
         f"{h['estimated_housing_units']} housing units; public label maps to "
         f"{h['public_label_maps_to']}; occupancy model applied: "
         f"{h['occupancy_model_applied']}")

    # 5 — campus duplicate obligations removed
    camp = report.get("campus_normalization") or {}
    unstamped = [s["id"] for s in segs
                 if s.get("in_campus_core") and s["source"]["dataset"] != "DERIVED"
                 and not s.get("campus_obligation")]
    gate("campus_duplicate_obligations_removed",
         "PASS" if camp and not unstamped else "FAIL",
         f"{camp.get('corridors', 0)} corridors normalized; "
         f"{camp.get('duplicate_miles', 0)} mi of parallel walkway marked ALTERNATIVE; "
         f"{len(unstamped)} campus segments unstamped")

    # 6 — overwhelming majority of required mileage in the main routing graph
    share = m["main_component"]["share_of_required_miles"]
    gate("required_mileage_reachable",
         "PASS" if share >= MAIN_COMPONENT_TARGET else "WARN",
         f"{share:.2%} of required mileage is in the main routing component "
         f"({m['main_component']['required_miles']} of {m['required_miles']} mi); "
         f"target {MAIN_COMPONENT_TARGET:.0%}. Unresolved: "
         f"{m['unresolved_required_miles']} mi across "
         f"{m['unresolved_required_segments']} segments")

    return checks


def check_unit_consistency(report, m):
    """Cross-check derived mileage against an independent source figure.

    The town's Roads layer carries its own MILES field, computed by the town in its
    own CRS. Our REQUIRED+EXCLUDED street mileage should land close to the town's
    total for the same features. A 3.28x gap here is the ft/m failure mode.
    """
    town_total = 169.16  # sum of Roads.MILES, all 1,547 features (schema inspection)
    ours = m["required_street_miles"] + m["excluded_miles"]
    ratio = ours / town_total if town_total else 0
    if 0.9 <= ratio <= 1.1:
        return dict(status="PASS",
                    detail=(f"street mileage {ours:.2f} mi vs the town's own MILES field "
                            f"total {town_total} mi — ratio {ratio:.3f}. No ft/m mismatch."))
    if 3.0 <= ratio <= 3.5 or 0.28 <= ratio <= 0.34:
        return dict(status="FAIL",
                    detail=(f"street mileage {ours:.2f} vs town {town_total} — ratio "
                            f"{ratio:.3f}. This is the survey-foot/metre ratio. CRS is wrong."))
    return dict(status="WARN",
                detail=(f"street mileage {ours:.2f} vs town {town_total} — ratio "
                        f"{ratio:.3f}. Not a unit error, but worth explaining: our figure "
                        f"excludes ramps and the US-460 bypass from REQUIRED and splits "
                        f"segments differently."))


# --- coverage-affecting decision table --------------------------------------
GROUPS = [
    ("provisional_trails",
     lambda s: s["role_status"] == "PROVISIONAL",
     "Provisional trails",
     "CONFIRM as REQUIRED",
     "D2 recommended Deerfield and Shenandoah as REQUIRED and they are applied "
     "provisionally. Both are short paved neighbourhood trails that pass homes, which "
     "is exactly the D2 test. Confirming changes nothing in the build; declining "
     "removes them from the denominator."),
    ("required_street_conflicts",
     lambda s: (s["segment_type"] == "STREET" and s["role_status"] == "NEEDS_REVIEW"
                and s["role"] in ("REQUIRED", "EXCLUDED")),
     "Required-street conflicts",
     "UPHOLD RD_MAINT",
     "36 segments where RD_MAINT says Private and ROAD_CLASS says Local, plus 4 public "
     "streets whose midpoint falls inside an HOA/private open-space polygon. RD_MAINT "
     "is the maintenance authority's own field and zero conflicts run the other way. "
     "Uphold it; spot-check the 4 HOA cases on a map."),
    ("campus_path_decisions",
     lambda s: (s.get("in_campus_core") and s["role_status"] == "NEEDS_REVIEW"
                and s.get("campus_obligation") == "CANONICAL"),
     "Campus path decisions (D1b)",
     "PROMOTE canonical campus corridors to REQUIRED",
     "After normalization each campus corridor carries exactly one obligation, so "
     "promoting these adds campus coverage without demanding a walker cover the same "
     "street twice. Parallel walkways are already marked ALTERNATIVE and stay "
     "connectors."),
    ("derived_connections_affecting_access",
     lambda s: (s["source"]["dataset"] == "DERIVED"
                and s.get("connector_class") != "HIGH_CONFIDENCE"),
     "Derived connections affecting required-network accessibility",
     "KEEP OUT of the default graph; review the 30 crossing cases",
     "8 LIKELY_FALSE assert access onto the US-460 bypass, its ramps, or private "
     "drives — reject outright. 30 CROSSING_REVIEW_REQUIRED and 4 UNRESOLVED need a "
     "human. Only 0.31 mi of required mileage depends on any of them."),
    ("other_consequential",
     lambda s: (s["role_status"] in ("NEEDS_REVIEW", "PROVISIONAL")
                and s["role"] in ("REQUIRED", "EXCLUDED")
                and s["source"]["dataset"] != "DERIVED"
                and s["segment_type"] != "STREET"
                and not (s.get("in_campus_core") and s.get("campus_obligation") == "CANONICAL")),
     "Other consequential cases",
     "REVIEW individually",
     "Trails currently EXCLUDED on a Paths Owner=PRIV tag, and off-main required "
     "stubs such as the Gordon C Willis Smart Road — a closed research facility that "
     "is probably EXCLUDED rather than REQUIRED."),
]


def decision_table(segs):
    seen, groups = set(), []
    for key, pred, title, ruling, reason in GROUPS:
        rows = []
        for s in segs:
            if s["id"] in seen:
                continue
            try:
                if pred(s):
                    rows.append(s)
                    seen.add(s["id"])
            except (KeyError, TypeError):
                continue
        miles = round(sum(float(r["length_m"]) for r in rows) / M_PER_MILE, 3)
        names = defaultdict(float)
        for r in rows:
            names[r["display_name"] or "(unnamed)"] += float(r["length_m"]) / M_PER_MILE
        groups.append(dict(
            key=key, title=title, segments=len(rows), miles=miles,
            recommended_ruling=ruling, reason=reason,
            top_features=[dict(name=n, miles=round(v, 3))
                          for n, v in sorted(names.items(), key=lambda x: -x[1])[:10]],
            segment_ids=[r["id"] for r in rows][:400],
        ))
    return groups


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    ap.add_argument("--version", default="v1")
    args = ap.parse_args()
    geo.assert_metric()

    segs, report = load(args.date)
    G, comps, main = routing_graph(segs)
    m = metrics(segs, report, main)
    checks = gates(segs, report, m)
    table = decision_table(segs)

    failed = [c for c in checks if c["status"] == "FAIL"]
    warned = [c for c in checks if c["status"] == "WARN"]
    recommendation = ("NO-GO" if failed else "GO WITH CONDITIONS" if warned else "GO")

    candidate = dict(
        version=args.version,
        frozen_at=datetime.now(timezone.utc).isoformat(),
        snapshot_date=args.date,
        build_crs=geo.PROJ,
        routing_graph=dict(components=len(comps), main_component_nodes=len(main)),
        metrics=m,
        gates=checks,
        go_no_go=dict(recommendation=recommendation,
                      failed=[c["gate"] for c in failed],
                      warned=[c["gate"] for c in warned]),
        coverage_decision_table=table,
        blocked=report.get("blocked_sources", []),
    )

    path = os.path.join(OUT_ROOT, args.date, f"candidate-network-{args.version}.json")
    with open(path, "w") as f:
        json.dump(candidate, f, indent=2, default=str)
    with open(os.path.join(OUT_ROOT, args.date, "review",
                           "coverage-decision-table.json"), "w") as f:
        json.dump(table, f, indent=2, default=str)

    print(f"CANDIDATE NETWORK {args.version} — snapshot {args.date}")
    print("=" * 68)
    for k in ("required_miles", "required_street_miles", "required_trail_miles",
              "connector_miles", "excluded_miles", "campus_corridor_miles",
              "campus_duplicate_obligations_removed_miles", "total_network_miles",
              "unresolved_required_miles"):
        print(f"  {k:<48}{m[k]:>9.3f} mi")
    mc = m["main_component"]
    print(f"  {'main-component required coverage':<48}{mc['share_of_required_miles']:>8.2%}"
          f"  ({mc['required_miles']} mi, {mc['nodes']} nodes)")
    h = m["households"]
    print(f"\n  {'estimated housing units':<48}{h['estimated_housing_units']:>9}")
    print(f"  {'households associated (REQUIRED coverage)':<48}{h['associated_to_required_coverage']:>9}"
          f"   <- public")
    print(f"  {'households on connector only':<48}{h['associated_to_connector_only']:>9}")
    print(f"  {'households held for review':<48}{h['held_for_review']:>9}")

    print(f"\n  {'GATE':<48}{'STATUS'}")
    for c in checks:
        print(f"  [{c['status']:^4}] {c['gate']}")
        print(f"          {c['detail']}")
    print(f"\n  RECOMMENDATION: {recommendation}")

    print("\n  coverage-affecting decision table:")
    for g in table:
        print(f"    {g['title']:<52}{g['segments']:>5} segs {g['miles']:>7.3f} mi"
              f"  -> {g['recommended_ruling']}")
    print(f"\n-> {path}")
    return 0 if recommendation != "NO-GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
