"""Virginia Tech campus coverage report.

Answers, from the data we can actually reach: what walkable campus infrastructure
exists in the canonical network, what is known to be missing, and what a human has to
decide. Source-priority evaluation (VGIN, then VT GIS, then OSM, then digitising) is
recorded here too, including which of those sources could not be evaluated and why.

Usage: python3 -m pipeline.build.campus_report [--date YYYY-MM-DD]
"""
import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone

from shapely.geometry import shape
from shapely.ops import transform

from . import geo

OUT_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out")
M_PER_MILE = 1609.344

# Campus streets probed by name against the full 1,547-feature Roads layer during the
# Phase 2a schema inspection and re-checked here. "stub" means the town carries only
# the few metres where the campus road meets a town street.
CAMPUS_STREET_PROBES = [
    "drillfield", "duck pond", "perry", "old turner", "beamer", "spring",
    "tech center", "stadium", "coliseum", "oak lane", "west campus", "w campus",
    "alumni", "stanger", "burruss", "mcbryde", "washington", "southgate",
    "kent", "turner", "prices fork",
]

SOURCE_PRIORITY = [
    dict(rank=1, source="VGIN Virginia Road Centerlines (RCL)",
         host="vginmaps.vdem.virginia.gov",
         status="NOT_EVALUATED",
         reason="Host denied by the build environment's egress policy (403 at the "
                "gateway on every attempt). The Hub site vgin.vdem.virginia.gov is "
                "reachable but publishes RCL only as a 112 MB File Geodatabase "
                "download served from the blocked host. No schema and no geometry were "
                "retrieved; nothing about RCL's campus coverage is asserted here."),
    dict(rank=2, source="Virginia Tech public GIS / campus map / building data",
         host="gis.vt.edu, www.vt.edu",
         status="NOT_EVALUATED",
         reason="Both hosts denied by the egress policy. VT's ArcGIS organisation, if "
                "it has a public open-data endpoint, was never reached."),
    dict(rank=3, source="OpenStreetMap",
         host="overpass-api.de",
         status="NOT_EVALUATED",
         reason="Host denied by the egress policy. Separately, OSM would require the "
                "ODbL analysis in data-audit §2.4 before any geometry entered the "
                "canonical network; it remains a documented comparison option, not a "
                "merge candidate."),
    dict(rank=4, source="Manual digitisation",
         host="n/a",
         status="RECOMMENDED_FALLBACK",
         reason="Recommended only for what remains missing after 1-3 are evaluated. "
                "Scope is small: roughly 5 miles of drivable campus street. Keeps the "
                "canonical network licence-clean, which is the property audit §2.4 was "
                "designed to protect."),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = ap.parse_args()
    date = args.date
    outdir = os.path.join(OUT_ROOT, date)

    zoning = geo.load("zoning", date)
    campus = next((g for a, g in zoning if (a.get("Labels") or "").strip() == "UNIV"), None)
    if campus is None:
        raise SystemExit("no UNIV zoning polygon in the snapshot")

    roads = geo.load("roads", date)
    paths_raw = geo.load("paths", date)

    with open(os.path.join(outdir, "segments.geojson")) as f:
        segs = json.load(f)["features"]

    # --- what the town's Roads layer has inside the campus polygon --------
    in_campus_roads = []
    for attrs, g in roads:
        if campus.intersects(g.interpolate(0.5, normalized=True)):
            in_campus_roads.append((attrs, g))
    road_names = defaultdict(float)
    for attrs, g in in_campus_roads:
        road_names[(attrs.get("LABEL") or "?").strip()] += g.length

    # --- name probes across the whole Roads layer -------------------------
    probes = []
    for probe in CAMPUS_STREET_PROBES:
        hits = [(a.get("LABEL"), g.length) for a, g in roads
                if probe in (a.get("LABEL") or "").lower()]
        total_m = sum(h[1] for h in hits)
        probes.append(dict(
            probe=probe, features=len(hits),
            miles=round(total_m / M_PER_MILE, 3),
            labels=sorted({h[0] for h in hits}),
            verdict=("ABSENT" if not hits
                     else "STUB_ONLY" if total_m < 100
                     else "PRESENT"),
        ))

    # --- campus pedestrian infrastructure in Paths ------------------------
    campus_paths = []
    for attrs, g in paths_raw:
        if campus.intersects(g.interpolate(0.5, normalized=True)):
            campus_paths.append((attrs, g))
    by_type = defaultdict(lambda: {"n": 0, "m": 0.0})
    by_owner = defaultdict(lambda: {"n": 0, "m": 0.0})
    named = defaultdict(float)
    for attrs, g in campus_paths:
        t = (attrs.get("Type") or "?").strip()
        o = (attrs.get("Owner") or "").strip() or "(blank)"
        by_type[t]["n"] += 1
        by_type[t]["m"] += g.length
        by_owner[o]["n"] += 1
        by_owner[o]["m"] += g.length
        nm = (attrs.get("Road") or "").strip()
        if nm:
            named[nm] += g.length

    # --- how the canonical network classified campus features -------------
    canon = defaultdict(lambda: {"n": 0, "m": 0.0})
    campus_segments = []
    for f in segs:
        p = f["properties"]
        if not p.get("in_campus_core"):
            continue
        g = transform(geo._to_proj, shape(f["geometry"]))
        key = f"{p['role']}::{p['segment_type']}"
        canon[key]["n"] += 1
        canon[key]["m"] += g.length
        campus_segments.append(dict(
            id=p["id"], name=p["display_name"], role=p["role"],
            role_status=p["role_status"], segment_type=p["segment_type"],
            surface=p.get("surface"), owner=p.get("ownership"),
            miles=round(g.length / M_PER_MILE, 4),
            reasons=p.get("review_reasons") or [],
        ))

    def fmt(d):
        return {k: {"features": v["n"], "miles": round(v["m"] / M_PER_MILE, 3)}
                for k, v in sorted(d.items(), key=lambda x: -x[1]["m"])}

    report = dict(
        generated_at=datetime.now(timezone.utc).isoformat(),
        snapshot_date=date,
        campus_polygon=dict(
            source="Town Zoning, Labels='UNIV' (single polygon)",
            area_sq_mi=round(campus.area / 2589988.11, 3),
            status="DRAFT",
            caveat=("This is the town's zoning district, not a curated campus core. "
                    "D1a asks for a hand-drawn boundary that excludes agricultural "
                    "research land, the airport and the golf course; those are largely "
                    "outside this polygon already, but the polygon has not been "
                    "reviewed feature by feature."),
        ),
        town_roads_inside_campus=dict(
            features=len(in_campus_roads),
            miles=round(sum(g.length for _, g in in_campus_roads) / M_PER_MILE, 3),
            by_name={k: round(v / M_PER_MILE, 4) for k, v in
                     sorted(road_names.items(), key=lambda x: -x[1])},
        ),
        street_name_probes=probes,
        missing_campus_streets=[p["probe"] for p in probes if p["verdict"] == "ABSENT"],
        stub_only_campus_streets=[p["probe"] for p in probes if p["verdict"] == "STUB_ONLY"],
        campus_paths_in_source=dict(
            features=len(campus_paths),
            miles=round(sum(g.length for _, g in campus_paths) / M_PER_MILE, 3),
            by_type=fmt(by_type), by_owner=fmt(by_owner),
            named_features={k: round(v / M_PER_MILE, 4) for k, v in
                            sorted(named.items(), key=lambda x: -x[1])[:40]},
        ),
        campus_in_canonical_network=fmt(canon),
        campus_segments=sorted(campus_segments, key=lambda s: -s["miles"]),
        source_priority_evaluation=SOURCE_PRIORITY,
        classification_policy=(
            "Campus paths are NOT auto-REQUIRED. D1b asks for a curated selection of "
            "major pedestrian ways, so every campus path enters the network as "
            "OPTIONAL_CONNECTOR with role_status=NEEDS_REVIEW and is listed here for a "
            "human to promote or leave as a connector."),
    )

    path = os.path.join(outdir, "review", "vt-campus-coverage.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"campus polygon: {report['campus_polygon']['area_sq_mi']} sq mi (DRAFT)")
    print(f"town roads inside campus: {report['town_roads_inside_campus']['features']} features, "
          f"{report['town_roads_inside_campus']['miles']} mi")
    print(f"campus paths in source: {report['campus_paths_in_source']['features']} features, "
          f"{report['campus_paths_in_source']['miles']} mi")
    print(f"  by owner: {report['campus_paths_in_source']['by_owner']}")
    print(f"\nABSENT from town Roads: {report['missing_campus_streets']}")
    print(f"STUB ONLY: {report['stub_only_campus_streets']}")
    print(f"\ncanonical network inside campus: {report['campus_in_canonical_network']}")
    print(f"\n-> {path}")


if __name__ == "__main__":
    main()
