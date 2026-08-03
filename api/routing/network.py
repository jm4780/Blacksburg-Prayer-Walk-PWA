"""The frozen canonical network and the routing graph built from it.

The routing engine always knows which network version it is operating against. A
network is identified by a content checksum over the segment records that matter to
routing, so a silently-changed network produces a different id and every stored route
becomes traceable to the network it was computed on.

This module only reads the canonical network. Changing it is a pipeline change plus a
version bump, never an edit here.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_ROOT = os.path.join(REPO, "pipeline", "out")
M_PER_MILE = 1609.344

#   1.3  Phase 3.5: neighbourhood names carried on every segment, from the Town's own
#        NbrhdCom_L/R fields. A label for mission descriptions, never a routing input —
#        the router still works on segments, clusters and completion state.
#   1.2  Phase 3: campus canonical corridors promoted REQUIRED (D1b) with parallel
#        walkways crediting them instead of duplicating the obligation; Deerfield and
#        Shenandoah trails PROVISIONAL -> CONFIRMED; CRC crossings catalogued for
#        review and still held out of the graph; Smart Road still EXCLUDED.
#   1.1  Phase 2b.1: Smart Road reclassified REQUIRED -> EXCLUDED.
#   1.0  Phase 2a.1 candidate freeze.
NETWORK_VERSION = "1.3"

# --- routing-graph membership (Phase 2b Step 2) -----------------------------
#
# In:  REQUIRED segments
#      APPROVED connector segments
#      HIGH_CONFIDENCE derived connectors
# Out: CROSSING_REVIEW_REQUIRED / LIKELY_FALSE / UNRESOLVED derived connectors
#
# "APPROVED connector" needs a definition, because no human connector-approval pass
# has run yet. Here it means: role=OPTIONAL_CONNECTOR, walkable, from an authoritative
# source (not DERIVED). The three exclusions named in the brief are all derived-
# connector classes, so this reading is the one that satisfies the brief without
# emptying the pedestrian network — 650 of 1,023 connectors are NEEDS_REVIEW purely
# because nobody has catalogued them yet, and dropping them would fragment the graph.
#
# When a human connector-approval pass does run, tighten this to an explicit allow
# list and re-freeze. Flagged as a known limitation.
def in_routing_graph(p: dict) -> tuple[bool, str]:
    # Derived connectors are tested first so the exclusion reason names the class that
    # caused it. The build sets walkable=false on rejected connectors, which would
    # otherwise swallow them into a generic "not walkable" bucket.
    if p["source"]["dataset"] == "DERIVED":
        cls = p.get("connector_class")
        if cls != "HIGH_CONFIDENCE":
            return False, f"derived connector: {cls}"
        return True, "HIGH_CONFIDENCE derived connector"
    role = p.get("role")
    if role == "EXCLUDED":
        return False, "EXCLUDED (private / ramp / bypass)"
    if not p.get("walkable"):
        return False, "not walkable"
    if role == "REQUIRED":
        return True, "REQUIRED"
    if role == "OPTIONAL_CONNECTOR":
        return True, "approved connector (authoritative source, walkable)"
    return False, f"role {role}"


@dataclass
class Segment:
    id: str
    idx: int
    u: int
    v: int
    length_m: float
    role: str
    segment_type: str
    display_name: str | None
    normalized_name: str | None
    households: int
    is_dead_end: bool
    walk_stress: int
    access_type: str | None
    campus_obligation: str | None
    campus_corridor: str | None
    connector_class: str | None
    # Town neighbourhood this segment sits in. Presentation only — see
    # pipeline/build/neighborhoods.py and docs/17 §7.
    neighborhood: str | None
    is_derived: bool
    coords: list  # WGS84 [[lon,lat],...] for visualisation only
    # [(canonical segment id, fraction of it this walkway runs alongside)]. Non-empty
    # only on campus ALTERNATIVE walkways. See `credited()`.
    satisfies: list = field(default_factory=list)

    @property
    def miles(self) -> float:
        return self.length_m / M_PER_MILE

    @property
    def required(self) -> bool:
        return self.role == "REQUIRED"


@dataclass
class Network:
    version: str
    network_id: str
    snapshot_date: str
    built_at: str
    frozen_at: str
    segments: list                      # only those in the routing graph
    excluded: dict                      # reason -> count, for the record
    adjacency: dict                     # node -> [(neighbour, seg_idx)]
    node_count: int
    stats: dict
    source_versions: dict
    # alternative seg idx -> [(canonical seg idx, fraction)]
    alt_credit: dict = field(default_factory=dict)
    satisfy_share: float = 0.6

    # numpy views, built once
    seg_len: np.ndarray = field(default_factory=lambda: np.zeros(0))
    seg_required: np.ndarray = field(default_factory=lambda: np.zeros(0, bool))
    seg_households: np.ndarray = field(default_factory=lambda: np.zeros(0))

    def segment(self, idx: int) -> Segment:
        return self.segments[idx]

    def credited(self, walked: set) -> set:
        """Canonical REQUIRED segments earned by walking parallel campus walkways.

        Spec §4.2: walking one side of a corridor counts. Network v1.2 promotes the
        canonical side of each campus corridor to REQUIRED, so without this a walker
        who took the other sidewalk would be told the corridor is still unprayed-for.

        Credit is additive across the alternatives actually walked, because canonical
        and alternative walkways are not split at the same points — one 100 m walkway
        beside a 300 m canonical segment covers a third of it, and only the union of
        what was walked can answer whether the corridor was really covered. A canonical
        segment is credited once the fractions reach `satisfy_share`.

        Returns only segments NOT in `walked`, so callers can union without care.
        """
        if not self.alt_credit:
            return set()
        acc = defaultdict(float)
        for i in walked:
            for c, f in self.alt_credit.get(i, ()):
                acc[c] += f
        return {c for c, f in acc.items()
                if f >= self.satisfy_share and c not in walked}


def _checksum(rows) -> str:
    """Content hash of everything routing depends on. Order-independent."""
    h = hashlib.sha256()
    for r in sorted(rows):
        h.update(r.encode())
    return h.hexdigest()[:16]


def load(date: str = "2026-08-03", quiet: bool = False) -> Network:
    outdir = os.path.join(OUT_ROOT, date)
    with open(os.path.join(outdir, "segments.geojson")) as f:
        feats = json.load(f)["features"]
    with open(os.path.join(outdir, "build-report.json")) as f:
        report = json.load(f)

    segments, excluded, digest_rows = [], {}, []
    for f_ in feats:
        p = f_["properties"]
        keep, reason = in_routing_graph(p)
        # Everything in the canonical network contributes to the checksum, in or out —
        # a change to an excluded segment is still a change to the network.
        digest_rows.append("|".join(str(x) for x in (
            p["id"], p["role"], p["segment_type"], p.get("connector_class"),
            round(float(p["length_m"]), 3), p["start_node_id"], p["end_node_id"],
            p.get("estimated_household_count") or 0, p.get("campus_obligation"),
            # Coverage credit changes what a route earns, so it is part of the network
            # identity — a re-tuned satisfy threshold must produce a new network id.
            ";".join(f"{x['segment_id']}:{x['fraction']}"
                     for x in (p.get("satisfies") or [])))))
        if not keep:
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        g = f_["geometry"]
        segments.append(Segment(
            id=p["id"], idx=len(segments),
            u=int(p["start_node_id"]), v=int(p["end_node_id"]),
            length_m=float(p["length_m"]), role=p["role"],
            segment_type=p["segment_type"], display_name=p.get("display_name"),
            normalized_name=p.get("normalized_name"),
            households=int(p.get("estimated_household_count") or 0),
            is_dead_end=bool(p.get("is_dead_end")),
            walk_stress=int(p.get("walk_stress") or 2),
            access_type=p.get("access_type"),
            campus_obligation=p.get("campus_obligation"),
            campus_corridor=p.get("campus_corridor"),
            connector_class=p.get("connector_class"),
            neighborhood=p.get("neighborhood"),
            is_derived=p["source"]["dataset"] == "DERIVED",
            coords=g["coordinates"] if g["type"] == "LineString" else [],
            satisfies=list(p.get("satisfies") or []),
        ))

    # Resolve coverage credit from segment ids to routing indices. A credit pointing at
    # a canonical segment that is not in the routing graph is dropped rather than
    # silently kept as a dangling id.
    idx_of_id = {s.id: s.idx for s in segments}
    alt_credit, dangling = {}, 0
    for s in segments:
        pairs = []
        for x in s.satisfies:
            j = idx_of_id.get(x["segment_id"])
            if j is None:
                dangling += 1
                continue
            pairs.append((j, float(x["fraction"])))
        if pairs:
            alt_credit[s.idx] = pairs

    adjacency = {}
    for s in segments:
        adjacency.setdefault(s.u, []).append((s.v, s.idx))
        if s.v != s.u:
            adjacency.setdefault(s.v, []).append((s.u, s.idx))

    req = [s for s in segments if s.required]
    conn = [s for s in segments if s.role == "OPTIONAL_CONNECTOR" and not s.is_derived]
    der = [s for s in segments if s.is_derived]
    campus = [s for s in segments if s.campus_obligation == "CANONICAL"]
    campus_alt = [s for s in segments if s.campus_obligation == "ALTERNATIVE"]
    camp_report = report.get("campus_normalization", {})

    def mi(rows):
        return round(sum(s.length_m for s in rows) / M_PER_MILE, 3)

    totals = report["totals"]
    stats = dict(
        routing_segments=len(segments),
        routing_nodes=len(adjacency),
        required_segments=len(req),
        required_miles=mi(req),
        # Street / trail / campus partition required_miles exactly. Campus is taken
        # first, by obligation rather than by segment_type: 4.471 mi of the campus
        # obligation is typed TRAIL in the Paths layer, so splitting on type alone
        # reported it under both trail and campus and the three did not sum.
        required_street_miles=mi([s for s in req if s.segment_type == "STREET"
                                  and s.campus_obligation != "CANONICAL"]),
        required_trail_miles=mi([s for s in req if s.segment_type == "TRAIL"
                                 and s.campus_obligation != "CANONICAL"]),
        required_campus_miles=mi([s for s in req
                                  if s.campus_obligation == "CANONICAL"]),
        connector_segments=len(conn),
        connector_miles=mi(conn),
        derived_connector_segments=len(der),
        derived_connector_miles=mi(der),
        campus_corridor_miles=mi(campus),
        campus_alternative_miles=mi(campus_alt),
        campus_duplicate_obligation_miles_avoided=camp_report.get("duplicate_miles", 0.0),
        campus_alternatives_with_credit=len(alt_credit),
        campus_credit_links_dropped=dangling,
        routable_miles=mi(segments),
        neighborhoods=sorted({s.neighborhood for s in req if s.neighborhood}),
        # From the canonical build, for the record — excluded mileage is not routable.
        excluded_miles=totals["EXCLUDED"]["miles"],
        canonical_total_miles=totals["ALL"]["miles"],
        households_on_required=report["households"]["units_associated_to_required_coverage"],
        households_held=report["households"]["units_held_for_review"],
        households_on_segments_in_graph=sum(s.households for s in segments),
    )

    net = Network(
        version=NETWORK_VERSION,
        network_id=f"bbg-net-v{NETWORK_VERSION}-{_checksum(digest_rows)}",
        snapshot_date=report["snapshot_date"],
        built_at=report["built_at"],
        frozen_at=datetime.now(timezone.utc).isoformat(),
        segments=segments, excluded=excluded, adjacency=adjacency,
        node_count=len(adjacency), stats=stats,
        alt_credit=alt_credit,
        satisfy_share=float(camp_report.get("satisfy_share", 0.6)),
        source_versions={k: dict(url=v["source_url"],
                                 source_updated_at=v["source_updated_at"],
                                 retrieved_at=v["retrieved_at"],
                                 feature_count=v["feature_count"],
                                 license_status=v["license_status"])
                         for k, v in report["sources"].items()},
    )
    net.seg_len = np.array([s.length_m for s in segments], dtype=float)
    net.seg_required = np.array([s.required for s in segments], dtype=bool)
    net.seg_households = np.array([s.households for s in segments], dtype=float)

    if not quiet:
        print(f"network {net.network_id}  ({len(segments)} routable segments, "
              f"{net.node_count} nodes, {stats['required_miles']} required mi)")
    return net


def freeze_manifest(net: Network) -> dict:
    return {
        "canonical_network_version": f"v{net.version}",
        "network_id": net.network_id,
        "build_date": net.built_at,
        "snapshot_date": net.snapshot_date,
        "frozen_at": net.frozen_at,
        "checksum_algorithm": "sha256 over (id, role, type, connector_class, length, "
                              "nodes, households, campus_obligation) for every canonical "
                              "segment, sorted; first 16 hex chars",
        "source_versions": net.source_versions,
        "mileage": {
            "required_total": net.stats["required_miles"],
            "required_street": net.stats["required_street_miles"],
            "required_trail": net.stats["required_trail_miles"],
            "required_campus": net.stats["required_campus_miles"],
            "connector": net.stats["connector_miles"],
            "derived_connector": net.stats["derived_connector_miles"],
            "excluded": net.stats["excluded_miles"],
            "campus_corridor": net.stats["campus_corridor_miles"],
            "campus_alternative": net.stats["campus_alternative_miles"],
            "routable_total": net.stats["routable_miles"],
            "canonical_total": net.stats["canonical_total_miles"],
        },
        "campus_obligation": {
            "canonical_miles": net.stats["campus_corridor_miles"],
            "alternative_miles": net.stats["campus_alternative_miles"],
            "duplicate_obligation_miles_avoided":
                net.stats["campus_duplicate_obligation_miles_avoided"],
            "alternatives_crediting_a_canonical_side":
                net.stats["campus_alternatives_with_credit"],
            "credit_links_dropped_as_dangling": net.stats["campus_credit_links_dropped"],
            "satisfy_share": net.satisfy_share,
            "rule": ("Walking a parallel campus walkway credits the canonical segments "
                     "it runs alongside, additively, once the covered fractions reach "
                     "satisfy_share. One obligation per corridor (spec §4.2)."),
        },
        "neighborhoods": net.stats["neighborhoods"],
        "counts": {
            "routing_segments": net.stats["routing_segments"],
            "routing_nodes": net.stats["routing_nodes"],
            "required_segments": net.stats["required_segments"],
            "connector_segments": net.stats["connector_segments"],
            "derived_connector_segments": net.stats["derived_connector_segments"],
        },
        "households": {
            "on_required_coverage": net.stats["households_on_required"],
            "held_for_review": net.stats["households_held"],
            "attached_to_segments_in_routing_graph": net.stats["households_on_segments_in_graph"],
        },
        "excluded_from_routing_graph": net.excluded,
        "routing_graph_membership_rule": {
            "include": ["REQUIRED", "approved connector (authoritative source, walkable)",
                        "HIGH_CONFIDENCE derived connector"],
            "exclude": ["EXCLUDED", "CROSSING_REVIEW_REQUIRED derived",
                        "LIKELY_FALSE derived", "UNRESOLVED derived", "not walkable"],
        },
    }
