"""Fetch each registered source layer into a dated snapshot + sidecar.

Snapshots are the build input, never the live API (technical plan §2.1). Every run
writes pipeline/snapshots/<dataset>/<YYYY-MM-DD>.geojson alongside a .meta.json
recording where it came from, when, and under what terms.

The town's services advertise capabilities=Query,Sync — no Extract — so this pages
through /query with resultOffset rather than relying on a bulk export endpoint.

Usage:  python3 -m pipeline.sources.fetch [--date YYYY-MM-DD] [layer ...]
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .registry import BLOCKED, LAYERS

SNAP_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "snapshots")
UA = {"User-Agent": "blacksburg-prayer-walk-pipeline/1.0"}


def _request(url, params, tries=4):
    body = urllib.parse.urlencode(params).encode()
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, data=body, headers=UA)
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = e
            if attempt < tries - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"{url} failed after {tries} tries: {last}")


def layer_meta(url):
    return _request(url, {"f": "json"})


def feature_count(url):
    return _request(url + "/query", {"where": "1=1", "returnCountOnly": "true", "f": "json"}).get("count")


def fetch_geojson(url, page_size):
    """Page through the layer, returning one merged GeoJSON FeatureCollection in 4326."""
    features, offset = [], 0
    while True:
        d = _request(url + "/query", {
            "where": "1=1", "outFields": "*", "returnGeometry": "true",
            "outSR": "4326", "f": "geojson",
            "resultRecordCount": page_size, "resultOffset": offset,
            "orderByFields": "OBJECTID",
        })
        if "error" in d:
            raise RuntimeError(f"{url}: {d['error']}")
        page = d.get("features", [])
        features.extend(page)
        offset += len(page)
        print(f"    +{len(page):>6} (total {len(features)})", flush=True)
        # exceededTransferLimit lives at top level on geojson responses; some servers
        # use "properties.exceededTransferLimit" instead. Check both, and stop on an
        # empty page regardless so a server that reports neither can't loop forever.
        more = d.get("exceededTransferLimit") or (d.get("properties") or {}).get("exceededTransferLimit")
        if not page or not more:
            break
    return {"type": "FeatureCollection", "features": features}


def fetch_one(key, spec, date_str):
    print(f"  {key}: {spec['url']}", flush=True)
    meta = layer_meta(spec["url"])
    count = feature_count(spec["url"])
    page_size = min(meta.get("maxRecordCount") or 1000, 2000)
    gj = fetch_geojson(spec["url"], page_size)

    got = len(gj["features"])
    if count is not None and got != count:
        raise RuntimeError(f"{key}: fetched {got} features but server reports {count}")

    outdir = os.path.join(SNAP_ROOT, key)
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, f"{date_str}.geojson")
    with open(path, "w") as f:
        json.dump(gj, f)

    edit = meta.get("editingInfo") or {}

    def ms(x):
        return datetime.fromtimestamp(x / 1000, timezone.utc).isoformat() if x else None

    sidecar = {
        "dataset": key,
        "title": spec["title"],
        "publisher": spec["publisher"],
        "role": spec["role"],
        "source_url": spec["url"],
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "source_updated_at": ms(edit.get("dataLastEditDate")),
        "source_schema_updated_at": ms(edit.get("schemaLastEditDate")),
        "feature_count": got,
        "server_reported_count": count,
        "geometry_type": meta.get("geometryType"),
        "source_srs": (meta.get("extent") or {}).get("spatialReference"),
        "snapshot_srs": "EPSG:4326",
        "service_capabilities": meta.get("capabilities"),
        "max_record_count": meta.get("maxRecordCount"),
        # Verbatim from the service. Empty string means the service published nothing.
        "license_text": (meta.get("copyrightText") or "").strip(),
        "license_status": spec["license_status"],
        "source_id_field": spec["source_id_field"],
        "stable_id_field": spec["stable_id_field"],
        "field_names": [f["name"] for f in meta.get("fields", [])],
    }
    with open(os.path.join(outdir, f"{date_str}.meta.json"), "w") as f:
        json.dump(sidecar, f, indent=2)

    print(f"    -> {path}  ({got} features, source edited {sidecar['source_updated_at']})", flush=True)
    return sidecar


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("layers", nargs="*", help="layer keys to fetch (default: all)")
    ap.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = ap.parse_args()

    keys = args.layers or list(LAYERS)
    print(f"Fetching {len(keys)} layers into snapshot {args.date}")
    sidecars = [fetch_one(k, LAYERS[k], args.date) for k in keys]

    manifest = {
        "snapshot_date": args.date,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "layers": sidecars,
        "blocked_sources": [
            dict(v, note="egress policy denied this host from the build environment; "
                         "no data retrieved, no schema inferred")
            for v in BLOCKED.values()
        ],
    }
    os.makedirs(SNAP_ROOT, exist_ok=True)
    with open(os.path.join(SNAP_ROOT, f"manifest-{args.date}.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"\nManifest: snapshots/manifest-{args.date}.json")
    if BLOCKED:
        print(f"WARNING: {len(BLOCKED)} source(s) unreachable — see manifest.blocked_sources")


if __name__ == "__main__":
    sys.exit(main())
