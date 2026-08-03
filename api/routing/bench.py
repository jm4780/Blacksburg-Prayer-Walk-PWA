"""Benchmark harness and stress tests for the routing engine.

Steps 7-9 of Phase 2b. Repeatable: same seed, same network, same numbers.

  python3 -m api.routing.bench            # everything
  python3 -m api.routing.bench --quick    # locations only
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from datetime import datetime, timezone

from . import network
from .engine import VARIANTS, Engine, EngineConfig
from .state import CompletionState

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "api", "routing", "results")

# Representative starts. Coordinates are approximate street locations; the engine
# snaps each to the nearest node on the main routing component.
LOCATIONS = [
    ("Downtown Blacksburg", -80.4139, 37.2296),
    ("Virginia Tech campus", -80.4225, 37.2284),
    ("Hethwood", -80.4460, 37.2380),
    ("North Main", -80.4110, 37.2450),
    # Corrected 2026-08-03. The previous South Main coordinate (-80.4180, 37.2130)
    # was ~1.5 km west of South Main Street and snapped into the Corporate Research
    # Center, which is why every South Main route reported zero households — there are
    # genuinely none within 250 m of where it landed. This point is on the residential
    # stretch of S Main St, with 305 dwelling units within 300 m.
    ("South Main", -80.4059, 37.2220),
    ("Near town boundary (NW)", -80.4530, 37.2560),
    # Its own routing component (VALID_INDEPENDENT_ROUTING_AREA), reachable only by
    # crossings we decline to route over. Added per Phase 2b.1 item 4.
    ("Corporate Research Center", -80.4069, 37.2010),
]

WALK_MPH = 3.0


def minutes(miles: float) -> int:
    return int(round(miles / WALK_MPH * 60))


def row_for(name, variant, route, score, net, ms, state):
    total_incomplete = state.incomplete_miles()
    return dict(
        location=name,
        variant=variant["name"],
        target_miles=variant["target_miles"],
        distance_miles=round(route.miles(net), 2),
        estimated_minutes=minutes(route.miles(net)),
        new_required_miles=round(score.new_required_miles, 2),
        repeated_miles=round(score.repeated_miles, 2),
        households=score.households,
        corridor_completions=score.corridor_completions,
        dead_end_completions=score.dead_end_completions,
        connector_miles=round(score.connector_miles, 2),
        walk_quality=score.walk_quality,
        loop_shape=round(score.loop_shape, 3),
        cohesion=round(score.cohesion, 3),
        turns=score.turns,
        uturns=score.uturns,
        score=score.total,
        pct_of_remaining_gained=round(
            100 * score.new_required_miles / total_incomplete, 3) if total_incomplete else 0.0,
        nested=variant.get("nested", True),
        grew=variant.get("grew", True),
        compute_ms=ms,
    )


def bench_locations(eng, net, state, label):
    rows = []
    for name, lon, lat in LOCATIONS:
        start = eng.snap(lon, lat)
        t0 = time.perf_counter()
        vs = eng.variants(start, state)
        ms = round((time.perf_counter() - t0) * 1000, 1)
        for v in vs:
            if v.get("route") is None:
                # Unavailable bands still belong in the table — "no one-mile route
                # exists from here any more" is a result, not a gap.
                rows.append(dict(location=name, variant=v["name"],
                                 target_miles=v["target_miles"], context=label,
                                 distance_miles=None,
                                 note=v.get("unavailable", "no route"),
                                 nearest_incomplete_miles=v.get("nearest_incomplete_miles"),
                                 compute_ms=ms))
                continue
            r = row_for(name, v, v["route"], v["score"], net, ms, state)
            r["context"] = label
            rows.append(r)
    return rows


def stress(eng, net):
    """Route quality across the project lifecycle."""
    scenarios = [("0%", lambda: CompletionState(net)),
                 ("25%", lambda: CompletionState.at_fraction(net, 0.25, seed=1)),
                 ("50%", lambda: CompletionState.at_fraction(net, 0.50, seed=1)),
                 ("75%", lambda: CompletionState.at_fraction(net, 0.75, seed=1)),
                 ("90%", lambda: CompletionState.at_fraction(net, 0.90, seed=1)),
                 ("98%", lambda: CompletionState.at_fraction(net, 0.98, seed=1)),
                 ("98% scattered", lambda: CompletionState.at_fraction(
                     net, 0.98, seed=1, mode="random")),
                 ("dead ends only", lambda: CompletionState.only_dead_ends_left(net))]

    rows = []
    for label, make in scenarios:
        st = make()
        remaining = st.incomplete_miles()
        for name, lon, lat in LOCATIONS[:4]:
            start = eng.snap(lon, lat)
            t0 = time.perf_counter()
            r, meta = eng.best_route(start, 3.5, st)
            ms = round((time.perf_counter() - t0) * 1000, 1)
            if r is None:
                rows.append(dict(completion=label, location=name,
                                 remaining_miles=round(remaining, 2),
                                 distance_miles=None, new_required_miles=0.0,
                                 note="no route found", compute_ms=ms,
                                 clusters=meta.get("clusters_found", 0)))
                continue
            s = r.score
            rows.append(dict(
                completion=label, location=name,
                remaining_miles=round(remaining, 2),
                distance_miles=round(r.miles(net), 2),
                estimated_minutes=minutes(r.miles(net)),
                new_required_miles=round(s.new_required_miles, 2),
                repeated_miles=round(s.repeated_miles, 2),
                efficiency=round(s.new_required_miles / max(r.miles(net), 0.01), 3),
                households=s.households,
                dead_end_completions=s.dead_end_completions,
                walk_quality=s.walk_quality,
                score=s.total,
                clusters=meta.get("clusters_found", 0),
                compute_ms=ms))
    return rows


def completion_context_bench(eng, net):
    """Steps 7's 'mostly completed' and 'mostly incomplete' contexts."""
    out = []
    out += bench_locations(eng, net, CompletionState(net), "mostly incomplete (0% done)")
    out += bench_locations(eng, net, CompletionState.at_fraction(net, 0.85, seed=3),
                           "mostly completed (85% done)")
    return out


def summarize(rows, key, fields):
    groups = {}
    for r in rows:
        if r.get("distance_miles") is None:
            continue
        groups.setdefault(r[key], []).append(r)
    out = []
    for k, rs in groups.items():
        entry = {key: k, "n": len(rs)}
        for f in fields:
            vals = [r[f] for r in rs if isinstance(r.get(f), (int, float))]
            if vals:
                entry[f"{f}_mean"] = round(statistics.mean(vals), 2)
        out.append(entry)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--date", default="2026-08-03")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    net = network.load(args.date)
    t0 = time.perf_counter()
    eng = Engine(net, EngineConfig())
    build_ms = round((time.perf_counter() - t0) * 1000, 1)
    print(f"engine ready in {build_ms} ms | {len(eng.components)} components, "
          f"main = {len(eng.main_component)} nodes")

    result = dict(
        generated_at=datetime.now(timezone.utc).isoformat(),
        network=network.freeze_manifest(net),
        engine_config=vars(EngineConfig()),
        walk_speed_mph=WALK_MPH,
        engine_build_ms=build_ms,
    )

    print("\n=== Step 7: benchmark by location and completion context ===")
    rows = completion_context_bench(eng, net)
    result["benchmark"] = rows
    hdr = f"{'location':<24}{'variant':<10}{'mi':>6}{'min':>5}{'new':>6}{'rep':>6}{'hh':>6}{'q':>6}{'score':>8}{'ms':>7}"
    for ctx in ("mostly incomplete (0% done)", "mostly completed (85% done)"):
        print(f"\n-- {ctx} --\n{hdr}")
        for r in rows:
            if r.get("context") != ctx:
                continue
            if r.get("distance_miles") is None:
                print(f"{r['location'][:23]:<24}{r['variant']:<10}   --  unavailable: "
                      f"{str(r.get('note'))[:52]} (nearest work "
                      f"{r.get('nearest_incomplete_miles')} mi)")
                continue
            print(f"{r['location'][:23]:<24}{r['variant']:<10}{r['distance_miles']:>6.2f}"
                  f"{r['estimated_minutes']:>5}{r['new_required_miles']:>6.2f}"
                  f"{r['repeated_miles']:>6.2f}{r['households']:>6}{r['walk_quality']:>6.1f}"
                  f"{r['score']:>8.0f}{r['compute_ms']:>7.0f}")

    if not args.quick:
        print("\n=== Step 8: stress across completion states (Medium, 3.5 mi) ===")
        srows = stress(eng, net)
        result["stress"] = srows
        print(f"{'completion':<16}{'location':<24}{'remain':>8}{'mi':>6}{'new':>6}"
              f"{'eff':>6}{'hh':>6}{'de':>4}{'q':>6}{'ms':>7}")
        for r in srows:
            if r.get("distance_miles") is None:
                print(f"{r['completion']:<16}{r['location'][:23]:<24}"
                      f"{r['remaining_miles']:>8.2f}   -- {r.get('note','')}")
                continue
            print(f"{r['completion']:<16}{r['location'][:23]:<24}{r['remaining_miles']:>8.2f}"
                  f"{r['distance_miles']:>6.2f}{r['new_required_miles']:>6.2f}"
                  f"{r['efficiency']:>6.2f}{r['households']:>6}{r['dead_end_completions']:>4}"
                  f"{r['walk_quality']:>6.1f}{r['compute_ms']:>7.0f}")

        result["stress_summary"] = summarize(
            srows, "completion",
            ["distance_miles", "new_required_miles", "efficiency", "walk_quality",
             "repeated_miles", "compute_ms"])

    result["performance"] = perf_summary(rows, result.get("stress", []))
    print("\n=== performance ===")
    for k, v in result["performance"].items():
        print(f"  {k:<34}{v}")

    path = os.path.join(OUT, "benchmark.json")
    with open(path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\n-> {path}")


def perf_summary(rows, srows):
    ms = [r["compute_ms"] for r in rows if isinstance(r.get("compute_ms"), (int, float))]
    sms = [r["compute_ms"] for r in srows if isinstance(r.get("compute_ms"), (int, float))]
    ms = sorted(set(ms))
    out = {}
    if ms:
        out["five_variants_ms_median"] = round(statistics.median(ms), 1)
        out["five_variants_ms_max"] = round(max(ms), 1)
    if sms:
        sms_sorted = sorted(sms)
        out["single_route_ms_median"] = round(statistics.median(sms_sorted), 1)
        out["single_route_ms_p90"] = round(sms_sorted[int(0.9 * (len(sms_sorted) - 1))], 1)
        out["single_route_ms_max"] = round(max(sms_sorted), 1)
    return out


if __name__ == "__main__":
    main()
