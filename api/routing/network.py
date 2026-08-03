"""Frozen canonical network v1.0 and the routing graph built from it.

The routing engine always knows which network version it is operating against. A
network is identified by a content checksum over the segment records that matter to
routing, so a silently-changed network produces a different id and every stored route
becomes traceable to the network it was computed on.

Phase 2b does not modify the canonical network. This module only reads it.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_ROOT = os.path.join(REPO, "pipeline", "out")
M_PER_MILE = 1609.344

NETWORK_VERSION = "1.1"

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
    is_derived: bool
    coords: list  # WGS84 [[lon,lat],...] for visualisation only

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

    # numpy views, built once
    seg_len: np.ndarray = field(default_factory=lambda: np.zeros(0))
    seg_required: np.ndarray = field(default_factory=lambda: np.zeros(0, bool))
    seg_households: np.ndarray = field(default_factory=lambda: np.zeros(0))

    def segment(self, idx: int) -> Segment:
        return self.segments[idx]


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
            p.get("estimated_household_count") or 0, p.get("campus_obligation"))))
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
            is_derived=p["source"]["dataset"] == "DERIVED",
            coords=g["coordinates"] if g["type"] == "LineString" else [],
        ))

    adjacency = {}
    for s in segments:
        adjacency.setdefault(s.u, []).append((s.v, s.idx))
        if s.v != s.u:
            adjacency.setdefault(s.v, []).append((s.u, s.idx))

    req = [s for s in segments if s.required]
    conn = [s for s in segments if s.role == "OPTIONAL_CONNECTOR" and not s.is_derived]
    der = [s for s in segments if s.is_derived]
    campus = [s for s in segments if s.campus_obligation == "CANONICAL"]

    def mi(rows):
        return round(sum(s.length_m for s in rows) / M_PER_MILE, 3)

    totals = report["totals"]
    stats = dict(
        routing_segments=len(segments),
        routing_nodes=len(adjacency),
        required_segments=len(req),
        required_miles=mi(req),
        required_street_miles=mi([s for s in req if s.segment_type == "STREET"]),
        required_trail_miles=mi([s for s in req if s.segment_type == "TRAIL"]),
        connector_segments=len(conn),
        connector_miles=mi(conn),
        derived_connector_segments=len(der),
        derived_connector_miles=mi(der),
        campus_corridor_miles=mi(campus),
        routable_miles=mi(segments),
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
            "connector": net.stats["connector_miles"],
            "derived_connector": net.stats["derived_connector_miles"],
            "excluded": net.stats["excluded_miles"],
            "campus_corridor": net.stats["campus_corridor_miles"],
            "routable_total": net.stats["routable_miles"],
            "canonical_total": net.stats["canonical_total_miles"],
        },
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
