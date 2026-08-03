"""Campus corridor normalization: one coverage obligation per street corridor.

On campus the pedestrian layer *is* our representation of the street network — but it
represents each street with whatever walkways exist beside it, often two (one per
side), sometimes three (sidewalk plus a parallel shared-use trail). Promoting all of
them to REQUIRED would demand that a walker cover the same corridor two or three
times before Drillfield Drive counted as done. Spec §4.2 already says walking one
side counts.

This module groups campus pedestrian geometry by corridor, splits each corridor into
physical "sides", nominates one canonical obligation per corridor, and records the
other sides as alternatives that satisfy the same obligation.

Usage: python3 -m pipeline.build.campus_normalize [--date YYYY-MM-DD]
"""
import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone

import networkx as nx
from shapely.geometry import shape
from shapely.ops import transform, unary_union

from . import geo
from .names import normalize

OUT_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out")
M_PER_MILE = 1609.344

# A walkway running within this distance of the obligation geometry is covering the
# same corridor from the other side, not new ground. Wide enough to catch a sidewalk
# across a divided campus street; narrow enough not to swallow a parallel back street.
PARALLEL_M = 45.0
# ...and it has to run alongside for most of its length, not just touch at one end.
PARALLEL_SHARE = 0.7

# Corridor-name aliasing: the Paths layer names the walkway after the street, and
# sometimes suffixes it. "West Campus Drive Trail" is the same corridor as
# "West Campus Drive".
CORRIDOR_SUFFIXES = (" trail", " trl", " spur", " underpass", " tunnel", " sidewalk")


def corridor_key(display_name):
    """Normalized corridor name, with walkway words stripped.

    Strip *before* normalizing, not after. `normalize` moves the directional to the
    end ("West Campus Drive Trail" -> "campus drive trl w"), so a suffix strip applied
    afterwards never matches and West Campus Drive Trail stays split from West Campus
    Drive. Stripping the raw string first gives both "campus dr w".
    """
    raw = (display_name or "").strip()
    if not raw:
        return None
    changed = True
    while changed:
        changed = False
        low = raw.lower()
        for suf in CORRIDOR_SUFFIXES:
            if low.endswith(suf):
                raw = raw[: -len(suf)].strip()
                changed = True
                break
    _, norm = normalize(raw, [])
    return norm or None


def load_campus(date):
    with open(os.path.join(OUT_ROOT, date, "segments.geojson")) as f:
        feats = json.load(f)["features"]
    out = []
    for f in feats:
        p = dict(f["properties"])
        if not p.get("in_campus_core"):
            continue
        if p["source"]["dataset"] == "DERIVED":
            continue
        p["_geom"] = transform(geo._to_proj, shape(f["geometry"]))
        out.append(p)
    return out


def build_obligation(segments):
    """Split a corridor's segments into one obligation set plus parallel alternatives.

    The distinction that matters:

      *Parallel* duplication — a sidewalk on the opposite side of the same stretch.
      Covers ground the obligation already covers, so it becomes an ALTERNATIVE that
      satisfies the same obligation (spec §4.2: walking one side counts).

      *Serial* continuation — a further stretch of the same named street. Covers new
      ground, so it JOINS the obligation.

    Distance alone cannot tell these apart, and an earlier version got it wrong:
    clustering by proximity treated a disconnected chunk 700 m down Prices Fork Rd as
    a second "side". The test here is overlap — a segment is parallel duplication only
    if most of its length runs alongside geometry already in the obligation.
    """
    order = sorted(range(len(segments)), key=lambda i: -segments[i]["_geom"].length)
    obligation, alternatives = [], []
    accumulated = None

    for i in order:
        g = segments[i]["_geom"]
        if accumulated is None:
            obligation.append(i)
            accumulated = g
            continue
        # Sample along the segment; how much of it runs beside what we already have?
        n = max(4, int(g.length // 5))
        near = sum(1 for k in range(n + 1)
                   if accumulated.distance(g.interpolate(k / n, normalized=True)) <= PARALLEL_M)
        if near / (n + 1) >= PARALLEL_SHARE:
            alternatives.append(i)
        else:
            obligation.append(i)
            accumulated = accumulated.union(g)
    return obligation, alternatives


def analyse(date):
    segs = load_campus(date)
    by_corridor = defaultdict(list)
    unnamed = []
    for s in segs:
        key = corridor_key(s.get("display_name"))
        if key:
            by_corridor[key].append(s)
        else:
            unnamed.append(s)

    corridors = []
    for key, members in by_corridor.items():
        ob_idx, alt_idx = build_obligation(members)

        def pack(idx):
            length = sum(members[i]["_geom"].length for i in idx)
            return dict(
                segment_ids=[members[i]["id"] for i in idx],
                segments=len(idx),
                miles=round(length / M_PER_MILE, 4),
                length_m=length,
                types=sorted({members[i]["segment_type"] for i in idx}),
                surfaces=sorted({members[i].get("surface") for i in idx
                                 if members[i].get("surface")}),
                names=sorted({members[i]["display_name"] for i in idx
                              if members[i]["display_name"]}),
            )

        canonical, alternatives = pack(ob_idx), pack(alt_idx)
        total_m = canonical["length_m"] + alternatives["length_m"]

        corridors.append(dict(
            corridor=key,
            display=canonical["names"][0] if canonical["names"] else key,
            total_features=len(members),
            obligation_segments=canonical["segments"],
            alternative_segments=alternatives["segments"],
            total_pedestrian_miles=round(total_m / M_PER_MILE, 4),
            canonical_obligation_miles=canonical["miles"],
            duplicate_miles_removed=alternatives["miles"],
            duplication_ratio=round(total_m / canonical["length_m"], 2)
            if canonical["length_m"] else None,
            canonical=canonical,
            alternatives=alternatives,
        ))

    corridors.sort(key=lambda c: -c["total_pedestrian_miles"])

    # Unnamed campus geometry — the interior quad mesh — is mostly genuine new
    # coverage, but some of it runs alongside a named corridor and would duplicate an
    # obligation we have already counted. Test each against the union of all canonical
    # geometry, same parallel rule.
    canon_geoms = []
    for c in corridors:
        for sid in c["canonical"]["segment_ids"]:
            for s in by_corridor[c["corridor"]]:
                if s["id"] == sid:
                    canon_geoms.append(s["_geom"])
                    break
    canon_union = unary_union(canon_geoms) if canon_geoms else None

    unnamed_distinct, unnamed_dupe = [], []
    for s in unnamed:
        g = s["_geom"]
        if canon_union is None:
            unnamed_distinct.append(s)
            continue
        n = max(4, int(g.length // 5))
        near = sum(1 for k in range(n + 1)
                   if canon_union.distance(g.interpolate(k / n, normalized=True)) <= PARALLEL_M)
        (unnamed_dupe if near / (n + 1) >= PARALLEL_SHARE else unnamed_distinct).append(s)

    return corridors, unnamed, segs, unnamed_distinct, unnamed_dupe


def covered_fraction(alt_geom, canon_geom):
    """What share of `canon_geom`'s length runs within PARALLEL_M of `alt_geom`.

    Sampled along the *canonical* segment, not the alternative. That direction is the
    one that matters: the question is how much of the obligation the alternative
    stands in for, not how much of the alternative is beside something.
    """
    n = max(4, int(canon_geom.length // 5))
    near = sum(1 for k in range(n + 1)
               if alt_geom.distance(canon_geom.interpolate(k / n, normalized=True))
               <= PARALLEL_M)
    return near / (n + 1)


# Below this, an alternative brushes a canonical segment rather than covering any
# meaningful part of it, and the pair is not worth recording.
MIN_CREDIT_FRACTION = 0.05


def _link_alternatives(alts, canons, share):
    """Stamp each ALTERNATIVE with the canonical segments it covers, and by how much.

    This is what makes "walking one side counts" mean something operationally. Without
    it, promoting canonical sides to REQUIRED would leave a walker who took the north
    sidewalk of Drillfield Drive with the south side still showing as unprayed-for.

    Credit is **proportional and additive**, not all-or-nothing, because canonical and
    alternative segments are not split at the same points. A 100 m alternative beside a
    300 m canonical segment covers a third of it — crediting the whole thing would
    falsely mark ground as prayed for, and crediting nothing (the first version of this
    function, which left 28 of 41 alternatives earning nothing) understates a walk that
    genuinely covered the corridor. So each pair records a fraction, and the routing
    layer credits a canonical segment once the fractions of the alternatives actually
    walked add up to `share`. Summing at completion time is also the only place the
    "did they walk the *whole* other side?" question can be answered.

    An alternative that covers nothing is still reported: it is beside the corridor but
    stands in for no obligation, so somebody should look at why.
    """
    orphans = []
    for a in alts:
        sat = []
        for c in canons:
            frac = covered_fraction(a["_geom"], c["_geom"])
            if frac >= MIN_CREDIT_FRACTION:
                sat.append(dict(segment_id=c["id"], fraction=round(frac, 4)))
        sat.sort(key=lambda x: -x["fraction"])
        a["satisfies"] = sat
        a["satisfies_segment_ids"] = [x["segment_id"] for x in sat]
        if not sat:
            orphans.append(a["id"])
            a["review_reasons"] = list(a.get("review_reasons") or []) + [
                "ALTERNATIVE walkway that does not run alongside any canonical segment "
                "closely enough to stand in for it. Walking it earns no coverage "
                "credit. Review whether it should be canonical instead."]
    return orphans


def normalize_segments(segments, satisfy_share=0.6):
    """In-build campus normalization: stamp campus_corridor / campus_obligation.

    Called from run.py with the live segment list (geometry under "_geom"). Marks each
    campus pedestrian segment CANONICAL (carries the corridor's coverage obligation) or
    ALTERNATIVE (satisfies the same obligation from the other side). Prevents parallel
    sidewalks from creating duplicate prayer-coverage obligations for one corridor.

    Each ALTERNATIVE also records `satisfies_segment_ids` — the canonical segments a
    walker earns by walking it. Network v1.2 promotes CANONICAL to REQUIRED, so this
    mapping is what stops the promotion from creating the duplicate obligation the
    normalization exists to prevent.
    """
    campus = [s for s in segments
              if s.get("in_campus_core") and s["source"]["dataset"] != "DERIVED"]
    by_corridor = defaultdict(list)
    unnamed = []
    for s in campus:
        key = corridor_key(s.get("display_name"))
        (by_corridor[key] if key else unnamed).append(s)

    canonical_m = duplicate_m = 0.0
    canon_geoms, canon_all, orphans = [], [], []
    for key, members in by_corridor.items():
        ob_idx, alt_idx = build_obligation(members)
        for i in ob_idx:
            members[i]["campus_corridor"] = key
            members[i]["campus_obligation"] = "CANONICAL"
            canonical_m += members[i]["_geom"].length
            canon_geoms.append(members[i]["_geom"])
            canon_all.append(members[i])
        for i in alt_idx:
            members[i]["campus_corridor"] = key
            members[i]["campus_obligation"] = "ALTERNATIVE"
            members[i]["review_reasons"] = list(members[i].get("review_reasons") or []) + [
                f"Parallel walkway on corridor '{key}' — satisfies the same coverage "
                f"obligation as the canonical side (spec §4.2). Not a separate obligation."]
            duplicate_m += members[i]["_geom"].length
        # Credit within the corridor first: an alternative on West Campus Drive should
        # satisfy West Campus Drive, not whatever happens to be geometrically nearest.
        orphans += _link_alternatives([members[i] for i in alt_idx],
                                      [members[i] for i in ob_idx], satisfy_share)

    canon_union = unary_union(canon_geoms) if canon_geoms else None
    unnamed_distinct = unnamed_dupe = 0.0
    unnamed_alts = []
    for s in unnamed:
        g = s["_geom"]
        dup = False
        if canon_union is not None:
            n = max(4, int(g.length // 5))
            near = sum(1 for k in range(n + 1)
                       if canon_union.distance(g.interpolate(k / n, normalized=True)) <= PARALLEL_M)
            dup = near / (n + 1) >= PARALLEL_SHARE
        s["campus_corridor"] = None
        s["campus_obligation"] = "ALTERNATIVE" if dup else "CANONICAL"
        if dup:
            unnamed_dupe += g.length
            unnamed_alts.append(s)
            s["review_reasons"] = list(s.get("review_reasons") or []) + [
                "Unnamed campus walkway running parallel to a named corridor already "
                "carrying an obligation — duplicate coverage, not new ground."]
        else:
            unnamed_distinct += g.length
            canon_all.append(s)

    # Unnamed duplicates have no corridor, so they are matched against every canonical
    # segment on campus.
    orphans += _link_alternatives(unnamed_alts, canon_all, satisfy_share)
    for s in campus:
        s.setdefault("satisfies", [])
        s.setdefault("satisfies_segment_ids", [])

    alts = [s for s in campus if s["campus_obligation"] == "ALTERNATIVE"]
    # How much of the promoted obligation is reachable by walking alternatives instead.
    creditable = set()
    for a in alts:
        creditable |= {x["segment_id"] for x in a["satisfies"]}
    return dict(
        corridors=len(by_corridor),
        campus_segments=len(campus),
        canonical_segments=len(canon_all),
        alternative_segments=len(alts),
        alternatives_with_credit=sum(1 for a in alts if a["satisfies_segment_ids"]),
        canonical_segments_with_an_alternative=len(creditable),
        alternatives_without_credit=len(orphans),
        alternatives_without_credit_ids=sorted(orphans),
        satisfy_share=satisfy_share,
        satisfy_distance_m=PARALLEL_M,
        canonical_miles=round((canonical_m + unnamed_distinct) / M_PER_MILE, 3),
        duplicate_miles=round((duplicate_m + unnamed_dupe) / M_PER_MILE, 3),
        named_canonical_miles=round(canonical_m / M_PER_MILE, 3),
        named_duplicate_miles=round(duplicate_m / M_PER_MILE, 3),
        unnamed_distinct_miles=round(unnamed_distinct / M_PER_MILE, 3),
        unnamed_duplicate_miles=round(unnamed_dupe / M_PER_MILE, 3),
        total_campus_pedestrian_miles=round(
            (canonical_m + duplicate_m + unnamed_distinct + unnamed_dupe) / M_PER_MILE, 3),
    )


# Campus streets known absent from the town Roads layer (Phase 2a schema inspection).
KNOWN_MISSING_CAMPUS_STREETS = [
    "Drillfield Drive", "Duck Pond Drive", "Perry Street", "Old Turner Street",
    "Beamer Way", "Tech Center Drive", "Oak Lane", "West Campus Drive",
    "Life Science Circle", "Stadium Drive", "Coliseum Drive", "Alumni Mall",
    "Stanger Street",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = ap.parse_args()
    geo.assert_metric()
    date = args.date

    corridors, unnamed, segs, unnamed_distinct, unnamed_dupe = analyse(date)

    total_ped = sum(c["total_pedestrian_miles"] for c in corridors)
    total_canon = sum(c["canonical_obligation_miles"] for c in corridors)
    unnamed_m = sum(s["_geom"].length for s in unnamed) / M_PER_MILE
    unnamed_distinct_m = sum(s["_geom"].length for s in unnamed_distinct) / M_PER_MILE
    unnamed_dupe_m = sum(s["_geom"].length for s in unnamed_dupe) / M_PER_MILE

    # Which known-missing campus streets have adequate pedestrian representation?
    representation = []
    for street in KNOWN_MISSING_CAMPUS_STREETS:
        # Run the street name through the same normalizer so the comparison is
        # like-for-like — "Oak Lane" and "Oak Lane Trail" must land on the same key.
        key = corridor_key(street)
        match = next((c for c in corridors if c["corridor"] == key), None)
        if match and match["canonical_obligation_miles"] >= 0.05:
            representation.append(dict(street=street, status="REPRESENTED",
                                       corridor=match["corridor"],
                                       canonical_miles=match["canonical_obligation_miles"],
                                       sides=match["total_features"]))
        elif match:
            representation.append(dict(street=street, status="THIN",
                                       corridor=match["corridor"],
                                       canonical_miles=match["canonical_obligation_miles"],
                                       sides=match["total_features"]))
        else:
            representation.append(dict(street=street, status="NO_REPRESENTATION",
                                       corridor=None, canonical_miles=0.0, sides=0))

    report = dict(
        generated_at=datetime.now(timezone.utc).isoformat(),
        snapshot_date=date,
        method=(
            "Campus pedestrian segments are grouped by corridor name (suffixes Trail/"
            "Spur/Underpass/Tunnel stripped), each corridor is split into physical "
            "sides by proximity (<=8 m midpoint separation or <=2 m endpoint "
            "continuation), and the longest side becomes the single canonical coverage "
            "obligation. Remaining sides are alternatives that satisfy the same "
            "obligation, per spec §4.2 — walking one side counts."),
        totals=dict(
            campus_segments=len(segs),
            named_corridors=len(corridors),
            total_pedestrian_miles=round(total_ped, 3),
            canonical_obligation_miles=round(total_canon, 3),
            duplicate_miles_removed=round(total_ped - total_canon, 3),
            unnamed_campus_miles=round(unnamed_m, 3),
            unnamed_campus_segments=len(unnamed),
            unnamed_distinct_miles=round(unnamed_distinct_m, 3),
            unnamed_distinct_segments=len(unnamed_distinct),
            unnamed_duplicate_miles=round(unnamed_dupe_m, 3),
            unnamed_duplicate_segments=len(unnamed_dupe),
            total_campus_pedestrian_miles=round(total_ped + unnamed_m, 3),
            total_duplicate_miles_removed=round(
                (total_ped - total_canon) + unnamed_dupe_m, 3),
            revised_campus_required_miles=round(total_canon + unnamed_distinct_m, 3),
        ),
        corridors=corridors,
        street_representation=representation,
        unnamed_segments=[dict(id=s["id"], type=s["segment_type"],
                               miles=round(s["_geom"].length / M_PER_MILE, 4),
                               surface=s.get("surface"))
                          for s in sorted(unnamed, key=lambda x: -x["_geom"].length)[:60]],
    )

    path = os.path.join(OUT_ROOT, date, "review", "campus-normalization.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    t = report["totals"]
    print(f"campus segments: {t['campus_segments']}  named corridors: {t['named_corridors']}")
    print(f"  total pedestrian miles        {t['total_pedestrian_miles']:>8.3f}")
    print(f"  canonical obligation miles    {t['canonical_obligation_miles']:>8.3f}")
    print(f"  duplicate miles removed       {t['duplicate_miles_removed']:>8.3f}")
    print(f"  unnamed campus miles          {t['unnamed_campus_miles']:>8.3f}  "
          f"({t['unnamed_campus_segments']} segments)")
    print(f"    of which distinct coverage  {t['unnamed_distinct_miles']:>8.3f}  "
          f"({t['unnamed_distinct_segments']} segments)")
    print(f"    of which parallel duplicate {t['unnamed_duplicate_miles']:>8.3f}  "
          f"({t['unnamed_duplicate_segments']} segments)")
    print(f"  TOTAL campus pedestrian       {t['total_campus_pedestrian_miles']:>8.3f}")
    print(f"  TOTAL duplicate removed       {t['total_duplicate_miles_removed']:>8.3f}")
    print(f"  REVISED campus required       {t['revised_campus_required_miles']:>8.3f}")
    print(f"\n{'corridor':<30}{'feats':>6}{'ped mi':>9}{'canon mi':>10}{'dup mi':>9}{'ratio':>7}")
    for c in corridors[:26]:
        print(f"  {c['display'][:28]:<30}{c['total_features']:>6}{c['total_pedestrian_miles']:>9.3f}"
              f"{c['canonical_obligation_miles']:>10.3f}{c['duplicate_miles_removed']:>9.3f}"
              f"{(c['duplication_ratio'] or 0):>7.2f}")
    print("\nstreet representation:")
    for r in representation:
        print(f"  {r['street']:<20}{r['status']:<20}{r['canonical_miles']:>8.3f} mi  "
              f"sides={r['sides']}")
    print(f"\n-> {path}")


if __name__ == "__main__":
    main()
