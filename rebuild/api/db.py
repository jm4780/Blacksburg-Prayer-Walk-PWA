"""Database access. One place that knows how to talk to Postgres."""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row

DSN = os.environ.get(
    "BPW_DSN",
    "postgresql://postgres@localhost:5432/bbg",
)


@contextmanager
def conn() -> Iterator[psycopg.Connection]:
    with psycopg.connect(DSN, row_factory=dict_row) as c:
        yield c


# --------------------------------------------------------------------------
# the network. Immutable *within* a build, so it is read once and kept.
#
# Across a build it is not immutable at all, and seg_ids do not survive one.
# A cache with no way to notice a rebuild will happily serve last week's
# street ids to a phone while /api/progress counts this week's, so the cache
# carries a fingerprint and rechecks it against the database on a short timer.
# The check is one aggregate query and costs about a millisecond.
# --------------------------------------------------------------------------

_network_cache: list[dict[str, Any]] | None = None
_network_fingerprint: tuple[int, float] | None = None
_network_checked_at: float = 0.0
#: Bumped every time the network is actually reloaded, so callers holding a
#: derived copy (the serialised /api/network body) know to rebuild it.
network_version: int = 0

RECHECK_SECONDS = 20.0


def _fingerprint(c: psycopg.Connection) -> tuple[int, float]:
    row = c.execute(
        "select count(*) as n, coalesce(sum(length_m), 0) as m from segment"
    ).fetchone()
    assert row is not None
    return (int(row["n"]), round(float(row["m"]), 3))


def load_network(force: bool = False) -> list[dict[str, Any]]:
    """Every segment, with geometry, as plain dicts.

    Shape matches contract section 1 exactly, plus `geometry` as GeoJSON.
    This is the object handed to the coverage and route engines.
    """
    global _network_cache, _network_fingerprint, _network_checked_at, network_version

    now = time.monotonic()
    if _network_cache is not None and not force and now - _network_checked_at < RECHECK_SECONDS:
        return _network_cache

    with conn() as c:
        fingerprint = _fingerprint(c)
        _network_checked_at = now
        if _network_cache is not None and fingerprint == _network_fingerprint and not force:
            return _network_cache

        rows = c.execute(
            """
            select seg_id, name, ref, class, length_m, node_a, node_b, homes,
                   st_asgeojson(geom)::json as geometry
            from segment
            order by seg_id
            """
        ).fetchall()

    for r in rows:
        # Convenience for engines that would rather not unwrap GeoJSON.
        r["coords"] = r["geometry"]["coordinates"]
    _network_cache = rows
    _network_fingerprint = fingerprint
    network_version += 1
    return _network_cache


def covered_ids() -> list[int]:
    with conn() as c:
        rows = c.execute("select seg_id from coverage order by seg_id").fetchall()
    return [r["seg_id"] for r in rows]


def progress() -> dict[str, Any]:
    with conn() as c:
        row = c.execute("select * from progress").fetchone()
    assert row is not None

    total_m = float(row["total_m"] or 0.0)
    covered_m = float(row["covered_m"] or 0.0)

    # Homes are null on purpose until a real address source exists. If the town
    # total is unknown, the covered figure is meaningless, so both stay null and
    # the interface renders no home line at all. Contract section 6.
    homes_total = row["homes_total"]
    homes_covered = row["homes_covered"] if homes_total is not None else None

    return {
        "segments_covered": int(row["segments_covered"]),
        "segments_total": int(row["segments_total"]),
        "covered_m": covered_m,
        "total_m": total_m,
        "percent": round(100.0 * covered_m / total_m, 2) if total_m else 0.0,
        "homes_covered": homes_covered,
        "homes_total": homes_total,
    }


def commit_walk(
    device_id: str,
    client_walk_id: str,
    display_name: str | None,
    started_at: str | None,
    seg_ids: list[int],
) -> tuple[str, list[int]]:
    """Commit a confirmed walk. Idempotent on (device_id, client_walk_id).

    Returns (walk_id, newly_covered). `newly_covered` is the set of segments
    this walk was the first to claim, which on a replay is empty.
    """
    with conn() as c:
        with c.transaction():
            before = {
                r["seg_id"]
                for r in c.execute(
                    "select seg_id from coverage where seg_id = any(%s)", (seg_ids,)
                ).fetchall()
            }
            row = c.execute(
                "select commit_walk(%s, %s, %s, %s, %s) as walk_id",
                (device_id, client_walk_id, display_name, started_at, seg_ids),
            ).fetchone()
            assert row is not None
            walk_id = str(row["walk_id"])
            after = {
                r["seg_id"]
                for r in c.execute(
                    "select seg_id from coverage where seg_id = any(%s) and first_walk_id = %s",
                    (seg_ids, walk_id),
                ).fetchall()
            }
    return walk_id, sorted(after - before)


def json_dumps(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"))
