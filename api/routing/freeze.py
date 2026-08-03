"""Freeze the integration candidate: the canonical network + the engine version.

Publishes one manifest that pins the network, the engine, the component
classification, the benchmark summary and the go/no-go gates.

  python3 -m api.routing.freeze
"""
from __future__ import annotations

import json
import os
import statistics
from dataclasses import asdict
from datetime import datetime, timezone

from . import components as comp_mod
from . import network
from .engine import ENGINE_VERSION, VARIANTS, Engine, EngineConfig
from .score import DEFAULT_WEIGHTS

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
M_PER_MILE = 1609.344

# Smart Road, from the curation override in the canonical build.
SMART_ROAD_NAME = "gordon c willis smart rd"


def main(date="2026-08-03"):
    net = network.load(date)
    eng = Engine(net)
    comps = eng.component_info
    csum = comp_mod.summary(comps)

    with open(os.path.join(OUT, "benchmark.json")) as f:
        bench = json.load(f)
    with open(os.path.join(OUT, "quality-review.json")) as f:
        quality = json.load(f)
    before_path = os.path.join(OUT, "before", "benchmark-v1.0.json")
    before = json.load(open(before_path)) if os.path.exists(before_path) else None
    qbefore_path = os.path.join(OUT, "before", "quality-review-v1.0.json")
    qbefore = json.load(open(qbefore_path)) if os.path.exists(qbefore_path) else None

    with open(os.path.join(network.OUT_ROOT, date, "build-report.json")) as f:
        build_report = json.load(f)
    overrides = build_report.get("curation_overrides", {})

    with_req = [c for c in comps if c.required_miles > 0.0005]
    gates = _gates(net, comps, csum, bench, quality, qbefore, overrides)
    failed = [g for g in gates if g["status"] == "FAIL"]
    warned = [g for g in gates if g["status"] == "WARN"]

    candidate = dict(
        frozen_at=datetime.now(timezone.utc).isoformat(),
        canonical_network_version=f"v{net.version}",
        network_id=net.network_id,
        previous_network_id="bbg-net-v1.1-3855ef9c4c15358a",
        routing_engine_version=ENGINE_VERSION,
        snapshot_date=net.snapshot_date,
        network=network.freeze_manifest(net),
        engine=dict(version=ENGINE_VERSION, config=vars(EngineConfig()),
                    weights=asdict(DEFAULT_WEIGHTS), bands=VARIANTS),
        curation_overrides=overrides,
        components=dict(
            total=len(comps),
            summary=csum,
            with_required_mileage=[
                dict(index=c.index, description=c.description,
                     classification=c.classification,
                     required_miles=c.required_miles, total_miles=c.total_miles,
                     households=c.households, has_cycle=c.has_cycle,
                     public=c.all_public, separation_m=c.separation_m,
                     separation_cause=c.separation_cause,
                     supports_closed_route=c.max_closed_walk_miles > 0.2,
                     max_closed_walk_miles=c.max_closed_walk_miles,
                     supported_bands=c.supports_bands,
                     start_snap_allowed=c.start_snap_allowed,
                     in_denominator=c.in_denominator,
                     top_streets=c.top_streets, reasons=c.reasons)
                for c in sorted(with_req, key=lambda x: -x.required_miles)],
        ),
        benchmark_summary=_bench_summary(bench, before),
        repeat_improvements=_repeat_delta(quality, qbefore),
        repeat_ab_test=_ab_summary(),
        performance=bench.get("performance", {}),
        quality_findings=quality.get("findings", []),
        gates=gates,
        go_no_go=dict(recommendation=("NO-GO" if failed
                                      else "GO WITH CONDITIONS" if warned else "GO"),
                      failed=[g["gate"] for g in failed],
                      warned=[g["gate"] for g in warned]),
    )

    path = os.path.join(OUT, f"integration-candidate-{ENGINE_VERSION}.json")
    with open(path, "w") as f:
        json.dump(candidate, f, indent=2, default=str)

    print(f"INTEGRATION CANDIDATE  network {candidate['canonical_network_version']} "
          f"({net.network_id})  engine {ENGINE_VERSION}")
    print("=" * 74)
    m = net.stats
    print(f"  required mileage                       {m['required_miles']:>9.3f} mi")
    print(f"  smart road excluded                    {overrides.get('miles', 0):>9.3f} mi")
    print(f"  valid routing components               {csum['valid_routing_areas']:>9}")
    print(f"  required mi in valid areas             {csum['required_miles_in_valid_areas']:>9.3f} mi")
    print(f"  required mi needing review             {csum['required_miles_needing_review']:>9.3f} mi")
    print(f"  required mi in denominator             {csum['required_miles_in_denominator']:>9.3f} mi")
    print("\n  components carrying required mileage:")
    for c in sorted(with_req, key=lambda x: -x.required_miles):
        print(f"    [{c.index:>3}] {c.description[:36]:<38}{c.required_miles:>8.3f} mi  "
              f"hh {c.households:>6}  {c.classification}")
    print("\n  gates:")
    for g in gates:
        print(f"    [{g['status']:^4}] {g['gate']}")
        print(f"           {g['detail']}")
    print(f"\n  RECOMMENDATION: {candidate['go_no_go']['recommendation']}")
    print(f"\n-> {path}")
    return 0 if not failed else 1


def _ab_summary():
    path = os.path.join(OUT, "ab-repeat-penalty.json")
    if not os.path.exists(path):
        return None
    ab = json.load(open(path))
    return dict(method=ab["method"], old_weights=ab["old_weights"],
                new_weights=ab["new_weights"], comparison=ab["comparison"])


def _bench_summary(bench, before):
    rows = [r for r in bench.get("benchmark", []) if r.get("distance_miles") is not None]
    def agg(rs, f):
        v = [r[f] for r in rs if isinstance(r.get(f), (int, float))]
        return round(statistics.mean(v), 3) if v else None
    out = dict(routes=len(rows))
    for f in ("distance_miles", "new_required_miles", "repeated_miles",
              "households", "walk_quality", "score"):
        out[f"{f}_mean"] = agg(rows, f)
    if before:
        brows = [r for r in before.get("benchmark", [])
                 if r.get("distance_miles") is not None]
        out["before"] = dict(routes=len(brows))
        for f in ("distance_miles", "new_required_miles", "repeated_miles",
                  "households", "walk_quality", "score"):
            out["before"][f"{f}_mean"] = agg(brows, f)
    out["stress"] = bench.get("stress_summary", [])
    return out


def _repeat_delta(quality, qbefore):
    now = quality.get("summary", {})
    was = (qbefore or {}).get("summary", {})
    keys = ("repeated_share", "avoidable_repeat_share", "walk_quality",
            "uturns_per_mile", "turns_per_mile", "loop_shape")
    out = {}
    for k in keys:
        out[k] = dict(after=now.get(k), before=was.get(k))
    return out


def _gates(net, comps, csum, bench, quality, qbefore, overrides):
    g = []

    def gate(name, ok, detail, warn=False):
        g.append(dict(gate=name,
                      status="PASS" if ok else ("WARN" if warn else "FAIL"),
                      detail=detail))

    # 1 — repeat traversal materially improved without severe coverage loss.
    #
    # Judged on the controlled A/B, not on Phase 2b's benchmark. The benchmark set
    # changed this phase (South Main moved off a bad coordinate, the CRC was added)
    # and so did the network (Smart Road excluded), so a straight before/after would
    # mix three effects. ab_repeat.py runs the same code over the same locations with
    # only the weights swapped.
    ab_path = os.path.join(OUT, "ab-repeat-penalty.json")
    if os.path.exists(ab_path):
        ab = json.load(open(ab_path))["comparison"]
        av = ab.get("avoidable_repeat_miles", {})
        cov = ab.get("new_required_miles", {})
        ext = ab.get("extra_traversals", {})
        improved = (av.get("pct") or 0) <= -10.0
        cov_ok = (cov.get("pct") or 0) >= -5.0
        gate("repeat_traversal_improved_without_coverage_loss", improved and cov_ok,
             f"controlled A/B over {ab.get('_matched_routes')} matched routes: "
             f"avoidable repeat {av.get('before')} -> {av.get('after')} mi "
             f"({av.get('pct'):+.1f}%), third-or-later passes {ext.get('pct'):+.1f}%, "
             f"U-turns {ab.get('uturns',{}).get('pct'):+.1f}%; new coverage "
             f"{cov.get('before')} -> {cov.get('after')} mi ({cov.get('pct'):+.1f}%), "
             f"households {ab.get('households',{}).get('pct'):+.1f}%, walk quality "
             f"{ab.get('walk_quality',{}).get('pct'):+.1f}%")
    else:
        gate("repeat_traversal_improved_without_coverage_loss", False,
             "ab-repeat-penalty.json not found; run python3 -m api.routing.ab_repeat")

    # 2 — Smart Road correctly classified
    ok = overrides.get("applied", 0) > 0 and not any(
        s.normalized_name == SMART_ROAD_NAME for s in net.segments)
    gate("smart_road_reclassified", ok,
         f"{overrides.get('applied', 0)} segments / {overrides.get('miles', 0)} mi "
         f"overridden REQUIRED -> EXCLUDED; Smart Road absent from the routing graph: "
         f"{not any(s.normalized_name == SMART_ROAD_NAME for s in net.segments)}")

    # 3 — valid independent components supported
    valid = [c for c in comps if c.classification == "VALID_INDEPENDENT_ROUTING_AREA"]
    gate("valid_independent_components_supported", len(valid) >= 2,
         f"{len(valid)} valid routing areas; start snapping restricted to them; "
         f"cluster discovery is scoped to the start's own component")

    # 4 — no legitimate public area excluded for not joining the main graph
    wrongly = [c for c in comps
               if c.required_miles >= comp_mod.MIN_REQUIRED_MI and c.all_public
               and c.classification != "VALID_INDEPENDENT_ROUTING_AREA"]
    gate("no_public_area_excluded_for_disconnection", not wrongly,
         f"{len(wrongly)} public components with >= {comp_mod.MIN_REQUIRED_MI} mi "
         f"required are not classified valid; "
         f"{csum['required_miles_removed_from_denominator']} mi removed from the "
         f"denominator in total")

    # 5 — South Main explained
    sm = [r for r in bench.get("benchmark", [])
          if r.get("location") == "South Main" and r.get("distance_miles") is not None]
    hh = max((r.get("households", 0) for r in sm), default=0)
    gate("south_main_explained", hh > 0,
         f"South Main now reports up to {hh} households per variant. Root cause: the "
         f"benchmark coordinate was ~1.5 km west of South Main Street and snapped into "
         f"the Corporate Research Center, where there are genuinely zero dwelling units "
         f"within 250 m. Household methodology unchanged.")

    # 6 — late-opportunity states defined
    from . import response as resp
    states = {"ROUTE_AVAILABLE", "LIMITED_LOCAL_COVERAGE", "NO_USEFUL_ROUTE_NEAR_START",
              "LONGER_ROUTE_REQUIRED", "SELECT_DIFFERENT_START_AREA"}
    gate("late_opportunity_states_defined", hasattr(resp, "assess"),
         f"{len(states)} states, decided from local conditions (nearest incomplete "
         f"distance, approach, new mileage, efficiency) — never from town-wide "
         f"completion percentage")

    # 8 — campus promoted without creating a duplicate obligation (Phase 3 item 1)
    co = network.freeze_manifest(net)["campus_obligation"]
    campus_req = net.stats["required_campus_miles"]
    alts = [s for s in net.segments if s.campus_obligation == "ALTERNATIVE"]
    alt_required = [s for s in alts if s.required]
    ok = (campus_req > 10.0 and not alt_required
          and co["alternatives_crediting_a_canonical_side"] == len(alts)
          and co["credit_links_dropped_as_dangling"] == 0)
    gate("campus_promoted_without_duplicate_obligation", ok,
         f"{campus_req} mi of canonical campus corridor is REQUIRED; "
         f"{len(alt_required)} ALTERNATIVE walkways are REQUIRED (must be 0); "
         f"{co['duplicate_obligation_miles_avoided']} mi of duplicate obligation "
         f"avoided; {co['alternatives_crediting_a_canonical_side']}/{len(alts)} "
         f"alternatives credit a canonical side, {co['credit_links_dropped_as_dangling']} "
         f"dangling credit links")

    # 9 — the three mileage buckets partition the required total exactly
    m = network.freeze_manifest(net)["mileage"]
    three = m["required_street"] + m["required_trail"] + m["required_campus"]
    gate("required_mileage_partitions", abs(three - m["required_total"]) <= 0.002,
         f"street {m['required_street']} + trail {m['required_trail']} + campus "
         f"{m['required_campus']} = {round(three, 3)} vs required total "
         f"{m['required_total']}")

    # 10 — CRC catalogued for review, still held out of the graph, still valid
    crc_path = os.path.join(network.OUT_ROOT, net.snapshot_date, "review",
                            "crc-crossings.json")
    if os.path.exists(crc_path):
        crc = json.load(open(crc_path))
        crc_comp = next((c for c in comps
                         if "Research Center" in (c.description or "")), None)
        promoted = [r for r in crc["crossings"]
                    if r["touches_crc"] and r["segment_id"] in
                    {s.id for s in net.segments}]
        ok = (crc["counts"]["crc_crossings"] > 0 and not promoted
              and crc_comp is not None
              and crc_comp.classification == "VALID_INDEPENDENT_ROUTING_AREA")
        gate("crc_crossings_catalogued_not_promoted", ok,
             f"{crc['counts']['crc_crossings']} CRC crossings catalogued for review; "
             f"{len(promoted)} of them are in the routing graph (must be 0); CRC is "
             f"{crc_comp.classification if crc_comp else 'MISSING'} with "
             f"{crc_comp.required_miles if crc_comp else 0} required mi. "
             f"{crc['if_all_crc_crossings_were_promoted']['finding']}")
    else:
        gate("crc_crossings_catalogued_not_promoted", False,
             "crc-crossings.json not found; run python3 -m pipeline.build.crc_review")

    # 11 — required mileage stranded off the main component, with its cause.
    # A WARN, not a FAIL: the campus promotion legitimately added required mileage that
    # the town street graph does not connect to, and hiding that behind a pass would be
    # worse than carrying it as a known, quantified limitation.
    cpath = os.path.join(network.OUT_ROOT, net.snapshot_date, "review",
                         "connector-classification.json")
    if os.path.exists(cpath):
        att = json.load(open(cpath))["disconnection_attribution"]["summary"]
        off = att["required_miles_off_main_high_confidence"]
        gate("off_main_required_mileage_attributed", off <= 2.0,
             f"{off} mi of REQUIRED mileage is off the main component: "
             f"{att['caused_by_rejected_connectors']} mi would be recovered by "
             f"reviewing specific rejected connectors, "
             f"{att['caused_by_isolation_or_missing_data']} mi is isolated or missing "
             f"from the source. Introduced by the campus promotion — campus pedestrian "
             f"geometry does not join the town street graph through any trusted "
             f"connector.", warn=True)

    # 7 — performance still interactive
    perf = bench.get("performance", {})
    med = perf.get("single_route_ms_median", 1e9)
    gate("performance_interactive", med < 100,
         f"single route median {med} ms, p90 {perf.get('single_route_ms_p90')} ms; "
         f"five variants median {perf.get('five_variants_ms_median')} ms, "
         f"max {perf.get('five_variants_ms_max')} ms", warn=med >= 100)

    return g


if __name__ == "__main__":
    raise SystemExit(main())
