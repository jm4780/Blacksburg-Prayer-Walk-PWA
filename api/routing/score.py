"""Transparent route scoring.

Every component is computed and stored separately. Retuning is editing `Weights`;
a stored route can be rescored without re-running the search, because the raw
components are kept alongside the total.

Units are normalized before weighting so a weight is a readable statement of relative
importance rather than a unit-conversion factor in disguise.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

M_PER_MILE = 1609.344


@dataclass(frozen=True)
class Weights:
    """Priority order from Phase 2b Step 3, expressed as weights.

    1. Maximize previously incomplete REQUIRED mileage   -> new_required_miles
    2. Complete partially completed corridors            -> corridor_completion
    3. Finish dead ends and isolated leftovers           -> dead_end_completion, isolation
    4. Clear coherent neighbourhood clusters             -> cohesion
    5. Minimize unnecessary repeated travel              -> repeat_penalty
    6. Produce a pleasant, understandable loop           -> stress, turn, shape
    """
    # --- primary objective -------------------------------------------------
    new_required_mile: float = 100.0     # per mile of previously incomplete REQUIRED
    household: float = 0.35              # per household newly passed
    # --- secondary structure ----------------------------------------------
    corridor_completion: float = 25.0    # per named street finished off by this route
    dead_end_completion: float = 12.0    # per dead-end segment cleared
    isolation_bonus: float = 8.0         # per newly-covered segment with few incomplete neighbours
    cohesion: float = 40.0               # x compactness in [0,1]
    # --- costs -------------------------------------------------------------
    repeat_mile: float = -45.0           # per mile walked that earns nothing
    connector_mile: float = -12.0        # per mile on OPTIONAL_CONNECTOR (necessary, not valuable)
    derived_connector_use: float = -6.0  # per synthetic connector traversed
    stress_mile: float = -9.0            # per mile weighted by (walk_stress-1)/4
    turn: float = -0.7                   # per sharp direction change
    uturn: float = -6.0                  # per immediate reversal at a non-dead-end
    # Length deviation is asymmetric on purpose. Overshooting is a promise broken —
    # the user asked for three miles and got four. Undershooting usually means there
    # was not enough incomplete work in reach, which is information, not a fault: a
    # 1.2-mile route that collects everything available beats a 3.5-mile route padded
    # with repeat travel to hit a number. The stress test at 75%+ completion is what
    # made this asymmetry necessary.
    length_overshoot: float = -120.0     # x (actual-target)/target when longer
    length_undershoot: float = -25.0     # x (target-actual)/target when shorter
    # --- shape -------------------------------------------------------------
    loop_shape: float = 18.0             # x how loop-like rather than out-and-back


DEFAULT_WEIGHTS = Weights()


@dataclass
class RouteScore:
    # raw components, all stored so weights can change later
    new_required_miles: float = 0.0
    repeated_miles: float = 0.0
    total_miles: float = 0.0
    connector_miles: float = 0.0
    required_miles_walked: float = 0.0
    corridor_completions: int = 0
    corridors_touched: int = 0
    dead_end_completions: int = 0
    isolated_completions: int = 0
    households: int = 0
    derived_connectors_used: int = 0
    stress_miles: float = 0.0
    turns: int = 0
    uturns: int = 0
    cohesion: float = 0.0
    loop_shape: float = 0.0
    length_deviation: float = 0.0
    length_overshoot: float = 0.0
    length_undershoot: float = 0.0
    efficiency: float = 0.0
    walk_quality: float = 0.0
    total: float = 0.0
    components: dict = field(default_factory=dict)

    def as_dict(self):
        return asdict(self)


def compute(route, net, state, target_miles, w: Weights = DEFAULT_WEIGHTS) -> RouteScore:
    """Score a Route. `state` is a CompletionState; `route.seg_seq` is the walk."""
    s = RouteScore()

    seen = set()
    first_pass_m = 0.0
    for idx in route.seg_seq:
        seg = net.segments[idx]
        s.total_miles += seg.miles
        if idx in seen:
            s.repeated_miles += seg.miles
            continue
        seen.add(idx)
        first_pass_m += seg.length_m
        if seg.role == "REQUIRED":
            s.required_miles_walked += seg.miles
            if not state.is_complete(idx):
                s.new_required_miles += seg.miles
                s.households += seg.households
                if seg.is_dead_end:
                    s.dead_end_completions += 1
                if state.incomplete_neighbours(net, idx) <= 1:
                    s.isolated_completions += 1
        else:
            s.connector_miles += seg.miles
        if seg.is_derived:
            s.derived_connectors_used += 1
        s.stress_miles += seg.miles * (seg.walk_stress - 1) / 4.0

    # Corridor completion: named streets this route finishes off entirely.
    touched, completed = state.corridor_progress(net, seen)
    s.corridors_touched = touched
    s.corridor_completions = completed

    s.turns, s.uturns = route.turn_stats(net)
    s.cohesion = route.cohesion(net)
    s.loop_shape = route.loop_shape(net)
    dev = (s.total_miles - target_miles) / target_miles if target_miles else 0.0
    s.length_deviation = abs(dev)
    s.length_overshoot = max(0.0, dev)
    s.length_undershoot = max(0.0, -dev)
    # Efficiency: new required mileage earned per mile walked. Reported, and used as a
    # tie-break through the repeat penalty rather than as its own term.
    s.efficiency = (s.new_required_miles / s.total_miles) if s.total_miles else 0.0

    c = {
        "new_required": w.new_required_mile * s.new_required_miles,
        "households": w.household * s.households,
        "corridor_completion": w.corridor_completion * s.corridor_completions,
        "dead_end_completion": w.dead_end_completion * s.dead_end_completions,
        "isolation": w.isolation_bonus * s.isolated_completions,
        "cohesion": w.cohesion * s.cohesion,
        "repeat": w.repeat_mile * s.repeated_miles,
        "connector": w.connector_mile * s.connector_miles,
        "derived_connector": w.derived_connector_use * s.derived_connectors_used,
        "stress": w.stress_mile * s.stress_miles,
        "turns": w.turn * s.turns,
        "uturns": w.uturn * s.uturns,
        "length_overshoot": w.length_overshoot * s.length_overshoot,
        "length_undershoot": w.length_undershoot * s.length_undershoot,
        "loop_shape": w.loop_shape * s.loop_shape,
    }
    s.components = {k: round(v, 2) for k, v in c.items()}
    s.total = round(sum(c.values()), 2)

    # A 0-100 readable "would I enjoy this walk" figure, independent of coverage.
    # Deliberately not part of `total` — it is reported to the user, not optimized.
    penalty = (min(1.0, s.repeated_miles / max(s.total_miles, 0.01)) * 45
               + min(1.0, s.stress_miles / max(s.total_miles, 0.01)) * 25
               + min(1.0, s.uturns / 4.0) * 15
               + min(1.0, s.turns / max(s.total_miles * 8, 1)) * 15)
    s.walk_quality = round(max(0.0, 100.0 - penalty) * (0.6 + 0.4 * s.loop_shape), 1)
    return s


def rescore(stored: dict, w: Weights) -> float:
    """Recompute a total from stored raw components under new weights."""
    return round(
        w.new_required_mile * stored["new_required_miles"]
        + w.household * stored["households"]
        + w.corridor_completion * stored["corridor_completions"]
        + w.dead_end_completion * stored["dead_end_completions"]
        + w.isolation_bonus * stored["isolated_completions"]
        + w.cohesion * stored["cohesion"]
        + w.repeat_mile * stored["repeated_miles"]
        + w.connector_mile * stored["connector_miles"]
        + w.derived_connector_use * stored["derived_connectors_used"]
        + w.stress_mile * stored["stress_miles"]
        + w.turn * stored["turns"]
        + w.uturn * stored["uturns"]
        + w.length_overshoot * stored["length_overshoot"]
        + w.length_undershoot * stored["length_undershoot"]
        + w.loop_shape * stored["loop_shape"], 2)
