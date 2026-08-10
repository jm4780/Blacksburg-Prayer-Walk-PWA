"""Load the extracted network into Postgres/PostGIS.

Usage:  python3 rebuild/db/load_network.py [dsn]
"""
import json
import os
import subprocess
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
GEOJSON = os.path.join(REPO, "rebuild", "data", "out", "network.geojson")
SCHEMA = os.path.join(REPO, "rebuild", "db", "schema.sql")
DB = os.environ.get("BBG_DB", "bbg")


def psql(sql: str, quiet: bool = True):
    args = ["su", "postgres", "-c", f"psql -v ON_ERROR_STOP=1 -q -d {DB} -c {json.dumps(sql)}"]
    if not quiet:
        args = ["su", "postgres", "-c", f"psql -v ON_ERROR_STOP=1 -d {DB} -tAc {json.dumps(sql)}"]
    out = subprocess.run(args, capture_output=True, text=True)
    if out.returncode:
        raise SystemExit(out.stderr.strip())
    return out.stdout.strip()


def main():
    subprocess.run(
        ["su", "postgres", "-c", f"psql -v ON_ERROR_STOP=1 -q -d {DB} -f {SCHEMA}"], check=True
    )
    print("schema applied")

    fc = json.load(open(GEOJSON))
    psql("truncate coverage, walk_segment, walk, segment restart identity cascade;")

    rows = []
    for f in fc["features"]:
        p = f["properties"]
        geom = json.dumps(f["geometry"])
        rows.append(
            "\t".join(
                [
                    str(p["seg_id"]),
                    p["name"].replace("\t", " "),
                    p["ref"] or "\\N",
                    p["class"],
                    str(p["length_m"]),
                    p["node_a"],
                    p["node_b"],
                    # Null unless the authoritative fetch supplied a real count.
                    # Never zero: zero is a claim that nobody lives there.
                    ("\\N" if p.get("homes") is None else str(p["homes"])),
                    ("\\N" if p.get("carriageway") is None else str(p["carriageway"])),
                    geom,
                ]
            )
        )

    tsv = "\n".join(rows) + "\n"
    tmp = "/tmp/bbg_segments.tsv"
    with open(tmp, "w") as fh:
        fh.write(tsv)
    os.chmod(tmp, 0o644)

    # \copy is a psql meta-command, so the load runs from a script file rather
    # than -c. Temp table and copy must share one session.
    script = "/tmp/bbg_load.sql"
    with open(script, "w") as fh:
        fh.write(
            "create temp table _seg_in (seg_id int, name text, ref text, class text,\n"
            " length_m float8, node_a text, node_b text, homes int, carriageway int,\n"
            " geojson text);\n"
            f"\\copy _seg_in from '{tmp}' with (format text)\n"
            "insert into segment (seg_id,name,ref,class,length_m,node_a,node_b,homes,carriageway,geom)\n"
            "select seg_id,name,ref,class,length_m,node_a,node_b,homes,carriageway,\n"
            " st_setsrid(st_geomfromgeojson(geojson),4326) from _seg_in;\n"
        )
    os.chmod(script, 0o644)
    subprocess.run(
        ["su", "postgres", "-c", f"psql -v ON_ERROR_STOP=1 -q -d {DB} -f {script}"], check=True
    )

    n = psql("select count(*) from segment;", quiet=False)
    mi = psql("select round((sum(length_m)/1609.34)::numeric,2) from segment;", quiet=False)
    print(f"loaded {n} segments, {mi} mi")


if __name__ == "__main__":
    main()
