"""Generate the emphasis wash — web/public/basemap/emphasis.json.

The regional basemap is one corpus, drawn one way, everywhere. That is what makes it
feel like a real place rather than a town with scenery glued around it, and it is not
being changed. What this adds is *emphasis*: a falloff that lets the eye settle on
Blacksburg without ever finding an edge to settle against.

Three things about it are deliberate.

  IT FOLLOWS THE TOWN, NOT A SHAPE DRAWN AROUND IT. The first cut used an ellipse,
  on the theory that washing the town limits would draw the town limits. That was
  wrong twice over: an ellipse cannot follow a town that is 9 km across and 10 km tall
  with a notch cut out of its south-west corner, so the wash arrived early on some
  sides and late on others; and a falloff four kilometres wide has no edge to draw
  whatever shape it starts from. The boundary is the honest centre line.

  THE BOUNDARY IS PUBLIC DOMAIN, NOT THE TOWN'S OWN GIS. USGS GovtUnit —
  `GU_IncorporatedPlace`, Census-sourced, 51.35 km², the real municipal limits. This
  repository is public and release gate G1 forbids redistributing Town of Blacksburg
  geometry (docs/05); the federal copy carries no such restriction, so the falloff can
  be checked in like any other build artifact.

  IT DARKENS BY COMPOSITING, NOT BY RESTYLING. One near-black fill at low alpha over
  everything below it. Alpha compositing moves every colour a fixed fraction toward
  the wash, so the same single control produces all three effects at once: darker
  (values fall), lower contrast (differences shrink by the same fraction), and less
  saturated (chroma collapses toward a neutral). Nothing has to be tuned three times,
  and nothing can drift out of agreement with itself.

Run:  python3 -m pipeline.basemap.emphasis [path/to/GU_IncorporatedPlace]

The shapefile is not committed — it is 69 MB of statewide boundaries for one polygon.
`pipeline/basemap/build.sh` fetches it; the extracted boundary is cached next to this
file as `blacksburg-limits.json` so a rebuild does not need the download again.
"""
import json
import math
import os
import sys

from shapely.geometry import mapping, shape
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(ROOT, 'web', 'public', 'basemap', 'emphasis.json')
CACHE = os.path.join(HERE, 'blacksburg-limits.json')

# Blacksburg sits at 37.23 N. Working in degrees and scaling the longitude axis is
# accurate to a few metres over a 15 km span and avoids a projection dependency.
LAT0 = 37.2299
KM_LAT = 110.57
KM_LON = 111.32 * math.cos(math.radians(LAT0))

# The falloff, in kilometres from the town boundary. Negative is inside.
#
# It starts *inside* the line on purpose. If the wash began exactly at the boundary,
# the outermost streets of Blacksburg would be the last fully-bright thing on the map
# and the first millimetre of falloff would sit right on the municipal edge — which is
# how you accidentally draw a border. Starting 800 m in means the ramp is already
# underway when it crosses, and there is no coincidence for the eye to find.
INNER_KM = -0.8
# Four kilometres past the line. At the dashboard's framing that is the full width of
# the visible country to the east and west, and it keeps going beyond the frame.
OUTER_KM = 4.0

# Peak alpha of the wash, and the one number worth arguing about.
#
# Two things make the arithmetic lie here, both in the same direction. A thin line is
# mostly antialiased edge — partial blends of road over land, sitting in the gamma
# part of the sRGB curve where a given alpha costs far more luminance than it does on
# either pure colour. And the map is made of thin lines. So 0.125 calculated at -13%
# and measured at -17.3%.
#
# 0.22 measures at about -30%, which is where "noticeably quieter" starts without the
# region ceasing to read as the same map. Any change here should be re-measured on a
# render, not recalculated — see docs/20 §2.
ALPHA = 0.22

# Bands across the feather. The step that matters is the largest one, not the average:
# smootherstep concentrates its change in the middle, so adjacent bands there differ by
# about twice the mean. Thirty-two over 4.8 km puts the worst case near 0.3 of a display
# level, spread over roughly 12 px at dashboard zoom. Cheap insurance — the whole file
# is under 100 KB either way.
BANDS = 32

# Simplification, in metres, at the inner and outer ends of the ramp. A ring four
# kilometres out has been smoothed into near-circular arcs by the buffer itself and
# does not need the boundary's original 1,757 points; the innermost one is closest to
# the real outline and keeps the most detail. Nothing here is ever drawn as a line, so
# the only cost of simplifying is the position of an invisible alpha step.
SIMPLIFY_M = (60, 400)


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


def to_km(geom):
    """Degrees -> a local kilometre plane, so buffering is isotropic."""
    from shapely.ops import transform
    return transform(lambda x, y: (x * KM_LON, y * KM_LAT), geom)


def to_deg(geom):
    from shapely.ops import transform
    return transform(lambda x, y: (x / KM_LON, y / KM_LAT), geom)


def smootherstep(t):
    """Zero slope at both ends, so neither the start nor the end of the falloff is a
    place the eye can catch."""
    t = max(0.0, min(1.0, t))
    return t * t * t * (t * (t * 6 - 15) + 10)


def build(src=None):
    town = to_km(load_boundary(src))
    # Buffering a 1,757-point outline 20 times is the slow part; a light generalisation
    # first costs nothing visible and makes it quick. 30 m, against a ramp 4.8 km wide.
    town = town.simplify(0.03, preserve_topology=True)

    rings = []
    for i in range(BANDS + 1):
        t = i / BANDS
        dist = INNER_KM + (OUTER_KM - INNER_KM) * t
        tol = (SIMPLIFY_M[0] + (SIMPLIFY_M[1] - SIMPLIFY_M[0]) * t) / 1000.0
        # quad_segs is generous: the joins are what a viewer would notice first if the
        # buffer were coarse, and they are free compared with the boundary itself.
        g = town.buffer(dist, quad_segs=16, join_style=1).simplify(tol)
        if g.is_empty:
            raise SystemExit(f'Ring at {dist:.2f} km collapsed — INNER_KM too negative')
        rings.append(unary_union(g))

    features = []
    for i in range(BANDS):
        # Each band is an annulus: the next ring out, with this one taken out of it.
        # Bands never overlap, so alpha never compounds and the ramp stays the ramp.
        band = rings[i + 1].difference(rings[i])
        if band.is_empty:
            continue
        alpha = ALPHA * smootherstep((i + 0.5) / BANDS)
        features.append({
            'type': 'Feature',
            'properties': {'a': round(alpha, 4)},
            'geometry': mapping(to_deg(band)),
        })

    # Everything beyond the feather, at full strength. Generous enough to cover the
    # archive's own extent and then some: the wash must not run out before the map does.
    from shapely.geometry import box
    world = box(-84.0, 34.0, -76.0, 40.5)
    features.append({
        'type': 'Feature',
        'properties': {'a': ALPHA},
        'geometry': mapping(world.difference(to_deg(rings[-1]))),
    })
    return {'type': 'FeatureCollection', 'features': features}


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
    print(f'{OUT}  {len(fc["features"])} bands  '
          f'alpha 0 -> {ALPHA}  {INNER_KM:+.1f} to {OUTER_KM:+.1f} km  '
          f'{os.path.getsize(OUT) / 1024:.0f} KB')
