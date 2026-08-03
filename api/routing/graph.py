"""Compact routing graph: CSR arrays, Dijkstra, and anchor distance matrices.

Segment identity is preserved throughout — every edge in the CSR carries the index of
the canonical Segment it came from, so a route can always be reported as a list of
SEG-xxxxxx ids.
"""
from __future__ import annotations

import heapq

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra as sp_dijkstra

from .network import Network


class RoutingGraph:
    """Undirected multigraph over canonical nodes, with parallel-edge support."""

    def __init__(self, net: Network):
        self.net = net
        self.nodes = sorted(net.adjacency)
        self.node_index = {n: i for i, n in enumerate(self.nodes)}
        self.n = len(self.nodes)

        # adjacency[i] -> list of (j, seg_idx, length)
        self.adj: list[list[tuple[int, int, float]]] = [[] for _ in range(self.n)]
        for s in net.segments:
            a, b = self.node_index[s.u], self.node_index[s.v]
            self.adj[a].append((b, s.idx, s.length_m))
            if b != a:
                self.adj[b].append((a, s.idx, s.length_m))

        # SciPy CSR for fast multi-source shortest paths. Parallel edges collapse to
        # the shortest, which is correct for distance queries; routing itself uses
        # self.adj so no edge identity is lost.
        rows, cols, data = [], [], []
        for i in range(self.n):
            for j, _, w in self.adj[i]:
                rows.append(i)
                cols.append(j)
                data.append(w)
        self.csr = csr_matrix((data, (rows, cols)), shape=(self.n, self.n))

        self._dist_cache: dict[int, np.ndarray] = {}
        # Anchor-to-anchor paths are recomputed constantly during local search — the
        # same pairs, over and over. Memoizing turns the improvement layer from the
        # dominant cost into a rounding error.
        self._path_cache: dict[tuple[int, int], tuple[float, list]] = {}

    # ---------------------------------------------------------------- basics
    def idx_of(self, node_id: int) -> int:
        return self.node_index[node_id]

    def dist_from(self, i: int) -> np.ndarray:
        """Shortest-path distance (metres) from node index i to all nodes."""
        d = self._dist_cache.get(i)
        if d is None:
            d = sp_dijkstra(self.csr, directed=False, indices=i)
            self._dist_cache[i] = d
        return d

    def dist_matrix(self, indices: list[int]) -> np.ndarray:
        """|indices| x n distance matrix, computed in C."""
        if not indices:
            return np.zeros((0, self.n))
        return sp_dijkstra(self.csr, directed=False, indices=indices)

    # ------------------------------------------------------------ path recovery
    def shortest_path(self, i: int, j: int) -> tuple[float, list[int]]:
        """Dijkstra with predecessor tracking; returns (length_m, [seg_idx,...]).

        Used for stitching anchors together. Kept in Python because it needs edge
        identity, which SciPy's matrix view discards.
        """
        if i == j:
            return 0.0, []
        key = (i, j)
        hit = self._path_cache.get(key)
        if hit is not None:
            return hit
        dist = {i: 0.0}
        prev: dict[int, tuple[int, int]] = {}
        pq = [(0.0, i)]
        while pq:
            d, u = heapq.heappop(pq)
            if u == j:
                break
            if d > dist.get(u, float("inf")):
                continue
            for v, seg, w in self.adj[u]:
                nd = d + w
                if nd < dist.get(v, float("inf")):
                    dist[v] = nd
                    prev[v] = (u, seg)
                    heapq.heappush(pq, (nd, v))
        if j not in dist:
            self._path_cache[key] = (float("inf"), [])
            return float("inf"), []
        path, cur = [], j
        while cur != i:
            u, seg = prev[cur]
            path.append(seg)
            cur = u
        path.reverse()
        result = (dist[j], path)
        self._path_cache[key] = result
        # The reverse of a shortest path is a shortest path; store it for free.
        self._path_cache[(j, i)] = (dist[j], path[::-1])
        return result

    # --------------------------------------------------------------- components
    def components(self) -> list[list[int]]:
        seen = [False] * self.n
        comps = []
        for start in range(self.n):
            if seen[start]:
                continue
            stack, comp = [start], []
            seen[start] = True
            while stack:
                u = stack.pop()
                comp.append(u)
                for v, _, _ in self.adj[u]:
                    if not seen[v]:
                        seen[v] = True
                        stack.append(v)
            comps.append(comp)
        comps.sort(key=len, reverse=True)
        return comps

    def nearest_node_to(self, lon: float, lat: float,
                        restrict_to: set | None = None) -> int:
        """Nearest graph node to a WGS84 point, by planar distance.

        `restrict_to` is a set of node *indices* — normally the main routing component.
        Without it the naive nearest node can land on one of the 117 small stranded
        fragments, from which no useful route exists. A walker standing downtown is on
        the real network; snap them to it.
        """
        best, best_d = None, float("inf")
        for s in self.net.segments:
            if not s.coords:
                continue
            for node, pt in ((s.u, s.coords[0]), (s.v, s.coords[-1])):
                ni = self.node_index.get(node)
                if ni is None or (restrict_to is not None and ni not in restrict_to):
                    continue
                dx = (pt[0] - lon) * 0.79  # cos(37.23 deg)
                dy = pt[1] - lat
                d = dx * dx + dy * dy
                if d < best_d:
                    best_d, best = d, ni
        if best is None:
            raise ValueError("no graph node available for that location")
        return best
