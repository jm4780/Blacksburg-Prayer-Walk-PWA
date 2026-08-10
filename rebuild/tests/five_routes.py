"""The final check: five routes, five different starting points, on the real map.

This is not a unit test. It renders five generated walks against real Blacksburg
geometry so a person can answer one question about each:

    would someone following this get lost, get confused, or end up somewhere unsafe?

One yes means fix it and run all five again.

    python3 rebuild/tests/five_routes.py
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from rebuild.engine import route as R  # noqa: E402
from rebuild.tests.render_route import OUTDIR, load_network, render  # noqa: E402

# Five genuinely different places to start, chosen to exercise different street
# fabrics rather than five points in the same neighbourhood.
STARTS = [
    ("downtown grid", (-80.4139, 37.2296), 30),
    ("campus edge", (-80.4230, 37.2250), 45),
    ("north residential", (-80.4200, 37.2450), 30),
    ("south residential", (-80.4050, 37.2130), 45),
    ("west edge", (-80.4550, 37.2350), 60),
]


def main():
    net_fc = json.load(open(os.path.join(os.path.dirname(__file__), "..", "data", "out", "network.geojson")))
    network = net_fc["features"]
    rendered = load_network()

    rows = []
    for name, start, minutes in STARTS:
        target = R.meters_for_minutes(minutes)
        t0 = time.time()
        rt = R.generate(start, target, network, covered=set(), seed=7)
        dt = time.time() - t0

        seg_ids = rt["seg_ids"]
        stats = R.route_stats(rt, network, start_lonlat=start)
        ratio = rt["length_m"] / target if target else 0.0
        path = os.path.join(OUTDIR, f"{name.replace(' ', '-')}.png")
        render(
            seg_ids,
            f"{name} · {minutes} min · {rt['length_m']/1609.34:.2f} mi · "
            f"{100*rt['new_m']/max(rt['length_m'],1):.0f}% new",
            path,
            network=rendered,
        )
        rows.append(
            dict(
                name=name,
                minutes=minutes,
                miles=rt["length_m"] / 1609.34,
                ratio=ratio,
                new_pct=100 * rt["new_m"] / max(rt["length_m"], 1),
                closure_m=stats.get("closure_m"),
                contiguity=stats.get("contiguity"),
                streets=len({rendered[s]["properties"]["name"] for s in seg_ids if s in rendered}),
                segs=len(seg_ids),
                secs=dt,
                path=path,
            )
        )

    print(f"{'start':20s} {'min':>4s} {'miles':>6s} {'x tgt':>6s} {'new%':>5s} "
          f"{'close':>6s} {'contig':>6s} {'streets':>7s} {'sec':>5s}")
    for r in rows:
        print(f"{r['name']:20s} {r['minutes']:4d} {r['miles']:6.2f} {r['ratio']:6.2f} "
              f"{r['new_pct']:5.0f} {r['closure_m']:6.1f} {r['contiguity']:6.3f} "
              f"{r['streets']:7d} {r['secs']:5.2f}")
    print()
    for r in rows:
        print("  ", r["path"])


if __name__ == "__main__":
    main()
