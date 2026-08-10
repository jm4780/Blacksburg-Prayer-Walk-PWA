"""Render a route against the real Blacksburg street network, for human inspection.

The final check on this app is not a unit test. It is a person looking at five
generated routes on the real map and answering one question each: would someone
following this get lost, get confused, or end up somewhere unsafe?

This draws that picture. Real segment geometry, real street names, the town
boundary, and the route in walking order with its start marked, so the question
can actually be answered rather than guessed at.

Palette matches the app's tokens: near-black ground, network in restrained
greys, colour spent only on the route and the start.

    python3 rebuild/tests/render_route.py
"""
from __future__ import annotations

import json
import math
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
NETWORK = os.path.join(REPO, "rebuild", "data", "out", "network.geojson")
LIMITS = os.path.join(REPO, "pipeline", "basemap", "blacksburg-limits.json")
OUTDIR = os.path.join(REPO, "rebuild", "data", "out", "routes")

# Design tokens, kept in step with the web app's token file.
INK = "#0a0b0d"          # ground
NET_FAR = "#1e2126"      # streets outside the frame of interest
NET_NEAR = "#31363d"     # streets in view
BOUNDARY = "#3a4048"     # town limit
ROUTE = "#f0b429"        # the active route: the one thing that must be followed
START = "#e8eaed"        # where you begin and end
LABEL = "#8b929c"


def load_network() -> dict:
    with open(NETWORK) as fh:
        fc = json.load(fh)
    return {f["properties"]["seg_id"]: f for f in fc["features"]}


def load_limits():
    return json.load(open(LIMITS))["coordinates"][0]


def _aspect(lat: float) -> float:
    """Degrees of longitude are shorter than degrees of latitude. Correct for it."""
    return 1.0 / math.cos(math.radians(lat))


def render(
    seg_ids: list[int],
    title: str,
    path: str,
    *,
    network: dict | None = None,
    pad: float = 0.004,
):
    """Draw `seg_ids` in walking order over the whole network."""
    network = network or load_network()
    route = [network[s] for s in seg_ids if s in network]
    if not route:
        raise ValueError("no known segments in route")

    xs, ys = [], []
    for f in route:
        for x, y in f["geometry"]["coordinates"]:
            xs.append(x)
            ys.append(y)
    x0, x1 = min(xs) - pad, max(xs) + pad
    y0, y1 = min(ys) - pad, max(ys) + pad
    midlat = (y0 + y1) / 2

    fig, ax = plt.subplots(figsize=(11, 11), dpi=110)
    fig.patch.set_facecolor(INK)
    ax.set_facecolor(INK)

    lim = load_limits()
    ax.plot([p[0] for p in lim], [p[1] for p in lim], color=BOUNDARY, lw=0.9, zorder=1)

    # The whole network, dimmer outside the view than inside it, so the route
    # reads as part of a town rather than floating in nothing.
    for f in network.values():
        c = f["geometry"]["coordinates"]
        inview = any(x0 <= x <= x1 and y0 <= y <= y1 for x, y in c)
        ax.plot(
            [p[0] for p in c],
            [p[1] for p in c],
            color=NET_NEAR if inview else NET_FAR,
            lw=1.0 if inview else 0.6,
            solid_capstyle="round",
            zorder=2,
        )

    # The route, in walking order.
    for f in route:
        c = f["geometry"]["coordinates"]
        ax.plot(
            [p[0] for p in c],
            [p[1] for p in c],
            color=ROUTE,
            lw=3.4,
            solid_capstyle="round",
            zorder=4,
        )

    # Street names, once per street, placed at the midpoint of its longest run.
    seen: dict[str, tuple] = {}
    for f in route:
        n = f["properties"]["name"]
        if n and (n not in seen or f["properties"]["length_m"] > seen[n][0]):
            c = f["geometry"]["coordinates"]
            seen[n] = (f["properties"]["length_m"], c[len(c) // 2])
    for n, (_, pt) in seen.items():
        ax.annotate(
            n,
            pt,
            color=LABEL,
            fontsize=7.5,
            ha="center",
            va="center",
            zorder=6,
            bbox=dict(boxstyle="round,pad=0.18", fc=INK, ec="none", alpha=0.82),
        )

    sx, sy = route[0]["geometry"]["coordinates"][0]
    ex, ey = route[-1]["geometry"]["coordinates"][-1]
    ax.plot([sx], [sy], "o", ms=13, mfc=START, mec=INK, mew=2.0, zorder=8)
    ax.plot([ex], [ey], "o", ms=8, mfc="none", mec=START, mew=1.8, zorder=8)

    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect(_aspect(midlat))
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title(title, color="#e8eaed", fontsize=12, pad=14, loc="left")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    fig.savefig(path, facecolor=INK, bbox_inches="tight")
    plt.close(fig)
    return path


def _demo_chain(network: dict, start_seg: int, n: int) -> list[int]:
    """Walk the adjacency graph greedily. Only used to exercise the renderer."""
    adj: dict[str, list[int]] = {}
    for sid, f in network.items():
        p = f["properties"]
        adj.setdefault(p["node_a"], []).append(sid)
        adj.setdefault(p["node_b"], []).append(sid)
    chain, used = [start_seg], {start_seg}
    node = network[start_seg]["properties"]["node_b"]
    while len(chain) < n:
        nxt = next((s for s in adj.get(node, []) if s not in used), None)
        if nxt is None:
            break
        used.add(nxt)
        chain.append(nxt)
        p = network[nxt]["properties"]
        node = p["node_b"] if p["node_a"] == node else p["node_a"]
    return chain


if __name__ == "__main__":
    net = load_network()
    seed = next(
        s for s, f in net.items() if (f["properties"]["name"] or "").startswith("Progress")
    )
    demo = _demo_chain(net, seed, 22)
    out = render(demo, "renderer check: a greedy chain, not a generated route",
                 os.path.join(OUTDIR, "renderer-check.png"), network=net)
    print(f"wrote {out}  ({len(demo)} segments)")
