"""Walking-pace analysis (Phase 3.5, Priority 11).

The product converts a time budget into a distance with one number:

    miles = minutes / 60 * DEFAULT_PACE_MPH

Everything the walker is told about duration rests on that constant, so it is worth
being explicit about what it is and what it is not.

**It is an assumption, not a measurement.** No walk in this application is timed —
there is no GPS trace, and `started_at`/`resolved_at` bracket the whole episode
including whatever happened between finishing and remembering to tap the button. This
module measures what *can* be measured from the recorded data and says plainly when
there is not enough of it.

Run it as a script for a written report:

    python -m api.routing.timing
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

M_PER_MILE = 1609.344

# Published walking-pace figures, for context on the constant we chose. These are
# literature values, not observations of this pilot.
REFERENCE_PACES = {
    "Adult casual walking, level ground (typical range)": (2.5, 3.5),
    "Highway Capacity Manual pedestrian design speed": (3.0, 3.0),
    "Older adults / mixed groups (typical range)": (2.0, 2.8),
    "Praying while walking — attentive, unhurried (estimate)": (2.0, 2.8),
}


@dataclass
class Observation:
    walk_id: str
    distance_miles: float
    predicted_minutes: int
    elapsed_minutes: float | None
    time_felt_accurate: bool | None


@dataclass
class Report:
    observations: list[Observation] = field(default_factory=list)
    pace_mph: float = 3.0

    # ------------------------------------------------------------------ counts
    @property
    def n_walks(self) -> int:
        return len(self.observations)

    @property
    def n_timed(self) -> int:
        """Walks with both a start and a resolution — the only timing evidence."""
        return sum(1 for o in self.observations if o.elapsed_minutes is not None)

    @property
    def n_rated(self) -> int:
        return sum(1 for o in self.observations if o.time_felt_accurate is not None)

    # ------------------------------------------------------------------ derived
    @property
    def implied_paces(self) -> list[float]:
        """Miles per hour implied by each timed walk.

        Heavily biased *slow*: the clock keeps running while somebody talks to a
        neighbour, and stops only when they remember to submit. Treat it as an upper
        bound on elapsed time, not a measurement of walking speed.
        """
        return [o.distance_miles / (o.elapsed_minutes / 60.0)
                for o in self.observations
                if o.elapsed_minutes and o.elapsed_minutes > 0]

    @property
    def felt_accurate_rate(self) -> float | None:
        rated = [o.time_felt_accurate for o in self.observations
                 if o.time_felt_accurate is not None]
        return (sum(rated) / len(rated)) if rated else None

    def recommendation(self) -> tuple[str, str]:
        """(verdict, why). The verdict is deliberately conservative."""
        if self.n_timed < 10:
            return ("KEEP 3.0 mph", (
                f"Only {self.n_timed} walk(s) carry both a start and a resolution "
                f"time, and elapsed time is not walking time in any case. There is no "
                f"evidence here that would justify moving the constant. Revisit after "
                f"a pilot with at least 10 completed, timed walks."))

        paces = self.implied_paces
        median = statistics.median(paces)
        if abs(median - self.pace_mph) < 0.25:
            return ("KEEP 3.0 mph",
                    f"Median implied pace {median:.2f} mph is within 0.25 of the "
                    f"assumed {self.pace_mph:.1f}.")
        direction = "slower" if median < self.pace_mph else "faster"
        return (f"CONSIDER {median:.1f} mph",
                f"Median implied pace {median:.2f} mph across {len(paces)} timed "
                f"walks is materially {direction} than the assumed "
                f"{self.pace_mph:.1f}. Elapsed time overstates walking time, so a "
                f"slow reading is weak evidence; a fast one is strong.")


def collect(db, pace_mph: float = 3.0) -> Report:
    """Read what the database can actually support a timing claim with."""
    from sqlalchemy import select

    from ..app.models import RouteFeedback, Walk

    rated = {f.walk_id: f.time_felt_accurate
             for f in db.execute(select(RouteFeedback)).scalars()}

    rep = Report(pace_mph=pace_mph)
    for w in db.execute(select(Walk).where(Walk.status == "COMPLETED")).scalars():
        elapsed = None
        if w.started_at and w.resolved_at:
            elapsed = (w.resolved_at - w.started_at).total_seconds() / 60.0
            if elapsed <= 0 or elapsed > 8 * 60:
                # A walk "finished" the next morning is a forgotten tab, not a walk.
                elapsed = None
        rep.observations.append(Observation(
            walk_id=w.id,
            distance_miles=w.final_distance_miles or w.distance_miles,
            predicted_minutes=w.estimated_minutes,
            elapsed_minutes=elapsed,
            time_felt_accurate=rated.get(w.id),
        ))
    return rep


def budget_feasibility(net, engine, state, minutes_range, pace_mph: float = 3.0):
    """What the slider can actually deliver at each end of its range.

    A time budget the router cannot hit is worse than no slider at all: the walker
    asks for 20 minutes and is handed 35. This measures the gap between what each
    slider position asks for and what the engine returns.
    """
    from . import missions

    rows = []
    for minutes in minutes_range:
        target = minutes / 60.0 * pace_mph
        found = missions.discover(net, engine, state, target, slate_size=3)
        if not found:
            rows.append(dict(minutes=minutes, target_miles=round(target, 2),
                             offered=0, best_miles=None, best_minutes=None,
                             error_minutes=None))
            continue
        best = min(found, key=lambda m: abs(m.distance_miles - target))
        got = int(round(best.distance_miles / pace_mph * 60))
        rows.append(dict(minutes=minutes, target_miles=round(target, 2),
                         offered=len(found), best_miles=best.distance_miles,
                         best_minutes=got, error_minutes=got - minutes))
    return rows


def render(rep: Report) -> str:
    out: list[str] = []
    w = out.append
    w("Walking-pace analysis")
    w("=" * 60)
    w(f"assumed pace             : {rep.pace_mph:.1f} mph")
    w(f"completed walks          : {rep.n_walks}")
    w(f"with usable elapsed time : {rep.n_timed}")
    w(f"with a 'time felt right' : {rep.n_rated}")
    w("")

    if rep.n_timed:
        paces = rep.implied_paces
        w(f"implied pace, median     : {statistics.median(paces):.2f} mph")
        w(f"implied pace, range      : {min(paces):.2f} – {max(paces):.2f} mph")
        w("  (elapsed time includes stops; this understates walking speed)")
    else:
        w("implied pace             : no timed walks — nothing to compute")

    rate = rep.felt_accurate_rate
    w(f"'the time was about right': "
      + (f"{rate:.0%} of {rep.n_rated}" if rate is not None else "no responses"))
    w("")

    w("Reference paces (literature, not observations of this pilot)")
    for label, (lo, hi) in REFERENCE_PACES.items():
        w(f"  {label:<58} {lo:.1f}–{hi:.1f} mph")
    w("")

    verdict, why = rep.recommendation()
    w(f"VERDICT: {verdict}")
    for line in _wrap(why, 72):
        w(f"  {line}")
    return "\n".join(out)


def _wrap(text: str, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for word in words:
        if len(cur) + len(word) + 1 > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        lines.append(cur)
    return lines


def main() -> None:
    from ..app.db import SessionLocal, init_db
    from ..app.services import mission_service

    init_db()
    with SessionLocal() as db:
        rep = collect(db, pace_mph=mission_service.DEFAULT_PACE_MPH)
    print(render(rep))


if __name__ == "__main__":
    main()
