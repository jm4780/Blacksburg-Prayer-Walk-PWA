"""Database access. One place that knows how to talk to Postgres."""

from __future__ import annotations

import json
import os
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
# the network. Immutable between builds, so it is read once and kept.
# --------------------------------------------------------------------------

_network_cache: list[dict[str, Any]] | None = None


def load_network(force: bool = False) -> list[dict[str, Any]]:
    """Every segment, with geometry, as plain dicts.

    Shape matches contract section 1 exactly, plus `geometry` as GeoJSON.
    This is the object handed to the coverage and route engines.
    """
    global _network_cache
    if _network_cache is not None and not force:
        return _network_cache

    with conn() as c:
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
