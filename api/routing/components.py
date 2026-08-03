"""Routing-component discovery and classification.

The network is not one graph. It is a large main component plus a tail of smaller
ones, and treating "not in the main component" as "not routable" was wrong: a walker
starting inside the Corporate Research Center can walk the CRC perfectly well, whether
or not the CRC connects to downtown across an unreviewed crossing.

Four classifications, per Phase 2b.1 item 2:

  VALID_INDEPENDENT_ROUTING_AREA  public, enough required mileage, supports a closed
                                  walk. Start snapping allowed; stays in the denominator.
  INACCESSIBLE_OR_RESTRICTED      required mileage nobody may lawfully walk. Removed
                                  from the denominator.
  DATA_ERROR_OR_REVIEW_REQUIRED   too small or too fragmentary to route independently;
                                  almost always a missing link in the source. Stays in
                                  the denominator — the street is still required, we
                                  just cannot build a route to it on its own.
  CONNECTOR_ONLY                  no required mileage at all.

The router never invents a connection between components. Separation is reported, not
bridged.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from pyproj import Transformer
from shapely.geometry import LineString
from shapely.ops import transform, unary_union

_TO_M = Transformer.from_crs("EPSG:4326", "EPSG:6594", always_xy=True).transform

M_PER_MILE = 1609.344

# A component needs at least this much required mileage to be worth starting a walk in.
MIN_REQUIRED_MI = 0.25
# Below this separation from another component, the split is a digitising artefact or a
# connector we declined to trust — not a real barrier.
ARTEFACT_SEPARATION_M = 30.0


@dataclass
class Component:
    index: int
    nodes: set
    segment_indices: list
    required_miles: float
    total_miles: float
    households: int
    has_cycle: bool
    all_public: bool
    separation_m: float
    separation_cause: str
    classification: str
    in_denominator: bool
    start_snap_allowed: bool
    description: str
    max_closed_walk_miles: float = 0.0
    supports_bands: list = field(default_factory=list)
    top_streets: list = field(default_factory=list)
    reasons: list = field(default_factory=list)
    centroid: tuple = (0.0, 0.0)


def classify(net, graph) -> list[Component]:
    comps = graph.components()
    by_comp = defaultdict(list)
    for s in net.segments:
        by_comp[_comp_of(graph, comps, s)].append(s)

    # Projected geometry per component, for separation distances.
    geoms = {}
    for ci, comp in enumerate(comps):
        gs = [transform(_TO_M, LineString(s.coords))
              for s in by_comp[ci] if s.coords and len(s.coords) >= 2]
        geoms[ci] = unary_union(gs) if gs else None

    out = []
    for ci, comp in enumerate(comps):
        segs = by_comp[ci]
        req = [s for s in segs if s.required]
        req_mi = sum(s.miles for s in req)
        total_mi = sum(s.miles for s in segs)
        households = sum(s.households for s in req)
        has_cycle = len(segs) >= len(comp)
        # "Restricted" means someone has said you may not walk there — PRIVATE or
        # GATED. UNKNOWN is the default on the paths layer (Owner is blank on 83% of
        # it) and must not be read as a prohibition; treating it as one classified
        # three Shenandoah Trail Spur fragments as INACCESSIBLE, which they are not.
        restricted = [s for s in req if s.access_type in ("PRIVATE", "GATED")]
        all_public = not restricted

        sep_m, sep_cause = _separation(ci, comps, geoms)
        names = defaultdict(float)
        for s in req:
            names[s.display_name or "(unnamed)"] += s.miles
        top = sorted(names.items(), key=lambda x: -x[1])[:5]

        # Upper bound on a closed walk here: every segment out and back.
        max_walk_mi = round(total_mi * 2, 3)
        cls, in_denom, snap, reasons = _rule(ci, req_mi, has_cycle, all_public,
                                             sep_m, len(segs), max_walk_mi)
        c = geoms[ci].centroid if geoms[ci] is not None else None
        out.append(Component(
            index=ci, nodes=set(comp), segment_indices=[s.idx for s in segs],
            required_miles=round(req_mi, 4), total_miles=round(total_mi, 4),
            households=households, has_cycle=has_cycle, all_public=all_public,
            separation_m=round(sep_m, 1), separation_cause=sep_cause,
            classification=cls, in_denominator=in_denom, start_snap_allowed=snap,
            description=_describe(ci, top, req_mi),
            max_closed_walk_miles=max_walk_mi,
            supports_bands=[b for b in BAND_MILES if b <= max_walk_mi],
            top_streets=[dict(name=n, miles=round(v, 3)) for n, v in top],
            reasons=reasons,
            centroid=(round(c.x, 5), round(c.y, 5)) if c is not None else (0.0, 0.0),
        ))
    return out


def _comp_of(graph, comps, seg):
    ni = graph.node_index[seg.u]
    for ci, comp in enumerate(comps):
        if ni in comp:
            return ci
    return -1


def _separation(ci, comps, geoms):
    """Distance to the nearest other component, and what the gap probably means."""
    if ci == 0 or geoms.get(ci) is None:
        return 0.0, "N/A (main component)" if ci == 0 else "no geometry"
    best = float("inf")
    for cj in range(len(comps)):
        if cj == ci or geoms.get(cj) is None:
            continue
        d = geoms[ci].distance(geoms[cj])   # metres: geometry is projected
        if d < best:
            best = d
    if best <= ARTEFACT_SEPARATION_M:
        cause = ("touches or nearly touches another component — separated by a "
                 "connector we declined to route over (CROSSING_REVIEW_REQUIRED / "
                 "LIKELY_FALSE / UNRESOLVED), not by a physical barrier")
    elif best < 150:
        cause = "short gap with no connector proposed within 25 m — probable missing link in the source"
    else:
        cause = "genuinely separate: no nearby geometry in any other component"
    return best, cause


# Length bands the engine offers, smallest first. A component that cannot support the
# smallest band can still be a valid place to walk, but the app has to say so.
BAND_MILES = (1.0, 2.0, 3.5, 5.0, 7.5)


def _rule(ci, req_mi, has_cycle, all_public, sep_m, seg_count, max_walk_mi):
    reasons = []
    if ci == 0:
        return ("VALID_INDEPENDENT_ROUTING_AREA", True, True,
                ["main component"])

    if req_mi <= 0.0005:
        return ("CONNECTOR_ONLY", True, False,
                ["no REQUIRED mileage; usable inside a route but not a place to start"])

    if not all_public:
        reasons.append("contains REQUIRED mileage that is not access_type=PUBLIC")
        return "INACCESSIBLE_OR_RESTRICTED", False, False, reasons

    if req_mi >= MIN_REQUIRED_MI:
        reasons.append(f"{req_mi:.2f} mi of public REQUIRED street"
                       + (" with at least one cycle" if has_cycle
                          else f" (no cycle — walkable out and back, up to "
                               f"{max_walk_mi:.1f} mi)"))
        if sep_m <= ARTEFACT_SEPARATION_M:
            reasons.append("separation is a rejected connector, not a barrier — likely "
                           "merges into the main component once that crossing is "
                           "reviewed, but it routes fine on its own meanwhile")
        if max_walk_mi < BAND_MILES[0] * 0.8:
            reasons.append(f"too small for the Quick band — the app must offer a "
                           f"shorter walk here or say why it cannot")
        return "VALID_INDEPENDENT_ROUTING_AREA", True, True, reasons

    reasons.append(f"only {req_mi:.2f} mi of REQUIRED street across {seg_count} "
                   f"segment(s)" + ("" if has_cycle else ", no cycle"))
    reasons.append("below the threshold for an independent routing area; the mileage "
                   "stays in the denominator and becomes reachable when the missing "
                   "link is fixed")
    return "DATA_ERROR_OR_REVIEW_REQUIRED", True, False, reasons


def _describe(ci, top, req_mi):
    if ci == 0:
        return "Main Blacksburg network"
    if not top:
        return "Connector-only fragment"
    lead = top[0][0]
    if len(top) > 1:
        return f"{lead} area ({', '.join(n for n, _ in top[1:3])})"
    return f"{lead}"


def summary(components):
    """Aggregate for the freeze manifest."""
    agg = defaultdict(lambda: {"components": 0, "required_miles": 0.0, "households": 0})
    for c in components:
        a = agg[c.classification]
        a["components"] += 1
        a["required_miles"] += c.required_miles
        a["households"] += c.households
    for a in agg.values():
        a["required_miles"] = round(a["required_miles"], 3)
    valid = [c for c in components
             if c.classification == "VALID_INDEPENDENT_ROUTING_AREA"]
    denom = sum(c.required_miles for c in components if c.in_denominator)
    return dict(
        by_classification=dict(agg),
        valid_routing_areas=len(valid),
        required_miles_in_denominator=round(denom, 3),
        required_miles_removed_from_denominator=round(
            sum(c.required_miles for c in components if not c.in_denominator), 3),
        required_miles_in_valid_areas=round(sum(c.required_miles for c in valid), 3),
        required_miles_needing_review=round(
            sum(c.required_miles for c in components
                if c.classification == "DATA_ERROR_OR_REVIEW_REQUIRED"), 3),
    )
