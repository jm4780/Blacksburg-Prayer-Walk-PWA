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
# homes. Deliberately NOT a metres-per-unit density test: dense complexes legitimately
# have very little road per unit, and that is not evidence of anything.
NO_INTERNAL_NETWORK_M = 25.0
MAX_SHARE_BEYOND_CAP = 0.25


def complex_status(profile):
    """v1 rule, kept for comparison. See `complex_disposition` for what the build uses."""
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


# --- v2, recalibrated against the three named complexes ---------------------
#
# The v1 rule held every unit in any complex it flagged, and flagged on "no internal
# network" alone. Looking at the three calibration complexes shows both halves of that
# were wrong:
#
#   Hunters Ridge   108 units, 0.09 mi internal, but 105/108 within the cap.
#                   v1 held all 108. A walker on Seneca Dr genuinely passes this site —
#                   it is 4.8 acres. Holding it was over-caution.
#   Terrace View    558 units, 1.37 mi internal, 486/558 within the cap.
#                   v1 held all 558 because it was named. Only the 72-unit tail is
#                   actually unreachable.
#   The Mill        162 units, ZERO internal network, 40% beyond the cap, median
#                   distance 72 m. v1 was right to hold this one entirely.
#
# So: site size and reach decide the disposition, and holding is per-unit wherever the
# site is genuinely walked. Holding a whole complex is reserved for sites a walker
# cannot pass at all.
TIER_A_MAX_SHARE = 0.10      # reachable — accept automatic association
TIER_B_MAX_SHARE = 0.35      # mostly reachable — associate the reachable units
SMALL_SITE_ACRES = 6.0       # below this, frontage genuinely serves the site

DISPOSITIONS = {
    "ACCEPT_AUTOMATIC_ASSOCIATION": "associate every unit within the cap; hold none",
    "ASSOCIATE_WITH_FRONTAGE_STREETS": "associate units within the cap; hold the tail "
                                       "for hand-assignment to frontage",
    "ADD_AUTHORITATIVE_PEDESTRIAN_NETWORK": "hold every unit until internal walkways "
                                            "are sourced or digitised",
}


def complex_disposition(profile):
    """Return (disposition, hold_mode, reasons, flags).

    hold_mode is 'NONE' | 'BEYOND_CAP_ONLY' | 'ALL'.
    """
    share = profile["share_beyond_cap"]
    internal = profile["internal_network_m"]
    acres = profile["footprint_area_m2"] / 4046.86
    reasons, flags = [], []

    name = (profile["place_name"] or "").lower()
    named = any(n.lower() in name for n in curation.ALWAYS_REVIEW_COMPLEXES)
    if named:
        flags.append("NAMED_FOR_REVIEW")

    no_internal = internal < NO_INTERNAL_NETWORK_M

    if share > TIER_B_MAX_SHARE or (no_internal and share > TIER_A_MAX_SHARE
                                    and acres > SMALL_SITE_ACRES):
        reasons.append(
            f"{profile['units_beyond_cap']} of {profile['units']} units ({share:.0%}) "
            f"beyond the {curation.ASSOCIATION_CAP_M:.0f} m cap"
            + (f", and no internal walkable network ({internal:.0f} m) across "
               f"{acres:.1f} acres" if no_internal else ""))
        return "ADD_AUTHORITATIVE_PEDESTRIAN_NETWORK", "ALL", reasons, flags

    if share > TIER_A_MAX_SHARE:
        reasons.append(
            f"{profile['units_beyond_cap']} of {profile['units']} units ({share:.0%}) "
            f"beyond the cap, but the site has {internal:.0f} m of internal walkable "
            f"network — most units associate honestly")
        return "ASSOCIATE_WITH_FRONTAGE_STREETS", "BEYOND_CAP_ONLY", reasons, flags

    reasons.append(
        f"only {profile['units_beyond_cap']} of {profile['units']} units ({share:.0%}) "
        f"beyond the cap"
        + (f"; {acres:.1f}-acre site, frontage genuinely serves it" if no_internal else ""))
    return "ACCEPT_AUTOMATIC_ASSOCIATION", "NONE", reasons, flags


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
    household in a complex whose disposition is hold-everything is never attached — it
    is reported instead. Units in partially-held complexes still associate if they are
    within the cap; only the tail is held. Returns (links, unassociated, stats).
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
            # Name match is the tie-break, not the primary key: a 12 m
            # penalty-equivalent bonus, enough to win a corner lot but not to drag a
            # household across a block.
            #
            # REQUIRED segments outrank connectors outright. Coverage obligations live
            # on REQUIRED segments, so a household attached to a connector contributes
            # to nothing a walker can complete — and the public count is defined as
            # units served by REQUIRED coverage.
            bonus = (12.0 if name_match else 0.0) + (1000.0 if seg["role"] == "REQUIRED" else 0.0)
            scored.append((dist - bonus, dist, name_match, idx))
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
        stats[f"role_{seg['role'].lower()}"] += 1
        links.append(dict(
            household_key=h["key"],
            primary_segment_id=seg["id"],
            primary_segment_role=seg["role"],
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
    """The V1 public method: a transparent count of residential units served by
    REQUIRED coverage. No occupancy model.

    An earlier version multiplied by an assumed 0.93 occupancy rate to produce
    "estimated occupied households". That rate was a placeholder with no source, it
    moved the headline by ~800 units, and nobody could audit it. A count of dwelling
    units associated with segments a walker can actually complete is defensible line
    by line, which matters more here than being closer to a true occupied-household
    figure we cannot measure.
    """
    units = stats["estimated_housing_units"]
    required = sum(1 for l in links if l["primary_segment_role"] == "REQUIRED")
    connector = len(links) - required
    return {
        # --- inputs, in order --------------------------------------------
        "residential_address_points": stats["residential_address_points"],
        "estimated_housing_units": units,
        "units_associated_to_required_coverage": required,
        "units_associated_to_connector_only": connector,
        "units_held_for_review": units - len(links),
        # --- the public number -------------------------------------------
        "public_label": "Estimated households prayed for",
        "public_label_maps_to": "units_associated_to_required_coverage",
        "public_value": required,
        "method": "RESIDENTIAL_UNITS_ON_REQUIRED_COVERAGE",
        "occupancy_model_applied": False,
        "occupancy_model_note": (
            "Deliberately none. A residential dwelling unit associated with a REQUIRED "
            "segment is the unit of account. Applying an unsourced occupancy rate would "
            "make the number less auditable, not more accurate."),
        "translation": (
            "residential address points (LocalType=Residential) "
            "-> drop non-dwellings: vacant / demolished / under construction "
            "-> drop duplicate normalized address keys "
            "= estimated housing units "
            "-> associate each unit one-to-one with the nearest REQUIRED segment within "
            "75 m (name-match tie-break; REQUIRED outranks connectors), holding units in "
            "complexes a walker cannot pass "
            "= units associated to REQUIRED coverage = the public number"),
    }
