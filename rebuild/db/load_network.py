"""Apply the schema and load the extracted network into Postgres/PostGIS.

Connects over a DSN like everything else, so it runs as any user on any host.
It used to shell out to `su postgres -c psql`, which works only as root on a
machine where the postgres system account exists, and fails on a Codespace.

    python3 rebuild/db/load_network.py
    BPW_DSN=postgresql://user@host/db python3 rebuild/db/load_network.py
"""
from __future__ import annotations

import json
import os

import psycopg

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
GEOJSON = os.path.join(REPO, "rebuild", "data", "out", "network.geojson")
SCHEMA = os.path.join(REPO, "rebuild", "db", "schema.sql")

DSN = os.environ.get("BPW_DSN", "postgresql://postgres@localhost:5432/bbg")

COLUMNS = (
    "seg_id", "name", "ref", "class", "length_m",
    "node_a", "node_b", "homes", "carriageway", "geom",
)


def main() -> None:
    with open(GEOJSON) as fh:
        fc = json.load(fh)
    features = fc["features"]

    with psycopg.connect(DSN, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(open(SCHEMA).read())
            print("schema applied")

            # Coverage points at segments, so it goes first. Walks are kept:
            # a rebuild renumbers seg_ids, and silently dropping somebody's
            # walk history to reload a file would be the wrong trade.
            cur.execute("truncate coverage, walk_segment, segment restart identity cascade")

            # Staged through a temp table because geometry arrives as GeoJSON
            # text and COPY cannot convert it on the way in.
            cur.execute(
                "create temp table _seg_in ("
                " seg_id int, name text, ref text, class text, length_m float8,"
                " node_a text, node_b text, homes int, carriageway int, geojson text"
                ") on commit drop"
            )
            with cur.copy(
                f"copy _seg_in ({', '.join(COLUMNS[:-1])}, geojson) from stdin"
            ) as copy:
                for f in features:
                    p = f["properties"]
                    copy.write_row(
                        (
                            p["seg_id"],
                            p["name"],
                            p.get("ref"),
                            p["class"],
                            p["length_m"],
                            p["node_a"],
                            p["node_b"],
                            # Null, never zero. A zero would claim nobody lives
                            # on that street. See contracts.md section 6.
                            p.get("homes"),
                            p.get("carriageway"),
                            json.dumps(f["geometry"]),
                        )
                    )

            cur.execute(
                f"insert into segment ({', '.join(COLUMNS)}) "
                f"select {', '.join(COLUMNS[:-1])}, "
                " st_setsrid(st_geomfromgeojson(geojson), 4326) from _seg_in"
            )
            cur.execute("select count(*), round((sum(length_m)/1609.34)::numeric,2) from segment")
            n, drawn = cur.fetchone()
            cur.execute("select count(*), round((sum(length_m)/1609.34)::numeric,2) from street_unit")
            units, countable = cur.fetchone()
        conn.commit()

    print(f"loaded {n} segments, {drawn} mi drawn")
    print(f"       {units} countable units, {countable} mi countable")


if __name__ == "__main__":
    main()
