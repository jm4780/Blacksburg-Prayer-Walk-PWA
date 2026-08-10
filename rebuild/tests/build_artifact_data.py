"""Bake the network and a spread of real routes into one JSON for the artifact page.

An artifact is a single self-contained page: no server, no Python, no database.
The route engine cannot run there. Rather than reimplement a worse one in
JavaScript and reintroduce the walk-to-nowhere failures that took two rounds to
fix, this precomputes real routes with the real engine from starts spread across
the town, and the page picks the nearest one.

    python3 rebuild/tests/build_artifact_data.py
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from rebuild.engine import route as R  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
NETWORK = os.path.join(REPO, "rebuild", "data", "out", "network.geojson")
LIMITS = os.path.join(REPO, "pipeline", "basemap", "blacksburg-limits.json")
OUT = os.path.join(REPO, "rebuild", "data", "out", "artifact-data.json")

MINUTES = [20, 30, 45, 60]
GRID = 9  # GRID x GRID cells over the town; one start per occupied cell


def main() -> None:
    fc = json.load(open(NETWORK))
    feats = fc["features"]

    # Spread starts by putting at most one in each grid cell, so they cover the
    # town rather than clustering where segments happen to be short.
    lons = [c[0] for f in feats for c in f["geometry"]["coordinates"]]
    lats = [c[1] for f in feats for c in f["geometry"]["coordinates"]]
    w, e, s, n = min(lons), max(lons), min(lats), max(lats)
    cell: dict[tuple[int, int], tuple[float, float]] = {}
    for f in feats:
        c = f["geometry"]["coordinates"][len(f["geometry"]["coordinates"]) // 2]
        gx = min(GRID - 1, int((c[0] - w) / (e - w) * GRID))
        gy = min(GRID - 1, int((c[1] - s) / (n - s) * GRID))
        if (gx, gy) not in cell and f["properties"]["length_m"] > 60:
            cell[(gx, gy)] = (c[0], c[1])
    starts = list(cell.values())
    print(f"{len(starts)} start points over a {GRID}x{GRID} grid")

    routes: list[dict] = []
    t0 = time.time()
    for i, st in enumerate(starts):
        for m in MINUTES:
            try:
                r = R.generate(st, R.meters_for_minutes(m), feats, covered=set(), seed=7)
            except Exception as exc:
                print(f"  start {i} {m}min failed: {exc}")
                continue
            if not r.get("seg_ids"):
                continue
            routes.append(
                {
                    "s": [round(st[0], 5), round(st[1], 5)],
                    "m": m,
                    "ids": [int(x) for x in r["seg_ids"]],
                    "len": round(float(r["length_m"])),
                }
            )
        print(f"  {i+1}/{len(starts)} starts, {len(routes)} routes, {time.time()-t0:.0f}s",
              flush=True)

    segs = [
        [
            f["properties"]["seg_id"],
            f["properties"]["name"],
            [[round(c[0], 5), round(c[1], 5)] for c in f["geometry"]["coordinates"]],
            round(f["properties"]["length_m"]),
            f["properties"].get("carriageway"),
        ]
        for f in feats
    ]
    limits = [[round(c[0], 5), round(c[1], 5)]
              for c in json.load(open(LIMITS))["coordinates"][0]]

    data = {"segments": segs, "limits": limits, "routes": routes}
    with open(OUT, "w") as fh:
        json.dump(data, fh, separators=(",", ":"))
    kb = os.path.getsize(OUT) / 1024
    print(f"\nwrote {OUT}  ({kb:.0f} KB, {len(segs)} segments, {len(routes)} routes)")


if __name__ == "__main__":
    main()
