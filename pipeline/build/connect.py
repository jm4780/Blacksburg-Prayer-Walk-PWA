"""The connect stage: stitch the pedestrian layer onto the street network.

Paths to the Future and Roads were digitised independently. Sidewalk and trail
geometry sits offset from road centerlines, so the two layers share no nodes and the
pedestrian network floats free of the streets — a router could never step from a
street onto the Huckleberry Trail.

This stage finds components that are disconnected from the main network and adds
short synthetic connector edges to the nearest reachable geometry. Every connector is
derived, not observed, so each one is emitted with source.dataset="DERIVED" and
role_status=NEEDS_REVIEW. A human confirms that the crossing it implies is real.
"""
from collections import defaultdict

import networkx as nx
from shapely.geometry import LineString
from shapely.ops import nearest_points
from shapely.strtree import STRtree

# How far a synthetic connector may reach. Beyond this the gap is a genuine missing
# link in the source data, not a digitising offset, and inventing an edge would be
# asserting a crossing that may not exist.
MAX_CONNECTOR_M = 25.0
# Below this the endpoints should have been snapped together during noding already.
MIN_CONNECTOR_M = 0.2


def components(pieces, node_ids):
    G = nx.Graph()
    for i, (a, b) in enumerate(node_ids):
        G.add_edge(a, b, idx=i)
    comps = sorted(nx.connected_components(G), key=len, reverse=True)
    node_comp = {}
    for ci, comp in enumerate(comps):
        for n in comp:
            node_comp[n] = ci
    return comps, node_comp


def propose(pieces, node_ids, node_points):
    """Return (connector_lines, stats).

    connector_lines is [(LineString, info_dict)] — short edges joining a stranded
    component to something in a larger one.
    """
    comps, node_comp = components(pieces, node_ids)
    if len(comps) <= 1:
        return [], {"components_before": len(comps), "connectors": 0}

    geoms = [g for _, g in pieces]
    tree = STRtree(geoms)
    piece_comp = [node_comp[a] for a, _ in node_ids]

    # Endpoint nodes of each stranded component, ordered so the largest strays first.
    nodes_by_comp = defaultdict(list)
    for i, (a, b) in enumerate(node_ids):
        nodes_by_comp[piece_comp[i]].extend([a, b])

    connectors, joined, skipped = [], set(), []
    for ci in range(1, len(comps)):
        best = None
        for n in set(nodes_by_comp[ci]):
            p = node_points[n]
            for idx in tree.query(p.buffer(MAX_CONNECTOR_M)):
                if piece_comp[idx] == ci:
                    continue
                # Only connect to something in a strictly larger component, so two
                # stranded fragments cannot pair off and stay stranded together.
                if len(comps[piece_comp[idx]]) <= len(comps[ci]):
                    continue
                target = geoms[idx]
                d = target.distance(p)
                if d < MIN_CONNECTOR_M or d > MAX_CONNECTOR_M:
                    continue
                if best is None or d < best[0]:
                    best = (d, n, idx)
        if best is None:
            skipped.append({"component": ci, "nodes": len(comps[ci]),
                            "reason": f"nothing within {MAX_CONNECTOR_M:.0f} m in a larger component"})
            continue
        d, n, idx = best
        p = node_points[n]
        _, snapped = nearest_points(p, geoms[idx])
        line = LineString([(p.x, p.y), (snapped.x, snapped.y)])
        if line.length < MIN_CONNECTOR_M:
            continue
        src_attrs = pieces[[i for i, c in enumerate(piece_comp) if c == ci][0]][0]
        connectors.append((line, {
            "length_m": round(line.length, 2),
            "from_component_size": len(comps[ci]),
            "joined_to_dataset": pieces[idx][0].get("__src"),
            "joined_to_name": pieces[idx][0].get("LABEL") or pieces[idx][0].get("Road"),
            "stranded_source": src_attrs.get("__src"),
            "stranded_name": src_attrs.get("LABEL") or src_attrs.get("Road"),
        }))
        joined.add(ci)

    return connectors, {
        "components_before": len(comps),
        "connectors": len(connectors),
        "components_joined": len(joined),
        "components_unreachable": len(skipped),
        "unreachable": skipped[:200],
    }


def as_features(connectors, offset=0):
    """Wrap connector lines as pipeline features with a DERIVED source tag."""
    out = []
    for i, (line, info) in enumerate(connectors, start=offset + 1):
        attrs = {
            "__src": "derived",
            "__derived_kind": "network_stitch",
            "__derived_info": info,
            "OBJECTID": f"CONN-{i:05d}",
            "GlobalID": None,
            "Road": None,
            "Type": "Connector",
        }
        out.append((attrs, line))
    return out
