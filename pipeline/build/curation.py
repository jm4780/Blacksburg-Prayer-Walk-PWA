"""Curation configuration: the decisions D1 and D2 encode, expressed as data.

Anything in here is a human judgment, not a data property. It is kept separate from
the classifier so the classifier stays auditable and so a change of mind is a one-line
diff rather than a code change.

`status` on each entry distinguishes decisions that are settled from ones still
awaiting Jacob's yes/no. Provisional entries are applied but reported separately in
the build report so nothing settled-looking is actually pending.
"""

# ---------------------------------------------------------------------------
# D2 — which trails count (docs/03-decisions.md#d2)
# Keys are normalized trail names as produced by build/names.py. Matching is on
# normalized_name, so "Deerfield" (the data's spelling) has already become
# "deerfield trl" via NAME_FIXES by the time it reaches here.
# ---------------------------------------------------------------------------
TRAIL_ROLES = {
    # Confirmed by Jacob 2026-08-02.
    "huckleberry trl": dict(role="REQUIRED", status="CONFIRMED",
                            note="Town spine; paved; passes neighborhoods. D2."),
    # Confirmed by Jacob 2026-08-03 (Phase 3 item 1). Were PROVISIONAL through v1.1.
    "deerfield trl": dict(role="REQUIRED", status="CONFIRMED",
                          note="D2 recommendation accepted at the Phase 3 network "
                               "ruling. PROVISIONAL -> CONFIRMED for network v1.2."),
    "shenandoah trl": dict(role="REQUIRED", status="CONFIRMED",
                           note="D2 recommendation accepted at the Phase 3 network "
                                "ruling. PROVISIONAL -> CONFIRMED for network v1.2."),
    # Explicitly connector-only per D2.
    "gateway trl": dict(role="OPTIONAL_CONNECTOR", status="CONFIRMED",
                        note="3.7 mi dirt, 869 ft gain; destination hike, not a "
                             "neighborhood walk. D2 reason 2."),
    "heritage trl": dict(role="OPTIONAL_CONNECTOR", status="CONFIRMED",
                         note="Park interior, no adjacent homes. D2."),
}

# Spur/underpass/tunnel features inherit their parent trail's role. Keyed on the
# normalized parent name; the classifier matches by prefix.
TRAIL_SPUR_INHERITS = True

# Everything else with Type=Trail lands here until reviewed. Deliberately not
# REQUIRED — an unreviewed trail must never inflate the denominator.
TRAIL_DEFAULT_ROLE = "OPTIONAL_CONNECTOR"
TRAIL_DEFAULT_STATUS = "NEEDS_REVIEW"

# ---------------------------------------------------------------------------
# D1 — Virginia Tech campus (docs/03-decisions.md#d1)
# ---------------------------------------------------------------------------
# The town's single UNIV zoning polygon is the first draft of D1a's campus core.
# It is a starting point for curation, not a finished boundary: it excludes some
# campus land and includes some non-residential parcels. Flagged accordingly.
CAMPUS_CORE_SOURCE = dict(
    layer="zoning",
    where=("Labels", "UNIV"),
    status="DRAFT",
    note="Town UNIV zoning polygon, 1.38 sq mi. D1a asks for a hand-drawn core; "
         "this is the starting point, not the answer.",
)

# Campus pedestrian ways are REQUIRED per D1b — but only ones a human has approved.
# The schema inspection found campus paths in Paths to the Future tagged Owner=VT;
# the classifier leaves them NEEDS_REVIEW, because D1b asks for a *selection* of major
# ways, not blanket inclusion.
CAMPUS_PATH_DEFAULT_ROLE = "OPTIONAL_CONNECTOR"
CAMPUS_PATH_DEFAULT_STATUS = "NEEDS_REVIEW"

# ---------------------------------------------------------------------------
# D1b ruling — network v1.2, 2026-08-03 (Phase 3 item 1)
# ---------------------------------------------------------------------------
# The *selection* D1b asked for is now made, and campus_normalize.py is what makes
# it. Rather than hand-picking street names, the approved selection is: one coverage
# obligation per campus corridor. The corridor's canonical side becomes REQUIRED; the
# parallel walkway on the other side stays a connector and *satisfies* the canonical
# obligation instead of creating a second one (spec §4.2 — walking one side counts).
#
# This is the whole point of the ruling. Promoting all 114 campus pedestrian segments
# would demand 13.403 mi of walking to cover 11.358 mi of distinct ground, and would
# make Drillfield Drive count as unfinished until a walker had been down both sides.
CAMPUS_PROMOTE_CANONICAL_TO_REQUIRED = True
CAMPUS_PROMOTION_STATUS = "CONFIRMED"
CAMPUS_PROMOTION_NOTE = (
    "D1b: campus pedestrian corridors carry the coverage obligation for campus, "
    "because the town Roads layer does not contain campus streets at all (see "
    "docs/02-technical-plan.md §2.4a). One obligation per corridor: the canonical "
    "side is REQUIRED, parallel walkways are ALTERNATIVE and satisfy it. "
    "Promoted for network v1.2, 2026-08-03.")

# A parallel walkway is credited with covering a canonical segment when it runs
# alongside at least this share of that segment's length. Below the threshold it is
# beside part of the corridor but does not stand in for the whole obligation.
CAMPUS_SATISFY_SHARE = 0.6

# ---------------------------------------------------------------------------
# Hard exclusions — limited-access facilities nobody walks.
# ---------------------------------------------------------------------------
EXCLUDE_ROAD_CLASS = {
    "Ramp": "Limited-access ramp; not walkable.",
    "Primary": "US-460 bypass; limited access, no pedestrian facility.",
}

# ---------------------------------------------------------------------------
# Household association
# ---------------------------------------------------------------------------
# Nominal association cap. Units beyond this distance from any eligible segment are
# not silently attached to the nearest one — they are reported as unassociated.
ASSOCIATION_CAP_M = 75.0

# A named complex whose internal circulation is not modelled by any eligible segment
# gets held for review rather than dumped onto its frontage street. See
# docs/06-household-methodology.md.
COMPLEX_MIN_UNITS_FOR_REVIEW = 25

# Complexes a human has named for review regardless of what the automatic test says.
# Matched case-insensitively as a substring of PlaceName. These three were called out
# in the Phase 2a instruction; the heuristic clears two of them, and a named human
# instruction outranks a heuristic.
ALWAYS_REVIEW_COMPLEXES = [
    "The Mill",
    "Hunters Ridge",
    "Terrace View",
]


# ---------------------------------------------------------------------------
# Segment role overrides — human eligibility corrections applied after the
# automatic rules, per technical plan §2.4. Keyed on normalized_name so they
# survive a rebuild that renumbers segment ids.
#
# These are corrections to *eligibility*, not routing tuning. Each needs a
# reason a reviewer can check.
# ---------------------------------------------------------------------------
ROLE_OVERRIDES_BY_NAME = {
    "gordon c willis smart rd": dict(
        role="EXCLUDED",
        access_type="GATED",
        status="CONFIRMED",
        reason=("The Virginia Smart Road is Virginia Tech Transportation Institute's "
                "controlled research facility, not a public street. It is gated, "
                "instrumented, and closed to the public except on organised tours; "
                "members of the public cannot lawfully walk it. It carries "
                "RD_MAINT=Blacksburg in the town's 911 file because emergency "
                "vehicles must be routed there, which is exactly the failure mode the "
                "Phase 1 audit warned about: presence in a 911 road layer is not "
                "evidence of public access. Reclassified REQUIRED -> EXCLUDED "
                "2026-08-03 (Phase 2b.1 item 3)."),
    ),
}
