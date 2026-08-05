"""Extract the municipal limits — web/public/basemap/boundary.json.

One line. That is the whole file, and the shortness of it is the point.

This used to emit a forty-band signed-distance field: an alpha ramp that darkened the
country outward from the town and a second one that lifted a tinted "plate" underneath
it. Both worked, in the sense that they measured what they were meant to measure. Both
were also, plainly, effects painted over a map — and on screen that is exactly what
they looked like: a soft green cloud with a findable edge, sitting on top of the
cartography rather than being part of it.

The hierarchy the product actually wants does not need any of that, because the map
already contains it. Blacksburg is where the mission is, so Blacksburg is where 1,868
prayer segments are drawn, and nowhere else in the region has a single one. Draw those
segments so they read, and the town separates itself from the country by the only
means a map is allowed to use: what is on it. Turn them down to a half-pixel hairline
at 45% and the town vanishes into the basemap — which is what had been happening, and
the real reason three rounds of tuning went looking for an effect to compensate.

So the emphasis field is gone and this is what is left of it: the municipal outline,
drawn once, as a genuine cartographic boundary at the weight a boundary deserves.

  THE BOUNDARY IS PUBLIC DOMAIN, NOT THE TOWN'S OWN GIS. USGS GovtUnit —
  `GU_IncorporatedPlace`, Census-sourced, 51.35 km², the real municipal limits. This
  repository is public and release gate G1 forbids redistributing Town of Blacksburg
  geometry (docs/05); the federal copy carries no such restriction, so the outline can
  be checked in like any other build artifact.

Run:  python3 -m pipeline.basemap.boundary [path/to/GU_IncorporatedPlace]

The shapefile is not committed — it is 69 MB of statewide boundaries for one polygon.
`pipeline/basemap/build.sh` fetches it; the extracted boundary is cached next to this
file as `blacksburg-limits.json` so a rebuild does not need the download again.
"""
import json
import os
import sys

from shapely.geometry import mapping, shape

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(ROOT, 'web', 'public', 'basemap', 'boundary.json')
CACHE = os.path.join(HERE, 'blacksburg-limits.json')

# Simplification, in degrees, before the outline is written. The line renders between
# one and two pixels wide at every zoom the app uses, so vertices finer than about
# 25 m are bytes nobody can see. 1,757 points becomes a few hundred.
SIMPLIFY_DEG = 0.00028


def load_boundary(src=None):
    """The Town of Blacksburg municipal limits, as a shapely polygon."""
    if src is None and os.path.exists(CACHE):
        with open(CACHE) as f:
            return shape(json.load(f))
    if src is None:
        raise SystemExit(
            f'No cached boundary at {CACHE} and no shapefile given.\n'
            'Run pipeline/basemap/build.sh, or pass the path to GU_IncorporatedPlace.')

    import shapefile  # pyshp, only needed on the extract path
    r = shapefile.Reader(src, encoding='latin-1', encodingErrors='replace')
    for sr in r.iterShapeRecords():
        d = sr.record.as_dict()
        if 'Blacksburg' in str(d.get('PLACE_NAME', '')):
            geom = shape(sr.shape.__geo_interface__)
            with open(CACHE, 'w') as f:
                json.dump(mapping(geom), f, separators=(',', ':'))
            print(f'  cached {d["PLACE_NAME"]}, {d["AREASQKM"]:.2f} km2 -> {CACHE}')
            return geom
    raise SystemExit('Blacksburg not found in ' + src)


def build(src=None):
    town = load_boundary(src).simplify(SIMPLIFY_DEG, preserve_topology=True)
    return {
        'type': 'FeatureCollection',
        'features': [{
            'type': 'Feature',
            'properties': {'kind': 'town', 'name': 'Blacksburg'},
            'geometry': mapping(town.boundary),
        }],
    }


def round_coords(obj, nd=5):
    if isinstance(obj, float):
        return round(obj, nd)
    if isinstance(obj, list):
        return [round_coords(v, nd) for v in obj]
    if isinstance(obj, dict):
        return {k: round_coords(v, nd) for k, v in obj.items()}
    return obj


if __name__ == '__main__':
    fc = round_coords(build(sys.argv[1] if len(sys.argv) > 1 else None))
    with open(OUT, 'w') as f:
        json.dump(fc, f, separators=(',', ':'))
    print(f'{OUT}  municipal limits, {os.path.getsize(OUT) / 1024:.0f} KB')
