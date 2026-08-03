"""Phase 3.1 item 2: is the disconnected campus network independently useful?

Network v1.2 promoted 11.359 mi of campus corridor to REQUIRED, and 12.858 mi of
required mileage now sits outside the main routing component. That is either fine —
campus is a place you walk *within*, and a walker on the Drillfield does not need to
reach downtown mid-walk — or it is a defect that leaves people stranded on fragments.
This answers which, from the six starts the brief names, by measuring rather than
asserting.

Two questions get their own treatment because they are the ones that decide it:

  Does the route form a coherent loop?   Measured, not assumed: loop_shape, the share
                                         of the walk that is avoidable doubling back,
                                         and whether the walk returns to its start.

  Can the walker reach nearby campus AND non-campus coverage without an invented
  crossing?                              Answered by looking at what is actually
                                         reachable inside the start's own component,
                                         since the router never leaves it.

  python3 -m api.routing.campus_validate
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone

import numpy as np

from . import network
from .engine import VARIANTS, Engine
from .state import CompletionState

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
M_PER_MILE = 1609.344
WALK_MPH = 3.0

# The six starts the brief names, plus the two Phase 2b.1 controls so campus numbers
# can be read against a known-good baseline rather than in isolation.
LOCATIONS = [
    ("The Drillfield", -80.4225, 37.2284, "campus core"),
    ("Duck Pond", -80.4265, 37.2180, "campus south, near residential edge"),
    ("Lane Stadium", -80.4185, 37.2200, "campus southeast"),
    ("N Main St near Prices Fork Rd", -80.4177, 37.2318, "campus/town boundary, north"),
    ("Downtown, eastern campus edge", -80.4160, 37.2295, "campus/town boundary, east"),
    ("Just outside campus, Prices Fork entrance", -80.4290, 37.2295,
     "legitimate pedestrian entrance, outside the core"),
    # Controls.
    ("Downtown Blacksburg (control)", -80.4139, 37.2296, "main component baseline"),
    ("Corporate Research Center (control)", -80.4069, 37.2010,
     "known independent component"),
]


def haversine_m(lon1, lat1, lon2, lat2):
    R = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def node_lonlat(net, graph, node_i):
    """WGS84 of a graph node index, read off any segment that touches it."""
    node_id = graph.node_ids[node_i] if hasattr(graph, "node_ids") else None
    for s in net.segments:
        if not s.coords:
            continue
        if graph.node_index.get(s.u) == node_i:
            return s.coords[0]
        if graph.node_index.get(s.v) == node_i:
            return s.coords[-1]
    return None


def component_profile(net, eng, ci):
    """What is in this component, split campus vs not."""
    comp = next((c for c in eng.component_info if c.index == ci), None)
    if comp is None:
        return {}
    campus_m = other_m = 0.0
    hh = 0
    names: dict[str, float] = {}
    for i in comp.segment_indices:
        s = net.segments[i]
        if not s.required:
            continue
        if s.campus_obligation == "CANONICAL":
            campus_m += s.length_m
        else:
            other_m += s.length_m
        hh += s.households
        if s.display_name:
            names[s.display_name] = names.get(s.display_name, 0.0) + s.length_m
    return dict(
        index=ci, description=comp.description,
        classification=comp.classification,
        required_miles=round(comp.required_miles, 3),
        campus_required_miles=round(campus_m / M_PER_MILE, 3),
        non_campus_required_miles=round(other_m / M_PER_MILE, 3),
        households=hh,
        supports_bands=list(comp.supports_bands or []),
        max_closed_walk_miles=round(comp.max_closed_walk_miles, 2),
        top_streets=[n for n, _ in sorted(names.items(), key=lambda x: -x[1])[:6]],
    )


def loop_quality(route, net):
    """Is this a coherent loop, or an out-and-back with a walk home bolted on?"""
    tr = route.traversals(net)
    miles = route.miles(net)
    nodes = route.node_sequence(net)
    closes = bool(nodes) and nodes[0] == nodes[-1]
    shape = route.loop_shape(net)
    avoidable = tr["avoidable_miles"] / max(miles, 0.01)
    # A coherent loop: it returns to its start, most segments are walked once, and
    # doubling back that is neither a cul-de-sac nor the walk home stays small.
    coherent = closes and shape >= 0.55 and avoidable <= 0.25
    return dict(
        returns_to_start=closes,
        loop_shape=round(shape, 3),
        avoidable_repeat_share=round(avoidable, 3),
        dead_end_return_miles=round(tr["dead_end_return_miles"], 3),
        closing_leg_miles=round(tr["closing_leg_miles"], 3),
        coherent_loop=bool(coherent),
        verdict=("coherent loop" if coherent
                 else "returns to start but retraces heavily" if closes
                 else "does not close"),
    )


def main(date: str = "2026-08-03"):
    net = network.load(date, quiet=True)
    eng = Engine(net)
    fresh = CompletionState(net)

    rows = []
    for name, lon, lat, why in LOCATIONS:
        start = eng.snap(lon, lat)
        snapped = node_lonlat(net, eng.g, start)
        snap_m = (haversine_m(lon, lat, snapped[0], snapped[1])
                  if snapped else float("nan"))
        ci = eng.component_of_node.get(start)
        profile = component_profile(net, eng, ci)

        variants = eng.variants(start, fresh)
        bands = []
        for v in variants:
            r = v.get("route")
            resp = v.get("response")
            if r is None:
                bands.append(dict(band=v["name"], available=False,
                                  state=resp.state if resp else None,
                                  reason=(resp.reason if resp else
                                          v.get("unavailable"))))
                continue
            s = r.score
            covered = r.required_covered(net)
            campus_new = sum(net.segments[i].length_m for i in covered
                             if net.segments[i].campus_obligation == "CANONICAL"
                             and not fresh.is_complete(i))
            bands.append(dict(
                band=v["name"], available=True,
                state=resp.state if resp else None,
                distance_miles=round(r.miles(net), 2),
                estimated_minutes=int(round(r.miles(net) / WALK_MPH * 60)),
                new_required_miles=round(s.new_required_miles, 2),
                campus_new_miles=round(campus_new / M_PER_MILE, 2),
                non_campus_new_miles=round(
                    s.new_required_miles - campus_new / M_PER_MILE, 2),
                households=s.households,
                walk_quality=s.walk_quality,
                **loop_quality(r, net)))

        # Can this walker reach campus AND non-campus coverage without the router
        # inventing anything? Only what is inside their own component counts.
        mixed = (profile.get("campus_required_miles", 0) > 0.1
                 and profile.get("non_campus_required_miles", 0) > 0.1)
        avail = [b for b in bands if b["available"]]
        reaches_both = any(b["campus_new_miles"] > 0.05
                           and b["non_campus_new_miles"] > 0.05 for b in avail)

        rows.append(dict(
            location=name, purpose=why, request_lon=lon, request_lat=lat,
            snap_distance_m=round(snap_m, 1),
            snapped_to=[round(snapped[0], 6), round(snapped[1], 6)] if snapped else None,
            component=profile,
            available_bands=[b["band"] for b in avail],
            unavailable_bands=[b["band"] for b in bands if not b["available"]],
            bands=bands,
            component_mixes_campus_and_town=bool(mixed),
            route_reaches_campus_and_non_campus=bool(reaches_both),
            reachable_without_invented_crossing=True,   # structural: see note below
        ))

    result = dict(
        generated_at=datetime.now(timezone.utc).isoformat(),
        network_id=net.network_id,
        network_version=f"v{net.version}",
        note=("`reachable_without_invented_crossing` is structurally true for every "
              "row: the router is scoped to the start's own component and never "
              "crosses between components, so anything it offers is reachable over "
              "geometry a source asserted. The question that actually matters is "
              "`route_reaches_campus_and_non_campus` — whether the component the "
              "walker landed in contains both kinds of coverage."),
        locations=rows,
        summary=_summary(rows),
    )
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "campus-validation.json")
    with open(path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    _print(rows, result["summary"], path)
    return result


def _summary(rows):
    on_campus = [r for r in rows if "campus" in r["purpose"]]
    return dict(
        locations=len(rows),
        landed_in_main=sum(1 for r in rows if r["component"].get("index") == 0),
        distinct_components=sorted({r["component"].get("index") for r in rows}),
        max_snap_distance_m=max(r["snap_distance_m"] for r in rows),
        locations_with_no_route=[r["location"] for r in rows
                                 if not r["available_bands"]],
        locations_with_all_five=[r["location"] for r in rows
                                 if len(r["available_bands"]) == len(VARIANTS)],
        coherent_loop_rate=round(
            sum(1 for r in rows for b in r["bands"]
                if b.get("available") and b.get("coherent_loop"))
            / max(sum(1 for r in rows for b in r["bands"] if b.get("available")), 1), 3),
        campus_starts_reaching_both=[r["location"] for r in on_campus
                                     if r["route_reaches_campus_and_non_campus"]],
    )


def _print(rows, summary, path):
    print(f"{'location':<42}{'snap m':>8}{'comp':>6}{'req mi':>9}{'bands':>7}"
          f"{'best mi':>9}{'new mi':>8}{'hh':>7}  loop")
    print("-" * 110)
    for r in rows:
        avail = [b for b in r["bands"] if b["available"]]
        best = max(avail, key=lambda b: b["distance_miles"], default=None)
        c = r["component"]
        loop = ("coherent" if best and best["coherent_loop"]
                else best["verdict"][:22] if best else "-")
        print(f"{r['location'][:41]:<42}{r['snap_distance_m']:>8.0f}"
              f"{c.get('index', -1):>6}{c.get('required_miles', 0):>9.2f}"
              f"{len(avail):>7}"
              f"{(best['distance_miles'] if best else 0):>9.2f}"
              f"{(best['new_required_miles'] if best else 0):>8.2f}"
              f"{(best['households'] if best else 0):>7}  {loop}")
    print()
    print(json.dumps(summary, indent=1))
    print(f"\n-> {path}")


if __name__ == "__main__":
    main()
