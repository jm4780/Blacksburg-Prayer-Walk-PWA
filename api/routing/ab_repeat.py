"""Controlled A/B for the length-scaled repeat penalty.

Comparing the Phase 2b benchmark to the Phase 2b.1 benchmark directly would be
dishonest: the location set changed (South Main was moved off a bad coordinate, the
Corporate Research Center was added) and the network changed (Smart Road excluded). So
the numbers would mix three effects.

This runs the *same* code over the *same* locations and bands twice, changing only the
weights: the old flat repeat penalty against the new categorised, length-scaled one.
That isolates the change the instruction asked to measure.

  python3 -m api.routing.ab_repeat
"""
from __future__ import annotations

import json
import os
import statistics
import time
from datetime import datetime, timezone

from . import network
from .bench import LOCATIONS, WALK_MPH, minutes
from .engine import VARIANTS, Engine
from .score import DEFAULT_WEIGHTS, Weights
from .state import CompletionState

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

# The Phase 2b behaviour: one flat rate for every kind of repeat, no share term, no
# multiplicity term, no band scaling.
OLD_WEIGHTS = Weights(
    repeat_avoidable_mile=-45.0,
    repeat_closing_mile=-45.0,
    repeat_dead_end_mile=-45.0,
    repeat_share_quadratic=0.0,
    repeat_extra_traversal=0.0,
    repeat_band_exponent=0.0,
)
NEW_WEIGHTS = DEFAULT_WEIGHTS


def run(net, weights, states):
    eng = Engine(net, weights=weights)
    rows = []
    for label, st in states:
        for nm, lon, lat in LOCATIONS:
            start = eng.snap(lon, lat)
            t0 = time.perf_counter()
            vs = eng.variants(start, st)
            ms = round((time.perf_counter() - t0) * 1000, 1)
            for v in vs:
                r = v.get("route")
                if r is None:
                    rows.append(dict(context=label, location=nm, variant=v["name"],
                                     available=False, compute_ms=ms))
                    continue
                s = r.score
                tr = r.traversals(net)
                rows.append(dict(
                    context=label, location=nm, variant=v["name"], available=True,
                    distance_miles=round(r.miles(net), 3),
                    estimated_minutes=minutes(r.miles(net)),
                    new_required_miles=round(s.new_required_miles, 3),
                    repeated_miles=round(s.repeated_miles, 3),
                    repeat_share=round(tr["repeat_share"], 4),
                    avoidable_repeat_miles=round(tr["avoidable_miles"], 3),
                    avoidable_repeat_share=round(
                        tr["avoidable_miles"] / max(r.miles(net), .01), 4),
                    closing_leg_miles=round(tr["closing_leg_miles"], 3),
                    dead_end_return_miles=round(tr["dead_end_return_miles"], 3),
                    extra_traversals=tr["extra_traversals"],
                    households=s.households,
                    uturns=s.uturns, turns=s.turns,
                    walk_quality=s.walk_quality, score=s.total,
                    compute_ms=ms))
    return rows


def mean(rows, field):
    v = [r[field] for r in rows if isinstance(r.get(field), (int, float))]
    return round(statistics.mean(v), 3) if v else None


def compare(a, b):
    """a = old, b = new. Matched on (context, location, variant)."""
    key = lambda r: (r["context"], r["location"], r["variant"])
    bm = {key(r): r for r in b}
    pairs = [(r, bm[key(r)]) for r in a if key(r) in bm]
    both = [(x, y) for x, y in pairs if x.get("available") and y.get("available")]
    fields = ["new_required_miles", "repeated_miles", "repeat_share",
              "avoidable_repeat_miles", "avoidable_repeat_share",
              "dead_end_return_miles", "extra_traversals", "distance_miles",
              "households", "score", "walk_quality", "uturns", "turns", "compute_ms"]
    out = {}
    for f in fields:
        ov = [x[f] for x, y in both if isinstance(x.get(f), (int, float))]
        nv = [y[f] for x, y in both if isinstance(y.get(f), (int, float))]
        if not ov or not nv:
            continue
        o, n = statistics.mean(ov), statistics.mean(nv)
        out[f] = dict(before=round(o, 3), after=round(n, 3),
                      delta=round(n - o, 3),
                      pct=round(100 * (n - o) / o, 1) if abs(o) > 1e-9 else None)
    out["_matched_routes"] = len(both)
    out["availability"] = dict(
        before=sum(1 for r in a if r.get("available")),
        after=sum(1 for r in b if r.get("available")),
        total_bands=len(a))
    return out


def main(date="2026-08-03"):
    net = network.load(date)
    states = [("fresh", CompletionState(net)),
              ("50% complete", CompletionState.at_fraction(net, 0.50, seed=1)),
              ("85% complete", CompletionState.at_fraction(net, 0.85, seed=3))]

    print("running OLD weights (flat repeat penalty)...")
    old = run(net, OLD_WEIGHTS, states)
    print("running NEW weights (categorised, length-scaled)...")
    new = run(net, NEW_WEIGHTS, states)

    cmp = compare(old, new)
    result = dict(generated_at=datetime.now(timezone.utc).isoformat(),
                  network_id=net.network_id,
                  method=("same code, same network, same locations and bands; only the "
                          "repeat-penalty weights differ"),
                  old_weights={k: v for k, v in vars(OLD_WEIGHTS).items()
                               if "repeat" in k},
                  new_weights={k: v for k, v in vars(NEW_WEIGHTS).items()
                               if "repeat" in k},
                  comparison=cmp, old_rows=old, new_rows=new)
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "ab-repeat-penalty.json")
    with open(path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    print(f"\nmatched routes: {cmp['_matched_routes']}   "
          f"bands available: {cmp['availability']['before']} -> "
          f"{cmp['availability']['after']} of {cmp['availability']['total_bands']}")
    print(f"\n{'metric':<28}{'before':>10}{'after':>10}{'delta':>10}{'pct':>9}")
    order = ["new_required_miles", "repeated_miles", "repeat_share",
             "avoidable_repeat_miles", "avoidable_repeat_share",
             "dead_end_return_miles", "extra_traversals", "distance_miles",
             "households", "score", "walk_quality", "uturns", "turns", "compute_ms"]
    for f in order:
        v = cmp.get(f)
        if not v:
            continue
        pct = f"{v['pct']:+.1f}%" if v["pct"] is not None else "—"
        print(f"{f:<28}{v['before']:>10.3f}{v['after']:>10.3f}{v['delta']:>+10.3f}{pct:>9}")
    print(f"\n-> {path}")
    return cmp


if __name__ == "__main__":
    main()
