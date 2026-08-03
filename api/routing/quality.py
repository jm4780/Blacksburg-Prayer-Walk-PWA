"""Step 9: route quality review.

Measures the things a walker notices — zigzagging, U-turns, awkward connectors,
neighbourhood readability — across a sample of routes, and turns them into concrete
scoring recommendations rather than impressions.

  python3 -m api.routing.quality
"""
from __future__ import annotations

import json
import os
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone

from . import network
from .bench import LOCATIONS
from .engine import Engine
from .state import CompletionState

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def street_runs(route, net):
    """Consecutive segments sharing a street name — how the route reads as directions.

    A route of 40 segments across 6 named streets reads as "six turns". The same 40
    segments across 25 names reads as a maze, whatever its geometry looks like.
    """
    names = [net.segments[i].normalized_name or "(unnamed)" for i in route.seg_seq]
    runs, prev = 0, None
    for n in names:
        if n != prev:
            runs += 1
            prev = n
    return runs, len(set(names))


def analyse(route, net, state):
    turns, uturns = route.turn_stats(net)
    runs, distinct_names = street_runs(route, net)
    miles = route.miles(net)
    derived = sum(1 for i in route.distinct() if net.segments[i].is_derived)
    connector_runs = 0
    prev_conn = False
    for i in route.seg_seq:
        conn = net.segments[i].role != "REQUIRED"
        if conn and not prev_conn:
            connector_runs += 1
        prev_conn = conn
    campus = sum(1 for i in route.distinct() if net.segments[i].campus_obligation)
    campus_alt = sum(1 for i in route.distinct()
                     if net.segments[i].campus_obligation == "ALTERNATIVE")
    dead = sum(1 for i in route.distinct()
               if net.segments[i].is_dead_end and net.segments[i].required)
    return dict(
        miles=round(miles, 2),
        segments=len(route.seg_seq),
        turns=turns, turns_per_mile=round(turns / max(miles, .01), 1),
        uturns=uturns, uturns_per_mile=round(uturns / max(miles, .01), 2),
        street_runs=runs, distinct_streets=distinct_names,
        runs_per_street=round(runs / max(distinct_names, 1), 2),
        connector_runs=connector_runs,
        derived_connectors=derived,
        campus_segments=campus, campus_alternative_segments=campus_alt,
        dead_end_segments=dead,
        loop_shape=round(route.loop_shape(net), 3),
        cohesion=round(route.cohesion(net), 3),
        repeated_share=round(
            (len(route.seg_seq) - len(route.distinct())) / max(len(route.seg_seq), 1), 3),
        walk_quality=route.score.walk_quality if route.score else None,
    )


def main(date="2026-08-03"):
    net = network.load(date)
    eng = Engine(net)
    fresh = CompletionState(net)
    late = CompletionState.at_fraction(net, 0.85, seed=3)

    rows = []
    for label, st in (("fresh", fresh), ("85% complete", late)):
        for nm, lon, lat in LOCATIONS:
            start = eng.snap(lon, lat)
            for target in (1.0, 3.5, 7.5):
                r, meta = eng.best_route(start, target, st)
                if r is None:
                    continue
                a = analyse(r, net, st)
                a.update(location=nm, context=label, target=target)
                rows.append(a)

    # Campus-specific behaviour.
    campus_start = eng.snap(-80.4225, 37.2284)
    campus_rows = []
    for target in (1.0, 2.0, 3.5, 5.0):
        r, _ = eng.best_route(campus_start, target, fresh)
        if r is None:
            continue
        a = analyse(r, net, fresh)
        a.update(target=target)
        campus_rows.append(a)

    def agg(field):
        vals = [r[field] for r in rows if isinstance(r.get(field), (int, float))]
        return dict(mean=round(statistics.mean(vals), 2),
                    median=round(statistics.median(vals), 2),
                    p90=round(sorted(vals)[int(.9 * (len(vals) - 1))], 2),
                    max=round(max(vals), 2)) if vals else {}

    summary = {f: agg(f) for f in
               ("turns_per_mile", "uturns_per_mile", "runs_per_street", "loop_shape",
                "cohesion", "repeated_share", "connector_runs", "derived_connectors",
                "street_runs", "walk_quality")}

    findings = derive_findings(summary, rows, campus_rows)

    result = dict(generated_at=datetime.now(timezone.utc).isoformat(),
                  network_id=net.network_id, routes_analysed=len(rows),
                  summary=summary, findings=findings,
                  routes=rows, campus=campus_rows)
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "quality-review.json")
    with open(path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    print(f"analysed {len(rows)} routes\n")
    print(f"{'metric':<22}{'mean':>8}{'median':>9}{'p90':>8}{'max':>8}")
    for k, v in summary.items():
        if v:
            print(f"{k:<22}{v['mean']:>8}{v['median']:>9}{v['p90']:>8}{v['max']:>8}")
    print("\nfindings:")
    for f in findings:
        print(f"  [{f['severity']}] {f['issue']}")
        print(f"      {f['evidence']}")
        print(f"      -> {f['recommendation']}")
    print(f"\n-> {path}")


def derive_findings(summary, rows, campus_rows):
    out = []

    uturn = summary["uturns_per_mile"]
    if uturn and uturn["p90"] > 1.0:
        out.append(dict(
            severity="MEDIUM", issue="U-turns at non-dead-end nodes",
            evidence=f"p90 {uturn['p90']} per mile, max {uturn['max']}",
            recommendation="Raise Weights.uturn from -6 to about -15. A reversal at a "
                           "through-node is the single most obvious defect to a walker "
                           "and is currently cheaper than half a tenth of a mile."))

    turns = summary["turns_per_mile"]
    if turns and turns["p90"] > 14:
        out.append(dict(
            severity="MEDIUM", issue="Zigzagging",
            evidence=f"p90 {turns['p90']} sharp turns per mile",
            recommendation="Raise Weights.turn from -0.7 to about -1.5, or add a "
                           "same-street-continuation bonus so the router prefers to "
                           "finish a street before turning off it."))

    runs = summary["runs_per_street"]
    if runs and runs["mean"] > 1.6:
        out.append(dict(
            severity="LOW", issue="Streets entered more than once",
            evidence=f"mean {runs['mean']} runs per distinct street name",
            recommendation="Add a small bonus for covering a street in one continuous "
                           "run. Improves how the route reads as turn-by-turn directions "
                           "without changing what it covers."))

    rep = summary["repeated_share"]
    if rep and rep["p90"] > 0.30:
        out.append(dict(
            severity="MEDIUM", issue="Repeat traversal on longer routes",
            evidence=f"p90 {rep['p90']} of traversed segments are repeats",
            recommendation="The repeat penalty (-45/mi) is being outbid by new coverage "
                           "(+100/mi). For Long and Extended, scale repeat_mile with "
                           "route length so a 7-mile route tolerates less doubling back "
                           "proportionally than a 1-mile one."))

    coh = summary["cohesion"]
    if coh and coh["median"] < 0.7:
        out.append(dict(
            severity="LOW", issue="Neighbourhood readability",
            evidence=f"median cohesion {coh['median']}",
            recommendation="Cohesion is measured from a bounding box, which punishes "
                           "legitimately linear neighbourhoods. Consider replacing with "
                           "convex-hull area or a street-name-entropy measure before "
                           "raising its weight."))

    der = summary["derived_connectors"]
    if der and der["max"] > 0:
        out.append(dict(
            severity="LOW", issue="Synthetic connectors appear in routes",
            evidence=f"max {der['max']} per route, mean {der['mean']}",
            recommendation="Only HIGH_CONFIDENCE connectors are routable, so this is "
                           "within policy, but routes should surface them in turn-by-turn "
                           "text ('cross here') so a walker is not surprised by a link "
                           "no source asserted."))

    if campus_rows:
        alt = sum(r["campus_alternative_segments"] for r in campus_rows)
        out.append(dict(
            severity="INFO" if alt == 0 else "MEDIUM",
            issue="Campus routing behaviour",
            evidence=f"{sum(r['campus_segments'] for r in campus_rows)} campus segments "
                     f"across {len(campus_rows)} campus routes, of which {alt} are "
                     f"ALTERNATIVE (duplicate-obligation) walkways",
            recommendation=("Campus normalization is holding — routes use canonical "
                            "corridors." if alt == 0 else
                            "Routes are using ALTERNATIVE walkways where the canonical "
                            "side would do. Add a small penalty on ALTERNATIVE segments "
                            "so the canonical corridor is preferred when both are "
                            "available.")))
    return out


if __name__ == "__main__":
    main()
