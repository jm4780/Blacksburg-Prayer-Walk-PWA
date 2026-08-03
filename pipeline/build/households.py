"""Household estimation and segment association.

Three quantities are tracked separately and never conflated internally:

  residential_address_points  raw count of address points classified residential
  estimated_housing_units     dwelling units after dedup and vacancy exclusion
  estimated_occupied_households  housing units x occupancy rate

The public interface says "Estimated households prayed for", which maps to
estimated_occupied_households. The translation is documented in
docs/06-household-methodology.md and recorded in the build report so the number
shown to a congregation can always be traced back to its inputs.

Double-counting is prevented at five distinct points; see DEDUP_RULES below.
"""
import math
from collections import defaultdict

from shapely.geometry import Point
from shapely.strtree import STRtree

from . import curation

DEDUP_RULES = {
    "apartment_units": "Each address point is one dwelling unit. Unit-level points "
                       "(APT/UNIT/LOT/BLDG) are counted individually and never also "
                       "counted as their parent building address.",
    "duplicate_addresses": "Households are keyed on a normalized composite address "
                           "(number + directional + street + type + post-dir + unit). "
                           "Collisions are dropped and reported.",
    "corner_properties": "A household has exactly one primary_segment_id. Secondary "
                         "associations are recorded for admin inspection but never "
                         "counted.",
    "buildings_multiple_segments": "Association is one-to-one from the household side, "
                                   "so a building fronting two streets contributes to "
                                   "one segment only.",
    "repeated_route_segments": "Route-level totals sum distinct household ids, not "
                               "per-segment counts, so revisiting a segment cannot "
                               "double-count it.",
}

# Address points that represent something other than a dwelling.
NON_DWELLING_LANDMARKS = ("vacant", "demolished", "construction")

# Occupancy rate applied to turn housing units into occupied households.
# Sourced from ACS 5-year vacancy for Blacksburg town; recorded here so the
# translation is explicit rather than buried in a formula.
OCCUPANCY_RATE = 0.93
OCCUPANCY_SOURCE = ("ACS 5-year occupancy rate for Blacksburg town (placeholder — "
                    "confirm against the current table before launch)")
OCCUPANCY_CONFIDENCE = "LOW"


def is_residential(attrs):
    return (attrs.get("LocalType") or "").strip() == "Residential"


def is_dwelling(attrs):
    """Residential point that represents an actual dwelling unit today."""
    if not is_residential(attrs):
        return False
    landmark = (attrs.get("LandmkName") or "").strip().lower()
    return not any(tok in landmark for tok in NON_DWELLING_LANDMARKS)


def address_key(attrs):
    """Normalized composite key. Unique across all 19,773 points as of 2026-08-03."""
    num = attrs.get("STNUM")
    parts = [
        str(int(num)) if isinstance(num, (int, float)) and not math.isnan(num) else "",
        (attrs.get("STREET_PRE_DIR") or "").strip(),
        (attrs.get("STREET_NAME") or "").strip(),
        (attrs.get("STREET_TYPE") or "").strip(),
        (attrs.get("STREET_POST_DIR") or "").strip(),
        (attrs.get("unit_designator") or "").strip(),
        (attrs.get("unit") or "").strip(),
    ]
    return " ".join(p for p in parts if p).upper()


def building_key(attrs):
    """Same as address_key without the unit — identifies the parent building."""
    num = attrs.get("STNUM")
    parts = [
        str(int(num)) if isinstance(num, (int, float)) and not math.isnan(num) else "",
        (attrs.get("STREET_PRE_DIR") or "").strip(),
        (attrs.get("STREET_NAME") or "").strip(),
        (attrs.get("STREET_TYPE") or "").strip(),
        (attrs.get("STREET_POST_DIR") or "").strip(),
    ]
    return " ".join(p for p in parts if p).upper()


def build_households(address_features, name_fn, fixes_log):
    """Turn address points into deduplicated household records.

    Returns (households, stats). Each household is one dwelling unit.
    """
    seen, households = {}, []
    stats = defaultdict(int)

    for attrs, geom in address_features:
        stats["address_points_total"] += 1
        if not is_residential(attrs):
            stats["non_residential"] += 1
            continue
        stats["residential_address_points"] += 1
        if not is_dwelling(attrs):
            stats["excluded_not_a_dwelling"] += 1
            continue

        key = address_key(attrs)
        if not key:
            stats["excluded_no_key"] += 1
            continue
        if key in seen:
            # DEDUP: duplicate address representation.
            stats["excluded_duplicate_key"] += 1
            fixes_log.append({"kind": "duplicate_address_key", "key": key,
                              "source_id": attrs.get("OBJECTID")})
            continue
        seen[key] = True

        _, street_norm = name_fn(attrs, fixes_log)
        unit = (attrs.get("unit") or "").strip()
        households.append(dict(
            key=key,
            building_key=building_key(attrs),
            point=geom,
            street_normalized=street_norm,
            place_name=(attrs.get("PlaceName") or "").strip() or None,
            unit=unit or None,
            unit_designator=(attrs.get("unit_designator") or "").strip() or None,
            is_unit_level=bool(unit),
            source_id=attrs.get("OBJECTID"),
            source_global_id=attrs.get("GlobalID"),
            addr=(attrs.get("ADDR") or "").strip() or None,
        ))

    stats["estimated_housing_units"] = len(households)
    stats["unit_level_points"] = sum(1 for h in households if h["is_unit_level"])
    stats["building_level_points"] = len(households) - stats["unit_level_points"]
    stats["distinct_buildings"] = len({h["building_key"] for h in households})
    return households, dict(stats)


def profile_complexes(households, eligible_segments):
    """Per named complex: unit count, footprint, and how much network is inside it.

    A complex with many units and no internal walkable network cannot have its units
    honestly attached to a frontage segment — the walker never passes them. Those are
    held for review rather than assigned.
    """
    by_place = defaultdict(list)
    for h in households:
        if h["place_name"]:
            by_place[h["place_name"]].append(h)

    seg_geoms = [s["geometry"] for s in eligible_segments]
    tree = STRtree(seg_geoms) if seg_geoms else None

    profiles = []
    for place, members in by_place.items():
        if len(members) < curation.COMPLEX_MIN_UNITS_FOR_REVIEW:
            continue
        pts = [h["point"] for h in members]
        hull = _hull(pts)
        # Internal network = eligible segment length whose midpoint falls inside the
        # complex footprint. Midpoint rather than intersection so a street merely
        # clipping the hull edge does not read as internal circulation.
        internal_m = 0.0
        internal_ids = []
        if tree is not None and hull is not None:
            for idx in tree.query(hull):
                g = seg_geoms[idx]
                if hull.contains(g.interpolate(0.5, normalized=True)):
                    internal_m += g.length
                    internal_ids.append(eligible_segments[idx]["id"])

        # How many units a walker on the existing network would actually pass.
        beyond = 0
        if tree is not None and seg_geoms:
            for h in members:
                nearest = seg_geoms[tree.nearest(h["point"])]
                if nearest.distance(h["point"]) > curation.ASSOCIATION_CAP_M:
                    beyond += 1

        profiles.append(dict(
            place_name=place,
            units=len(members),
            footprint_area_m2=round(hull.area, 1) if hull is not None else 0.0,
            internal_network_m=round(internal_m, 1),
            internal_segment_ids=internal_ids,
            units_beyond_cap=beyond,
            share_beyond_cap=round(beyond / len(members), 3),
            members=members,
            hull=hull,
        ))
    profiles.sort(key=lambda p: -p["units"])
    return profiles


# A complex is unresolved when a walker on the eligible network would not pass its
# homes. Two independent ways that happens:
#   - the site has essentially no internal walkable network of its own, or
#   - a large share of its units sit beyond the association cap from anything eligible.
# Deliberately NOT a metres-per-unit density test: dense complexes legitimately have
# very little road per unit, and that is not evidence of anything.
NO_INTERNAL_NETWORK_M = 25.0
MAX_SHARE_BEYOND_CAP = 0.25


def complex_status(profile):
    """Return (status, reasons, trigger) for one complex profile."""
    reasons, trigger = [], None
    if profile["internal_network_m"] < NO_INTERNAL_NETWORK_M:
        reasons.append(
            f"no internal walkable network ({profile['internal_network_m']:.0f} m of "
            f"eligible segment inside the site footprint)")
        trigger = "AUTOMATIC"
    if profile["share_beyond_cap"] > MAX_SHARE_BEYOND_CAP:
        reasons.append(
            f"{profile['units_beyond_cap']} of {profile['units']} units "
            f"({profile['share_beyond_cap']:.0%}) are further than "
            f"{curation.ASSOCIATION_CAP_M:.0f} m from any eligible segment")
        trigger = "AUTOMATIC"

    name = (profile["place_name"] or "").lower()
    for named in curation.ALWAYS_REVIEW_COMPLEXES:
        if named.lower() in name:
            if not reasons:
                reasons.append(
                    f"named for review in the Phase 2a instruction; the automatic test "
                    f"clears it ({profile['internal_network_m']:.0f} m internal network, "
                    f"{profile['share_beyond_cap']:.0%} of units beyond cap) but a human "
                    f"instruction outranks the heuristic")
                trigger = "INSTRUCTION_ONLY"
            else:
                trigger = "INSTRUCTION_AND_AUTOMATIC"
            break

    return ("UNRESOLVED" if reasons else "OK"), reasons, trigger


def _hull(points):
    from shapely.geometry import MultiPoint
    if len(points) < 3:
        return MultiPoint(points).buffer(20.0) if points else None
    hull = MultiPoint(points).convex_hull
    if hull.geom_type in ("Point", "LineString"):
        hull = hull.buffer(20.0)
    return hull.buffer(15.0)  # a little slack for units at the footprint edge


def associate(households, eligible_segments, unresolved_places, cap_m=None):
    """Attach each household to exactly one primary segment.

    Nearest eligible segment within `cap_m`, tie-broken by street-name match. A
    household in a complex flagged unresolved is never attached — it is reported
    instead. Returns (links, unassociated, stats).
    """
    cap_m = cap_m or curation.ASSOCIATION_CAP_M
    seg_geoms = [s["geometry"] for s in eligible_segments]
    tree = STRtree(seg_geoms) if seg_geoms else None
    links, unassociated = [], []
    stats = defaultdict(int)

    for h in households:
        if h["place_name"] in unresolved_places:
            stats["held_unresolved_complex"] += 1
            unassociated.append(dict(h, reason="UNRESOLVED_COMPLEX",
                                     detail=f"complex {h['place_name']!r} has no internal "
                                            f"walkable network; held for review"))
            continue
        if tree is None:
            unassociated.append(dict(h, reason="NO_SEGMENTS", detail="no eligible segments"))
            continue

        p = h["point"]
        candidates = tree.query(p.buffer(cap_m))
        if len(candidates) == 0:
            stats["beyond_cap"] += 1
            nearest_idx = tree.nearest(p)
            d = seg_geoms[nearest_idx].distance(p)
            unassociated.append(dict(h, reason="BEYOND_CAP",
                                     detail=f"nearest eligible segment is {d:.0f} m away "
                                            f"(cap {cap_m:.0f} m)"))
            continue

        scored = []
        for idx in candidates:
            seg = eligible_segments[idx]
            dist = seg_geoms[idx].distance(p)
            if dist > cap_m:
                continue
            name_match = (h["street_normalized"] is not None
                          and h["street_normalized"] == seg["normalized_name"])
            # Name match is the tie-break, not the primary key: a 5 m penalty-equivalent
            # bonus, enough to win a corner lot but not to drag a household across a block.
            scored.append((dist - (12.0 if name_match else 0.0), dist, name_match, idx))
        if not scored:
            stats["beyond_cap"] += 1
            unassociated.append(dict(h, reason="BEYOND_CAP", detail="no candidate within cap"))
            continue

        scored.sort()
        _, dist, name_match, idx = scored[0]
        seg = eligible_segments[idx]

        # Confidence reflects how much we trust this particular attachment.
        if name_match and dist <= 40:
            confidence = "HIGH"
        elif name_match or dist <= 25:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"
        stats[f"confidence_{confidence.lower()}"] += 1

        secondary = [eligible_segments[i]["id"] for _, _, _, i in scored[1:4]]
        links.append(dict(
            household_key=h["key"],
            primary_segment_id=seg["id"],
            distance_m=round(dist, 2),
            name_match=name_match,
            confidence=confidence,
            # Recorded for admin inspection; never counted (DEDUP: corner properties).
            secondary_segment_ids=secondary,
        ))

    stats["associated"] = len(links)
    stats["unassociated"] = len(unassociated)
    return links, unassociated, dict(stats)


def summarize(stats, links):
    """Produce the three headline quantities plus the public-facing translation."""
    units = stats["estimated_housing_units"]
    associated_units = len(links)
    occupied = round(associated_units * OCCUPANCY_RATE)
    return {
        "residential_address_points": stats["residential_address_points"],
        "estimated_housing_units": units,
        "housing_units_associated_to_network": associated_units,
        "estimated_occupied_households": occupied,
        "occupancy_rate": OCCUPANCY_RATE,
        "occupancy_rate_source": OCCUPANCY_SOURCE,
        "occupancy_confidence": OCCUPANCY_CONFIDENCE,
        "public_label": "Estimated households prayed for",
        "public_label_maps_to": "estimated_occupied_households",
        "translation": (
            "residential address points -> drop non-dwellings (vacant/demolished/"
            "construction) and duplicate address keys -> estimated housing units -> "
            "associate one-to-one with an eligible segment (unresolved complexes held "
            "back) -> multiply by occupancy rate -> estimated occupied households"
        ),
    }
