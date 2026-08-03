"""Canonical network build: snapshots in, canonical segments + households out.

    fetch -> normalize -> split -> classify -> connect -> households -> identify -> report

Deterministic and re-runnable. Writes everything under pipeline/out/<date>/:

    segments.geojson        canonical network, WGS84, one feature per segment
    households.json         deduplicated dwelling units + their segment links
    build-report.json       counts, mileage, conflicts, validation, lineage
    review/*.json           everything a human has to look at

Usage: python3 -m pipeline.build.run [--date YYYY-MM-DD]
"""
import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone

from shapely.geometry import Point
from shapely.strtree import STRtree

from . import (campus_normalize, classify, connect, connector_review, curation,
               geo, households as hh)
from .names import address_name, normalize, road_name

OUT_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out")
M_PER_MILE = 1609.344
SIDEWALK_MATCH_M = 30.0  # a sidewalk this close to a same-named street is that street's


def miles(m):
    return round(m / M_PER_MILE, 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = ap.parse_args()
    date = args.date
    geo.assert_metric()
    outdir = os.path.join(OUT_ROOT, date)
    os.makedirs(os.path.join(outdir, "review"), exist_ok=True)

    log = {"name_fixes": [], "value_fixes": [], "anomalies": []}
    report = {"snapshot_date": date, "built_at": datetime.now(timezone.utc).isoformat()}

    # ------------------------------------------------------------------ load
    print("load")
    roads = geo.load("roads", date)
    paths = geo.load("paths", date)
    boundary_feats = geo.load("boundary", date)
    zoning = geo.load("zoning", date)
    address = geo.load("address", date)
    openspace = geo.load("openspace", date)
    boundary = boundary_feats[0][1]
    campus = next((g for a, g in zoning if (a.get("Labels") or "").strip() == "UNIV"), None)
    print(f"  roads={len(roads)} paths={len(paths)} address={len(address)} "
          f"campus_polygon={'yes' if campus is not None else 'NO'}")

    report["sources"] = {
        k: geo.load_meta(k, date)
        for k in ("roads", "paths", "boundary", "zoning", "address", "landuse",
                  "openspace", "building", "parks")
    }

    # ------------------------------------------------- sidewalk absorption
    print("absorb sidewalks and on-street bike facilities")
    road_by_name = defaultdict(list)
    for attrs, g in roads:
        _, norm = road_name(attrs, log["name_fixes"])
        road_by_name[norm].append(g)

    street_attr = defaultdict(lambda: {"has_sidewalk": False, "has_bike_facility": False,
                                       "sidewalk_material": None})
    keep_paths, absorbed = [], defaultdict(int)
    for attrs, g in paths:
        ptype = (attrs.get("Type") or "").strip()
        norm = classify.sidewalk_key(attrs, log["name_fixes"])
        mid = g.interpolate(0.5, normalized=True)
        near_same_named = any(rg.distance(mid) <= SIDEWALK_MATCH_M for rg in road_by_name.get(norm, []))

        if ptype in classify.ONSTREET_PATH_TYPES and near_same_named:
            street_attr[norm]["has_bike_facility"] = True
            absorbed["bike_facility"] += 1
            continue
        if ptype in classify.SIDEWALK_PATH_TYPES and near_same_named:
            street_attr[norm]["has_sidewalk"] = True
            street_attr[norm]["sidewalk_material"] = classify.normalize_material(
                attrs.get("Material"), attrs.get("OBJECTID"), log["value_fixes"])
            absorbed["sidewalk"] += 1
            continue
        if ptype in classify.ONSTREET_PATH_TYPES:
            # On-street facility with no matching street — a name problem, not an edge.
            absorbed["bike_facility_unmatched"] += 1
            log["anomalies"].append({
                "kind": "onstreet_path_unmatched", "type": ptype,
                "road": attrs.get("Road"), "source_id": attrs.get("OBJECTID")})
            continue
        keep_paths.append((attrs, g))

    print(f"  absorbed sidewalks={absorbed['sidewalk']} bike={absorbed['bike_facility']} "
          f"unmatched-onstreet={absorbed['bike_facility_unmatched']} "
          f"remaining path features={len(keep_paths)}")
    report["absorption"] = dict(absorbed)

    # ------------------------------------------------------------ node/split
    print("split at intersections")
    tagged = ([({"__src": "roads", **a}, g) for a, g in roads]
              + [({"__src": "paths", **a}, g) for a, g in keep_paths])
    exploded = [(a, part) for a, g in tagged for part in geo.explode_lines(g)]
    pieces, split_stats = geo.node_network(exploded)
    print(f"  {split_stats['inputs']} -> {split_stats['outputs']} pieces "
          f"({split_stats['split']} inputs were split)")

    node_ids, node_points, snap_log = geo.build_nodes(pieces)
    print(f"  nodes={len(node_points)} snaps>{geo.LOG_SNAP_M}m={len(snap_log)}")

    # ---------------------------------------------------------------- connect
    # Paths and Roads were digitised independently and share no nodes, so the
    # pedestrian layer arrives disconnected from the streets. Stitch it on.
    # Each pass only joins a component to a strictly larger one, so two stranded
    # fragments can never pair off and stay stranded together. That means a chain of
    # fragments takes several passes to reel in; iterate until it stops shrinking.
    print("connect stranded components")
    conn_stats, total_connectors, passes = None, 0, []
    for attempt in range(6):
        connectors, stats = connect.propose(pieces, node_ids, node_points)
        passes.append({"pass": attempt + 1, "components_before": stats["components_before"],
                       "connectors": stats["connectors"],
                       "unreachable": stats["components_unreachable"]})
        print(f"  pass {attempt + 1}: {stats['components_before']} components -> "
              f"{stats['connectors']} connectors, {stats['components_unreachable']} unreachable")
        if conn_stats is None:
            conn_stats = dict(stats)
        stalled = (len(passes) > 1
                   and stats["components_before"] >= passes[-2]["components_before"])
        if not connectors or stalled:
            conn_stats["components_after"] = stats["components_before"]
            conn_stats["unreachable"] = stats["unreachable"]
            if stalled:
                conn_stats["stopped_reason"] = (
                    "component count stopped falling; remaining components have nothing "
                    f"within {connect.MAX_CONNECTOR_M:.0f} m in a larger component")
            break
        total_connectors += len(connectors)
        exploded = exploded + connect.as_features(connectors, offset=total_connectors - len(connectors))
        pieces, split_stats = geo.node_network(exploded)
        node_ids, node_points, snap_log = geo.build_nodes(pieces)
    conn_stats["passes"] = passes
    conn_stats["connectors"] = total_connectors
    print(f"  total connectors={total_connectors}, pieces={len(pieces)}, nodes={len(node_points)}")

    keep_idx, dropped_dupes = geo.dedupe_collinear(pieces, node_ids)
    print(f"  duplicate-geometry dropped={len(dropped_dupes)}")

    pieces = [pieces[i] for i in keep_idx]
    node_ids = [node_ids[i] for i in keep_idx]
    degrees = geo.node_degrees(node_ids, len(node_points))

    report["split"] = dict(split_stats, nodes=len(node_points),
                           snaps_over_threshold=len(snap_log),
                           duplicate_geometry_dropped=len(dropped_dupes))
    report["connect"] = conn_stats

    # ------------------------------------------------------------- classify
    print("classify")
    conflicts = []
    segments = []
    for (attrs, g), (a_node, b_node) in zip(pieces, node_ids):
        src = attrs["__src"]
        if src == "derived":
            display, norm = None, None
            info = attrs.get("__derived_info") or {}
            cls = dict(
                segment_type="PEDESTRIAN_CONNECTOR", access_type="UNKNOWN",
                ownership=None, road_class=None, speed_limit=None, walk_stress=1,
                walkable=True, role="OPTIONAL_CONNECTOR", role_status="NEEDS_REVIEW",
                surface=None, grade_pct=None, grade_source="NOT_APPLICABLE",
                has_sidewalk=False, has_bike_facility=False, one_way=None,
                review_reasons=[
                    "SYNTHETIC: derived connector stitching a disconnected pedestrian "
                    f"component onto {info.get('joined_to_name') or 'the network'} "
                    f"({info.get('length_m')} m). Not observed in any source. Confirm the "
                    "crossing this implies actually exists before relying on it."],
            )
            source_id, global_id = attrs.get("OBJECTID"), None
        elif src == "roads":
            display, norm = road_name(attrs, log["name_fixes"])
            cls = classify.classify_road(attrs, conflicts, log["anomalies"])
            extra = street_attr.get(norm, {})
            cls["has_sidewalk"] = bool(extra.get("has_sidewalk"))
            cls["has_bike_facility"] = bool(extra.get("has_bike_facility"))
            cls["surface"] = None
            cls["grade_pct"] = None
            cls["grade_source"] = "NOT_APPLICABLE"
            source_id, global_id = attrs.get("OBJECTID"), attrs.get("GlobalID")
        else:
            display, norm = normalize(attrs.get("Road"), log["name_fixes"])
            in_campus = campus is not None and campus.intersects(g.interpolate(0.5, normalized=True))
            cls = classify.classify_path(attrs, norm, in_campus, log["value_fixes"])
            cls["has_sidewalk"] = False
            cls["has_bike_facility"] = False
            cls["in_campus_core"] = in_campus
            source_id, global_id = attrs.get("OBJECTID"), attrs.get("GlobalID")

        mid = g.interpolate(0.5, normalized=True)
        inside = boundary.contains(mid)
        crosses = not boundary.contains(g) and boundary.intersects(g)
        if not inside:
            cls["segment_type"] = "OUT_OF_AREA_CONNECTOR"
            cls["role"] = "OPTIONAL_CONNECTOR"
            cls["role_status"] = "AUTOMATIC"
            cls.setdefault("review_reasons", []).append("Midpoint outside town limits.")

        segments.append(dict(
            geometry=g,
            length_m=g.length,
            display_name=display,
            normalized_name=norm,
            start_node_id=a_node,
            end_node_id=b_node,
            is_dead_end=(degrees[a_node] == 1 or degrees[b_node] == 1),
            crosses_boundary=crosses,
            inside_boundary=inside,
            source=(dict(dataset="DERIVED", source_id=source_id, source_global_id=None,
                         source_layer_url=None, source_updated_at=None,
                         retrieved_at=report["built_at"], license_status="DERIVED",
                         derived_from=attrs.get("__derived_info"))
                    if src == "derived" else
                    dict(dataset=src, source_id=source_id, source_global_id=global_id,
                         source_layer_url=report["sources"][src]["source_url"],
                         source_updated_at=report["sources"][src]["source_updated_at"],
                         retrieved_at=report["sources"][src]["retrieved_at"],
                         license_status=report["sources"][src]["license_status"])),
            **cls,
        ))

    # HOA / privately-owned open space corroboration for private-drive detection.
    hoa = [g for a, g in openspace
           if (a.get("Type") or "").strip() in ("HOA Active", "HOA Inactive", "Privately Owned")]
    if hoa:
        hoa_tree = STRtree(hoa)
        for s in segments:
            if s["segment_type"] != "STREET" or s["role"] != "REQUIRED":
                continue
            mid = s["geometry"].interpolate(0.5, normalized=True)
            if any(hoa[i].contains(mid) for i in hoa_tree.query(mid)):
                s["role_status"] = "NEEDS_REVIEW"
                s["review_reasons"].append(
                    "Public per RD_MAINT but midpoint falls inside an HOA/privately-owned "
                    "open-space polygon — corroborating evidence of a private drive.")

    # -------------------------------------------------------- stable IDs
    print("assign stable ids")
    # Deterministic spatial order: south-to-north, then west-to-east on the midpoint.
    segments.sort(key=lambda s: (round(s["geometry"].interpolate(0.5, normalized=True).y, 2),
                                 round(s["geometry"].interpolate(0.5, normalized=True).x, 2),
                                 s["normalized_name"] or "", s["source"]["source_id"] or 0))
    for i, s in enumerate(segments, start=1):
        s["id"] = f"SEG-{i:06d}"

    # ------------------------------------------- connector trust + campus dedup
    # Both need the segment list, and both write decisions back onto it, so the
    # candidate network file carries them rather than living in a side report.
    print("classify connectors")
    for s in segments:
        s["_geom"] = s["geometry"]
    conn_classes = connector_review.classify(segments)
    by_id = {s["id"]: s for s in segments}
    conn_counts = defaultdict(lambda: {"n": 0, "m": 0.0})
    for c in conn_classes:
        s = by_id[c["id"]]
        s["connector_class"] = c["classification"]
        s["routable_by_default"] = c["classification"] == "HIGH_CONFIDENCE"
        s["review_reasons"] = list(s["review_reasons"]) + c["reasons"]
        if not s["routable_by_default"]:
            s["walkable"] = False
        conn_counts[c["classification"]]["n"] += 1
        conn_counts[c["classification"]]["m"] += s["length_m"]
    for s in segments:
        s.setdefault("connector_class", None)
        s.setdefault("routable_by_default", True)
    print("  " + " · ".join(f"{k}={v['n']}" for k, v in sorted(conn_counts.items())))
    report["connector_classes"] = {
        k: {"connectors": v["n"], "miles": miles(v["m"])} for k, v in sorted(conn_counts.items())}
    report["connector_policy"] = (
        "Only HIGH_CONFIDENCE connectors are routable by default. The rest stay in the "
        "network with routable_by_default=false and walkable=false so they are visible "
        "for review but cannot carry a route.")

    print("normalize campus corridors")
    camp = campus_normalize.normalize_segments(segments)
    for s in segments:
        s.setdefault("campus_corridor", None)
        s.setdefault("campus_obligation", None)
    print(f"  {camp['corridors']} corridors · canonical {camp['canonical_miles']:.3f} mi · "
          f"duplicate obligations removed {camp['duplicate_miles']:.3f} mi")
    report["campus_normalization"] = camp


    # --------------------------------------------------------- households
    print("households")
    household_records, hstats = hh.build_households(address, address_name, log["name_fixes"])
    print(f"  address points={hstats['address_points_total']} "
          f"residential={hstats['residential_address_points']} "
          f"housing units={hstats['estimated_housing_units']}")

    eligible = [s for s in segments if s["role"] in ("REQUIRED", "OPTIONAL_CONNECTOR")
                and s["walkable"]]
    profiles = hh.profile_complexes(household_records, eligible)

    unresolved_places, complex_report = set(), []
    for p in profiles:
        disposition, hold_mode, reasons, flags = hh.complex_disposition(p)
        v1_status, v1_reasons, v1_trigger = hh.complex_status(p)
        entry = dict(place_name=p["place_name"], units=p["units"],
                     footprint_acres=round(p["footprint_area_m2"] / 4046.86, 2),
                     internal_network_miles=miles(p["internal_network_m"]),
                     internal_network_m=p["internal_network_m"],
                     internal_segment_count=len(p["internal_segment_ids"]),
                     units_beyond_cap=p["units_beyond_cap"],
                     share_beyond_cap=p["share_beyond_cap"],
                     disposition=disposition, hold_mode=hold_mode,
                     hold_action=hh.DISPOSITIONS[disposition],
                     reasons=reasons, flags=flags,
                     v1_status=v1_status, v1_trigger=v1_trigger,
                     changed_by_recalibration=(v1_status == "UNRESOLVED") != (hold_mode == "ALL"))
        if hold_mode == "ALL":
            unresolved_places.add(p["place_name"])
        complex_report.append(entry)

    links, unassociated, astats = hh.associate(household_records, eligible, unresolved_places)
    summary = hh.summarize(hstats, links)
    print(f"  associated={astats['associated']} unassociated={astats['unassociated']} "
          f"(held in unresolved complexes={astats.get('held_unresolved_complex', 0)})")

    # Cache per-segment counts. Distinct household keys only (DEDUP: repeated segments).
    per_segment = defaultdict(set)
    for l in links:
        per_segment[l["primary_segment_id"]].add(l["household_key"])
    for s in segments:
        s["estimated_household_count"] = len(per_segment.get(s["id"], ()))

    # ------------------------------------------------------------- validate
    print("validate")
    validation = run_validation(segments, links, household_records, eligible)

    # --------------------------------------------------------------- write
    print("write")
    write_outputs(outdir, segments, node_points, degrees, household_records, links,
                  unassociated, complex_report, conflicts, log, snap_log, dropped_dupes)

    report.update(
        totals=totals(segments),
        households=summary,
        household_stats=hstats,
        association_stats=astats,
        dedup_rules=hh.DEDUP_RULES,
        ownership_conflicts=dict(count=len(conflicts), rule="RD_MAINT primary",
                                 file="review/ownership-conflicts.json"),
        complexes=dict(
            profiled=len(complex_report),
            held_entirely=sum(1 for c in complex_report if c["hold_mode"] == "ALL"),
            held_partially=sum(1 for c in complex_report if c["hold_mode"] == "BEYOND_CAP_ONLY"),
            accepted=sum(1 for c in complex_report if c["hold_mode"] == "NONE"),
            units_held_entirely=sum(c["units"] for c in complex_report if c["hold_mode"] == "ALL"),
            rule_version="v2 (recalibrated against Terrace View / Hunters Ridge / The Mill)",
            changed_by_recalibration=sum(1 for c in complex_report if c["changed_by_recalibration"]),
            file="review/apartment-complexes.json"),
        review_queue=review_queue(segments),
        corrections=dict(name_fixes=len(log["name_fixes"]), value_fixes=len(log["value_fixes"]),
                         anomalies=len(log["anomalies"]), file="review/corrections.json"),
        validation=validation,
        blocked_sources=json.load(open(os.path.join(
            geo.SNAP_ROOT, f"manifest-{date}.json")))["blocked_sources"],
    )
    with open(os.path.join(outdir, "build-report.json"), "w") as f:
        json.dump(report, f, indent=2, default=str)

    print_summary(report)
    return 0 if validation["passed"] else 1


def recommend_for_complex(p):
    """One of the four dispositions the instruction asks for, with a reason."""
    if p["units"] >= 100:
        return dict(
            action="ADD_AUTHORITATIVE_PEDESTRIAN_NETWORK",
            detail=("Large complex with no internal walkable network in any town layer. "
                    "Frontage-street association would silently claim these units are "
                    "prayed for by someone who never enters the site. Source internal "
                    "walkways from an authoritative provider, or digitise them, before "
                    "counting these units."),
            interim="EXCLUDE_FROM_ESTIMATE")
    if p["footprint_area_m2"] > 20000:
        return dict(
            action="ASSOCIATE_WITH_FRONTAGE_STREETS",
            detail=("Moderate complex spanning more than the association cap. Assign "
                    "buildings to the frontage street they actually face, by hand, "
                    "rather than nearest-neighbour."),
            interim="EXCLUDE_FROM_ESTIMATE")
    return dict(
        action="TREAT_AS_UNRESOLVED",
        detail="Small footprint; likely resolvable by raising the cap after review.",
        interim="EXCLUDE_FROM_ESTIMATE")


def totals(segments):
    out = defaultdict(lambda: {"segments": 0, "miles": 0.0})
    for s in segments:
        for key in (s["role"], f"{s['role']}::{s['segment_type']}"):
            out[key]["segments"] += 1
            out[key]["miles"] += s["length_m"]
    result = {k: {"segments": v["segments"], "miles": miles(v["miles"])} for k, v in out.items()}
    result["ALL"] = {"segments": len(segments),
                     "miles": miles(sum(s["length_m"] for s in segments))}
    req = [s for s in segments if s["role"] == "REQUIRED"]
    result["ELIGIBLE_MILEAGE"] = miles(sum(s["length_m"] for s in req))
    return result


def review_queue(segments):
    q = defaultdict(int)
    for s in segments:
        if s["role_status"] in ("NEEDS_REVIEW", "PROVISIONAL"):
            q[s["role_status"]] += 1
            for r in s["review_reasons"][:1]:
                q[f"reason::{r[:70]}"] += 1
    return dict(q)


def run_validation(segments, links, household_records, eligible):
    """Gates that fail the build loudly rather than letting it proceed quietly."""
    checks = []

    def check(name, ok, detail, fatal=True):
        checks.append(dict(name=name, passed=bool(ok), fatal=fatal, detail=detail))

    zero = [s["id"] for s in segments if s["length_m"] <= 0.05]
    check("no_zero_length_segments", not zero, f"{len(zero)} segments <= 5 cm")

    ids = [s["id"] for s in segments]
    check("segment_ids_unique", len(set(ids)) == len(ids),
          f"{len(ids)} ids, {len(set(ids))} distinct")

    keys = [h["key"] for h in household_records]
    check("household_keys_unique", len(set(keys)) == len(keys),
          f"{len(keys)} households, {len(set(keys))} distinct keys")

    primaries = [l["household_key"] for l in links]
    check("one_primary_segment_per_household", len(set(primaries)) == len(primaries),
          f"{len(primaries)} links, {len(set(primaries))} distinct households")

    # Connectivity: every REQUIRED segment must reach the main component.
    import networkx as nx
    G = nx.Graph()
    for s in segments:
        if s["role"] in ("REQUIRED", "OPTIONAL_CONNECTOR") and s["walkable"]:
            G.add_edge(s["start_node_id"], s["end_node_id"], id=s["id"])
    if G.number_of_nodes():
        comps = sorted(nx.connected_components(G), key=len, reverse=True)
        main = comps[0]
        isolated = [s["id"] for s in segments
                    if s["role"] == "REQUIRED" and s["start_node_id"] not in main]
        check("required_segments_connected", not isolated,
              f"{len(isolated)} REQUIRED segments off the main component "
              f"({len(comps)} components total)", fatal=False)
        stranded_components = len(comps) - 1
    else:
        check("required_segments_connected", False, "empty graph")
        stranded_components = 0

    # Housing units against the census benchmark — units, not occupied households.
    units = len(household_records)
    check("housing_units_plausible", 12000 <= units <= 24000,
          f"{units} estimated housing units (plausible band 12,000-24,000; "
          f"compared against housing units, not the ~13,800 occupied-household figure)",
          fatal=False)

    unassoc_rate = 1 - (len(links) / units) if units else 1
    check("association_rate", unassoc_rate <= 0.20,
          f"{unassoc_rate:.1%} of housing units unassociated", fatal=False)

    fatal_failures = [c for c in checks if not c["passed"] and c["fatal"]]
    return dict(passed=not fatal_failures, checks=checks,
                stranded_components=stranded_components)


def write_outputs(outdir, segments, node_points, degrees, household_records, links,
                  unassociated, complex_report, conflicts, log, snap_log, dropped_dupes):
    feats = []
    for s in segments:
        feats.append({
            "type": "Feature",
            "geometry": geo.to_wgs84_geojson(s["geometry"]),
            "properties": {k: v for k, v in s.items()
                           if k not in ("geometry", "_geom")},
        })
    with open(os.path.join(outdir, "segments.geojson"), "w") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f, default=str)

    with open(os.path.join(outdir, "nodes.geojson"), "w") as f:
        json.dump({"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": geo.to_wgs84_geojson(p),
             "properties": {"node_id": i, "degree": degrees[i]}}
            for i, p in enumerate(node_points)]}, f)

    link_by_key = {l["household_key"]: l for l in links}
    with open(os.path.join(outdir, "households.json"), "w") as f:
        json.dump({"households": [
            {k: v for k, v in dict(h, link=link_by_key.get(h["key"])).items() if k != "point"}
            for h in household_records]}, f, default=str)

    R = os.path.join(outdir, "review")
    dump = lambda name, obj: json.dump(obj, open(os.path.join(R, name), "w"),
                                       indent=2, default=str)
    dump("ownership-conflicts.json", conflicts)
    dump("apartment-complexes.json", complex_report)
    dump("unassociated-households.json",
         [{k: v for k, v in u.items() if k != "point"} for u in unassociated])
    dump("corrections.json", log)
    dump("node-snaps.json", snap_log)
    dump("duplicate-geometry.json", dropped_dupes)
    dump("segments-needing-review.json",
         [{"id": s["id"], "name": s["display_name"], "role": s["role"],
           "role_status": s["role_status"], "segment_type": s["segment_type"],
           "access_type": s["access_type"], "miles": miles(s["length_m"]),
           "reasons": s["review_reasons"], "source": s["source"]}
          for s in segments if s["role_status"] in ("NEEDS_REVIEW", "PROVISIONAL")])


def print_summary(report):
    t = report["totals"]
    print("\n" + "=" * 66)
    print("CANONICAL NETWORK BUILD")
    print("=" * 66)
    for key in sorted(k for k in t if "::" in k or k in ("REQUIRED", "OPTIONAL_CONNECTOR", "EXCLUDED")):
        v = t[key]
        print(f"  {key:<44} {v['segments']:>6} segs {v['miles']:>9.2f} mi")
    print(f"  {'ALL':<44} {t['ALL']['segments']:>6} segs {t['ALL']['miles']:>9.2f} mi")
    print(f"\n  Eligible (REQUIRED) mileage: {t['ELIGIBLE_MILEAGE']:.2f} mi")
    h = report["households"]
    print(f"\n  residential address points          {h['residential_address_points']:>7}")
    print(f"  estimated housing units             {h['estimated_housing_units']:>7}")
    print(f"  units on REQUIRED coverage          {h['units_associated_to_required_coverage']:>7}"
          f"   <- public: {h['public_label']!r}")
    print(f"  units on connector only             {h['units_associated_to_connector_only']:>7}")
    print(f"  units held for review               {h['units_held_for_review']:>7}")
    print(f"\n  ownership conflicts: {report['ownership_conflicts']['count']}")
    c = report['complexes']
    print(f"  complexes: {c['accepted']} accepted / {c['held_partially']} partial-hold / "
          f"{c['held_entirely']} full-hold  (of {c['profiled']}; "
          f"{c['changed_by_recalibration']} changed by recalibration)")
    print(f"  segments needing review: {report['review_queue'].get('NEEDS_REVIEW', 0)}"
          f" + {report['review_queue'].get('PROVISIONAL', 0)} provisional")
    print("\n  validation:")
    for c in report["validation"]["checks"]:
        mark = "PASS" if c["passed"] else ("FAIL" if c["fatal"] else "WARN")
        print(f"    [{mark}] {c['name']}: {c['detail']}")
    print("=" * 66)


if __name__ == "__main__":
    raise SystemExit(main())
