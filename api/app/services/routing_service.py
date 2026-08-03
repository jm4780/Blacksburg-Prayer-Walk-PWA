"""Route generation: the documented backend contract (§7).

One request produces up to five nested variants. The contract is deliberately narrow:
the browser sends where the walker is and how far they want to go, and receives, per
variant, everything an interface needs to describe the walk and everything an auditor
needs to reproduce it — and no residential data of any kind.

Determinism and diversity (§11):

  Same (start node, seed, completion state, network id) -> byte-identical variants.
  Different requests get different seeds, so two walkers who tap "generate" on the
  same corner at the same moment get different routes even before reservations bite.

The seed is stored on the request, so a route can be regenerated months later and
checked against what was served.
"""
from __future__ import annotations

import secrets

from ...routing.state import Route
from .network_state import BANDS, NetworkService

M_PER_MILE = 1609.344
WALK_MPH = 3.0

# Quality tolerance for diversity (§11). A seed is allowed to cost this much score
# relative to the best seed tried; beyond it, the diversity is not worth the walk.
DIVERSITY_QUALITY_TOLERANCE = 0.15


def new_seed() -> int:
    return secrets.randbelow(2**31 - 1)


def minutes(miles: float) -> int:
    return int(round(miles / WALK_MPH * 60))


def _node_point(ns: NetworkService, r: Route) -> list | None:
    """WGS84 [lon, lat] of the walk's start node, read off its first segment."""
    if not r.seg_seq:
        return None
    seg = ns.net.segments[r.seg_seq[0]]
    if not seg.coords:
        return None
    return list(seg.coords[0] if seg.u == r.start_node else seg.coords[-1])


def _variant_payload(ns: NetworkService, band: str, target: float, v: dict,
                     component, seed: int, network_version: str) -> dict:
    """The 17 documented per-variant outputs.

    Everything here is either an aggregate, a segment id, or public street geometry.
    No household coordinate, address or count-per-segment leaves this function — the
    household figure is a single number for the whole route.
    """
    r: Route | None = v.get("route")
    resp = v.get("response")
    base = dict(
        # 1-3 identity
        band=band,
        target_miles=target,
        available=r is not None,
        # 4 response state (§10 late-opportunity states)
        state=resp.state if resp else "NO_USEFUL_ROUTE_NEAR_START",
        reason=resp.reason if resp else (v.get("unavailable") or ""),
    )
    if r is None:
        base.update(
            distance_miles=None, estimated_minutes=None, new_required_miles=None,
            repeated_miles=None, efficiency=None, households=None,
            walk_quality=None, segment_count=None, required_segment_count=None,
            dead_end_returns_miles=None, closing_leg_miles=None,
            nests_within_shorter=None, suggested_band=(resp.suggested_band if resp else None),
            nearest_incomplete_miles=(resp.nearest_incomplete_miles if resp else None),
            component=_component_payload(component),
            score_components=None, segment_ids=[], required_segment_ids=[],
            connector_segment_ids=[], geometry=None, campus_credited_miles=None,
            route_score=None, start_point=None, end_point=None, seed=seed,
            network_version=network_version, engine_version=_engine_version(),
        )
        return base

    s = r.score
    tr = r.traversals(ns.net)
    dist = r.miles(ns.net)
    base.update(
        # 5-10 what the walk is
        distance_miles=round(dist, 2),
        estimated_minutes=minutes(dist),
        new_required_miles=round(s.new_required_miles, 2),
        repeated_miles=round(s.repeated_miles, 2),
        efficiency=round(s.efficiency, 3),
        households=s.households,
        # 11-13 quality
        walk_quality=s.walk_quality,
        dead_end_returns_miles=round(tr["dead_end_return_miles"], 2),
        closing_leg_miles=round(tr["closing_leg_miles"], 2),
        # 14-15 structure
        segment_count=len(r.seg_seq),
        required_segment_count=len(r.required_covered(ns.net)),
        nests_within_shorter=bool(v.get("nested")),
        # 16 where it can be walked
        component=_component_payload(component),
        # 17 the transparent score, stored so a route can be re-scored later
        score_components=s.components,
        # coverage earned by walking a parallel campus walkway rather than the
        # canonical side — surfaced so the claim is auditable, not silent
        campus_credited_miles=round(s.credited_required_miles, 3),
        suggested_band=(resp.suggested_band if resp else None),
        nearest_incomplete_miles=(resp.nearest_incomplete_miles if resp else None),
        segment_ids=ns.ids(r.seg_seq),
        required_segment_ids=sorted(ns.required_ids(r.required_covered(ns.net))),
        connector_segment_ids=sorted({ns.id_of_idx[i] for i in set(r.seg_seq)
                                      if not ns.net.segments[i].required}),
        # A closed walk, so start and end are the same node — reported as two fields
        # anyway, because the contract promises both and a future open route would
        # break a caller that assumed otherwise.
        start_point=_node_point(ns, r),
        end_point=_node_point(ns, r),
        route_score=s.total,
        seed=seed,
        network_version=network_version,
        engine_version=_engine_version(),
    )
    return base


def _component_payload(c) -> dict | None:
    if c is None:
        return None
    return dict(index=c.index, description=c.description,
                classification=c.classification,
                required_miles=round(c.required_miles, 3),
                supported_bands=list(c.supports_bands or []),
                # §9: a small area with less required mileage than the shortest band
                # is offered as "complete this area", not as a sixth size.
                complete_area_miles=(round(c.max_closed_walk_miles, 2)
                                     if c.required_miles < BANDS[0][1] else None))


def completion_state_version(state) -> str:
    """A short, stable fingerprint of the completion state (§7).

    Two requests with the same seed reproduce identical routes only if the town has
    not changed underneath them. Storing this makes a failure to reproduce
    *explainable* rather than mysterious.
    """
    import hashlib
    h = hashlib.sha256()
    for i in sorted(state.complete):
        h.update(str(i).encode())
        h.update(b",")
    return f"cs-{len(state.complete)}-{h.hexdigest()[:12]}"


def generate(ns: NetworkService, lon: float, lat: float, state, seed: int,
             requested_family: str | None = None) -> dict:
    """Run the engine for one request and return the full variant set.

    `requested_family` narrows the response to one band. The default is to return all
    of them: §7 prefers one response carrying every related variant, because the size
    control has to be able to re-render without another round trip.
    """
    eng = ns.engine_with_seed(seed)
    start = eng.snap(lon, lat)
    component = eng.component_for(start)
    variants = eng.variants(start, state)
    if requested_family:
        variants = [v for v in variants if v["name"] == requested_family] or variants

    network_version = ns.manifest["canonical_network_version"]
    payload = [_variant_payload(ns, v["name"], v["target_miles"], v, component,
                                seed, network_version)
               for v in variants]

    # Route geometry, resolved server-side from the frozen network. Sent as one
    # LineString per variant rather than per segment, because the browser only ever
    # draws it.
    geoms = {}
    for v, p in zip(variants, payload):
        r = v.get("route")
        p["geometry"] = _line(ns, r) if r is not None else None
        if r is not None:
            geoms[p["band"]] = p["geometry"]

    available = [p for p in payload if p["available"]]
    comp = _component_payload(component)
    return dict(
        start_node=start,
        coverage_area_id=(f"comp-{component.index}" if component is not None else None),
        completion_state_version=completion_state_version(state),
        seed=seed,
        network_id=ns.net.network_id,
        engine_version=_engine_version(),
        component=_component_payload(component),
        variants=payload,
        available_bands=[p["band"] for p in available],
        # The overall answer to "is there anything worth walking here?". Taken from
        # the longest available band, because a Quick failure with a working Medium is
        # not a no.
        state=(available[-1]["state"] if available
               else (payload[-1]["state"] if payload else "NO_USEFUL_ROUTE_NEAR_START")),
        routes=geoms,
    )


def _engine_version() -> str:
    from ...routing.engine import ENGINE_VERSION
    return ENGINE_VERSION


def _line(ns: NetworkService, route: Route) -> dict:
    """The walk as one ordered LineString in WGS84.

    Segment coordinate lists are stored in their own digitised direction, so each has
    to be flipped to match the direction of travel or the line zigzags.
    """
    coords: list = []
    cur = route.start_node
    for idx in route.seg_seq:
        seg = ns.net.segments[idx]
        pts = list(seg.coords)
        if not pts:
            continue
        if seg.u == cur:
            nxt = seg.v
        else:
            pts.reverse()
            nxt = seg.u
        if coords and coords[-1] == pts[0]:
            pts = pts[1:]
        coords.extend(pts)
        cur = nxt
    return {"type": "LineString", "coordinates": coords}
