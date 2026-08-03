"""Structured routing responses, including the late-opportunity states.

The engine must be able to say "there is nothing worth walking near you" without
padding a route to hide it. These states are decided from **local** conditions — how
far the nearest un-walked street is, how much new mileage a route would earn, how
efficient it would be — never from a town-wide completion percentage. A town at 40%
completion can still have a neighbourhood that is finished, and a town at 95% can
still have good walking left in one corner.

States:
  ROUTE_AVAILABLE              a route worth walking
  LIMITED_LOCAL_COVERAGE       a route exists but most of it is approach or repeat
  LONGER_ROUTE_REQUIRED        this band cannot reach the work; a longer one can
  NO_USEFUL_ROUTE_NEAR_START   nothing reachable from here at any band
  SELECT_DIFFERENT_START_AREA  nothing here, and the work is far enough that the
                               honest advice is to start somewhere else

Every state carries the numbers an interface needs to write its own sentence. No
copy is composed here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

M_PER_MILE = 1609.344

# A route is worth offering when it earns at least this much new required mileage...
MIN_NEW_MILES = 0.25
# ...and at least this share of what is walked is new coverage.
MIN_EFFICIENCY = 0.30
# Beyond this, "go somewhere else" is better advice than "walk further".
FAR_START_MILES = 2.5


@dataclass
class RoutingResponse:
    state: str
    target_miles: float
    band: str | None = None
    route: object = None
    # Facts an interface can turn into a sentence.
    new_required_miles: float = 0.0
    total_miles: float = 0.0
    efficiency: float = 0.0
    approach_miles: float | None = None
    nearest_incomplete_miles: float | None = None
    walk_quality: float | None = None
    households: int = 0
    component_index: int | None = None
    component_description: str | None = None
    component_classification: str | None = None
    available_bands: list = field(default_factory=list)
    suggested_band: str | None = None
    suggested_band_miles: float | None = None
    reason: str = ""
    detail: dict = field(default_factory=dict)

    def as_dict(self):
        d = asdict(self)
        d.pop("route", None)
        return d


def assess(band_name, target_miles, route, meta, component,
           all_band_results=None) -> RoutingResponse:
    """Turn one band's result into a response state.

    `all_band_results` is [(band_name, target_miles, route_or_None, meta)] for the
    whole set, used to say which longer band would work.
    """
    nearest = meta.get("nearest_incomplete_miles")
    approach = meta.get("approach_miles")
    r = RoutingResponse(
        state="", target_miles=target_miles, band=band_name, route=route,
        approach_miles=approach, nearest_incomplete_miles=nearest,
        component_index=getattr(component, "index", None),
        component_description=getattr(component, "description", None),
        component_classification=getattr(component, "classification", None),
        available_bands=list(getattr(component, "supports_bands", []) or []),
    )

    if route is None:
        # Is there a longer band that does reach work?
        better = _first_working_band(all_band_results, after=target_miles)
        if better:
            r.state = "LONGER_ROUTE_REQUIRED"
            r.suggested_band, r.suggested_band_miles = better[0], better[1]
            r.reason = (f"No incomplete required street is reachable and returnable "
                        f"within {target_miles:.1f} mi. The nearest is "
                        f"{nearest:.1f} mi away, which needs the {better[0]} band "
                        f"({better[1]:.1f} mi) or longer.") if nearest else (
                        f"No route at {target_miles:.1f} mi; {better[0]} works.")
            return r
        if nearest is not None and nearest > FAR_START_MILES:
            r.state = "SELECT_DIFFERENT_START_AREA"
            r.reason = (f"The nearest un-walked required street is {nearest:.1f} mi "
                        f"from here — far enough that starting closer to it is better "
                        f"advice than walking further from this point.")
            return r
        r.state = "NO_USEFUL_ROUTE_NEAR_START"
        r.reason = (meta.get("reason")
                    or "No incomplete required street is reachable from this start.")
        if nearest is not None:
            r.reason += f" Nearest un-walked street: {nearest:.1f} mi."
        return r

    s = route.score
    r.new_required_miles = round(s.new_required_miles, 3)
    r.total_miles = round(s.total_miles, 3)
    r.efficiency = round(s.efficiency, 3)
    r.walk_quality = s.walk_quality
    r.households = s.households
    r.detail = dict(
        repeated_miles=round(s.repeated_miles, 3),
        repeat_avoidable_miles=round(s.repeat_avoidable_miles, 3),
        repeat_share=round(s.repeat_share, 3),
        corridor_completions=s.corridor_completions,
        dead_end_completions=s.dead_end_completions,
    )

    if s.new_required_miles >= MIN_NEW_MILES and s.efficiency >= MIN_EFFICIENCY:
        r.state = "ROUTE_AVAILABLE"
        r.reason = (f"{s.new_required_miles:.2f} mi of streets not yet prayed for, "
                    f"{s.efficiency:.0%} of the walk.")
        return r

    # A route exists but it is mostly approach or repeat. Say so, and point at the
    # band that would do better if there is one.
    better = _first_working_band(all_band_results, after=target_miles, min_new=MIN_NEW_MILES,
                                 min_efficiency=MIN_EFFICIENCY)
    r.state = "LIMITED_LOCAL_COVERAGE"
    r.reason = (f"Only {s.new_required_miles:.2f} mi of this {s.total_miles:.1f}-mi walk "
                f"({s.efficiency:.0%}) is new coverage"
                + (f"; {approach:.1f} mi of approach each way to reach it"
                   if approach else "") + ".")
    if better:
        r.suggested_band, r.suggested_band_miles = better[0], better[1]
        r.reason += f" The {better[0]} band reaches more."
    elif nearest is not None and nearest > FAR_START_MILES:
        r.state = "SELECT_DIFFERENT_START_AREA"
        r.reason += (f" The nearest substantial un-walked area is {nearest:.1f} mi "
                     f"away; starting closer to it would walk better.")
    return r


def _first_working_band(all_band_results, after, min_new=0.0, min_efficiency=0.0):
    if not all_band_results:
        return None
    for name, target, route, meta in all_band_results:
        if target <= after or route is None:
            continue
        s = route.score
        if s.new_required_miles >= max(min_new, MIN_NEW_MILES) and \
                s.efficiency >= min_efficiency:
            return name, target
    return None


def summarize_states(responses) -> dict:
    counts = {}
    for r in responses:
        counts[r.state] = counts.get(r.state, 0) + 1
    return counts
