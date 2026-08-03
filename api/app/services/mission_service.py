"""Missions, as the walker sees them.

This is the application layer. It takes the domain-neutral slate that
`api/routing/missions.py` produces — clusters, coverage, candidate starts, routes —
and turns it into *"Continue praying through Hethwood. About 45 minutes, roughly 460
households."*

The split is deliberate (docs/17 §7): the engine knows about coverage, this file knows
about prayer. Every prayer-specific word in the product below the interface lives here.

Two things this file owns beyond wording:

  Caching.     A slate takes 1–5 s to compute, which is too slow to make a person wait
               on every slider nudge. Slates are cached on (network, budget bucket,
               completion-state fingerprint) and invalidate themselves the moment
               anybody records a walk, because the fingerprint changes.

  Assignment.  Everyone asking "what should I walk?" would otherwise get the same
               answer. The slate is deliberately several genuinely different walks, and
               a participant is given one of them based on who they are, skipping any
               that somebody else currently holds.
"""
from __future__ import annotations

import hashlib
import time
from collections import OrderedDict

from ...routing import missions as mission_engine
from ...routing.engine import ENGINE_VERSION
from ..config import settings
from .network_state import NetworkService

M_PER_MILE = 1609.344

# Time-budget bounds offered by the slider (Priority 4).
MIN_MINUTES = 20
MAX_MINUTES = 90
STEP_MINUTES = 5

# The walking pace used to turn minutes into miles. Labelled "estimated" everywhere it
# is shown. See docs/18 for the timing analysis behind keeping this at 3.0 for now.
DEFAULT_PACE_MPH = 3.0

# Slate cache. Small, because it is keyed on a coarse budget bucket and the completion
# fingerprint changes whenever the town moves.
_CACHE: "OrderedDict[tuple, tuple[float, list]]" = OrderedDict()
_CACHE_MAX = 32
_CACHE_TTL_S = 900

# The label the routing layer uses for coverage with no neighbourhood name — trails,
# mostly, which cross several neighbourhoods and belong to none.
UNLABELLED = "__unlabelled__"

CAMPUS_LABEL = "Virginia Tech"


def minutes_to_miles(minutes: float, pace_mph: float = DEFAULT_PACE_MPH) -> float:
    return round(minutes / 60.0 * pace_mph, 3)


def miles_to_minutes(miles: float, pace_mph: float = DEFAULT_PACE_MPH) -> int:
    return int(round(miles / pace_mph * 60.0))


def clamp_minutes(minutes: float) -> int:
    m = max(MIN_MINUTES, min(MAX_MINUTES, int(round(float(minutes) / STEP_MINUTES))
                             * STEP_MINUTES))
    return m


def state_fingerprint(state) -> str:
    h = hashlib.sha256()
    for i in sorted(state.complete):
        h.update(str(i).encode())
        h.update(b",")
    return f"{len(state.complete)}-{h.hexdigest()[:12]}"


def _reserved_fingerprint(reserved) -> str:
    """Identify a set of holds, not merely whether any exist.

    Keying on `bool(reserved)` was wrong in a way that only shows up with more than one
    walker: two different sets of held streets hashed the same, so the second walker
    could be handed a cached slate computed against somebody else's holds. Reservations
    are soft, so nothing breaks — but the steering that is supposed to send two people
    to different parts of town silently stops steering, which is the whole point of it.
    """
    if not reserved:
        return "0"
    h = hashlib.sha256()
    for i in sorted(reserved):
        h.update(f"{i},".encode())
    return f"{len(reserved)}-{h.hexdigest()[:12]}"


def slate(ns: NetworkService, state, minutes: int, reserved_indices=None,
          size: int = 5) -> list:
    """The cached mission slate for this budget and this state of the town."""
    key = (ns.net.network_id, clamp_minutes(minutes), state_fingerprint(state),
           _reserved_fingerprint(reserved_indices))
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < _CACHE_TTL_S:
        _CACHE.move_to_end(key)
        return hit[1]

    budget = minutes_to_miles(clamp_minutes(minutes))
    found = mission_engine.discover(ns.net, ns.engine, state, budget,
                                    reserved_indices=reserved_indices, slate_size=size)
    _CACHE[key] = (now, found)
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return found


def invalidate() -> None:
    """Called when the town moves. Cheap insurance — the fingerprint would miss it
    anyway, but an explicit clear keeps a stale slate from being served for the few
    seconds between a completion landing and the next fingerprint being taken."""
    _CACHE.clear()


def assign(candidates: list, participant_id: str | None) -> object | None:
    """Give this participant one mission from the slate.

    Deterministic per participant, so refreshing the page does not reshuffle the
    recommendation, and different people get different walks from the same slate. An
    anonymous visitor always sees the strongest one, because they have no identity to
    spread on and the best walk is the most honest preview of what the app offers.
    """
    if not candidates:
        return None
    if not participant_id:
        return candidates[0]
    h = int(hashlib.sha256(participant_id.encode()).hexdigest()[:8], 16)
    return candidates[h % len(candidates)]


# --------------------------------------------------------------------- wording
def _dominant(labels: dict) -> tuple[str | None, float]:
    """The area carrying most of this mission's new coverage, and its share."""
    named = {k: v for k, v in labels.items() if k != UNLABELLED}
    total = sum(labels.values()) or 1.0
    if not named:
        return None, 0.0
    name = max(named, key=named.get)
    return name, named[name] / total


def describe(m, ns: NetworkService) -> dict:
    """Mission title, subtitle and household phrasing.

    Truthfulness rules, from Priority 8 and 9:

      - never say "Finish X" unless the walk genuinely completes X
      - never invent household impact where the data reports none
      - adapt the language to the character of the area rather than reporting a zero
    """
    name, share = _dominant(m.area_labels)
    streets = _headline_streets(m, ns)
    is_campus = name == CAMPUS_LABEL

    # --- title ----------------------------------------------------------------
    if m.completes_cluster and name:
        title = f"Finish the remaining streets in {name}"
    elif m.completes_cluster and streets:
        title = f"Finish the remaining streets around {streets[0]}"
    elif is_campus:
        title = "Pray through the Virginia Tech campus corridors"
    elif name and share >= 0.6:
        title = f"Continue praying through {name}"
    elif name:
        second, _ = _second(m.area_labels, name)
        title = (f"Pray through {name} and {second}" if second
                 else f"Continue praying through {name}")
    elif streets:
        title = f"Pray through the streets around {streets[0]}"
    else:
        title = "Pray through this area"

    # --- household phrasing ---------------------------------------------------
    # A route with no residential units is not without value; it just needs different
    # words. Never print "0 households".
    if m.value >= 25:
        households = f"Approximately {m.value:,} households"
    elif m.value > 0:
        households = f"About {m.value} households"
    elif is_campus:
        households = "Campus walkways — no homes on this route"
    else:
        households = "No homes on this route"

    where = _start_description(m)
    return dict(
        title=title,
        households_line=households,
        has_households=m.value > 0,
        start_description=where,
        area=name,
        areas=[k for k in m.area_labels if k != UNLABELLED],
        completes_area=bool(m.completes_cluster),
    )


def _second(labels: dict, exclude: str) -> tuple[str | None, float]:
    rest = {k: v for k, v in labels.items() if k not in (exclude, UNLABELLED)}
    if not rest:
        return None, 0.0
    name = max(rest, key=rest.get)
    return name, rest[name]


def _headline_streets(m, ns: NetworkService, limit: int = 3) -> list:
    """The streets carrying most of this mission's new coverage."""
    by_name: dict = {}
    for sid in m.required_segment_ids:
        i = ns.idx_of_id.get(sid)
        if i is None:
            continue
        seg = ns.net.segments[i]
        if seg.display_name:
            by_name[seg.display_name] = by_name.get(seg.display_name, 0.0) + seg.length_m
    return [n for n, _ in sorted(by_name.items(), key=lambda x: -x[1])[:limit]]


def _start_description(m) -> str:
    """Where the walk begins. Never phrased as parking (Priority 5)."""
    s = m.start.streets
    if len(s) >= 2:
        return f"{s[0]} at {s[1]}"
    if s:
        return s[0]
    return "the start of the route"


# ---------------------------------------------------------------- presentation
def to_payload(m, ns: NetworkService, pace_mph: float = DEFAULT_PACE_MPH) -> dict:
    """One mission, as the browser receives it.

    Carries what helps somebody understand today's walk, and nothing that helps them
    understand the optimiser. Route score, walk quality, cluster identifiers, coverage
    gain and engine diagnostics all stay server-side (Priority 8) — they remain
    available through the admin endpoints.
    """
    d = describe(m, ns)
    return dict(
        id=m.id,
        title=d["title"],
        households_line=d["households_line"],
        has_households=d["has_households"],
        households=m.value,
        completes_area=d["completes_area"],
        area=d["area"],
        areas=d["areas"],
        estimated_minutes=miles_to_minutes(m.distance_miles, pace_mph),
        distance_miles=m.distance_miles,
        start=dict(lat=m.start.lat, lon=m.start.lon,
                   description=d["start_description"],
                   streets=m.start.streets),
        geometry=_line(m, ns),
        segment_ids=m.segment_ids,
        required_segment_ids=m.required_segment_ids,
        network_version=f"v{ns.net.version}",
        engine_version=ENGINE_VERSION,
    )


def _line(m, ns: NetworkService) -> dict:
    """The walk as one ordered LineString, following the direction of travel."""
    coords: list = []
    cur = m.route.start_node_id
    for idx in m.route.seg_seq:
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


def directions_links(lat: float, lon: float) -> dict:
    """External navigation to the *start* of the walk.

    Only ever to the start point. The app remains the source of truth for the route
    itself, and no claim is made that a mapping app will preserve it.
    """
    return dict(
        apple=f"https://maps.apple.com/?daddr={lat:.6f},{lon:.6f}&dirflg=d",
        google=(f"https://www.google.com/maps/dir/?api=1"
                f"&destination={lat:.6f},{lon:.6f}"),
        geo=f"geo:{lat:.6f},{lon:.6f}",
    )
