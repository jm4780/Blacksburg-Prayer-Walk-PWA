"""Generate the emphasis field — web/public/basemap/emphasis.json.

The regional basemap is one corpus, drawn one way, everywhere. That is what makes it
feel like a real place rather than a town with scenery glued around it, and it is not
being changed. What this adds is *emphasis*: three levels where there were two.

    the surrounding world      the archive, darkened outward from the town
    the mission area           the same archive, on a lifted plate
    the prayer overlay         untouched, and still the brightest thing on the map

The middle level is the one that was missing. Darkening the outside alone gives the
town no stage of its own — only an absence around it — and an absence is not a place.
So this file emits a signed-distance field around the municipal line and hangs two
values off every band of it: `a`, how much the ground is darkened, and `l`, how much
it is lifted. One geometry, two directions, and the crossing between them centred on
the boundary rather than either side of it.

The two ramps are deliberately different widths, and the town's own shape is why. It
is 51 km2 of sprawl, not a blob: erode it by 2 km and only 5 km2 survives, so a lift
that faded over kilometres would leave the plate a gradient with no shape to it. The
lift therefore feathers over 1 km, centred on the line; the darkening keeps its 4.8 km.
Short plate, long falloff.

Three more things are deliberate.

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

# --- the darkening, in kilometres from the town boundary. Negative is inside. ------
#
# Both ramps now begin exactly on the line, and that is a correction. An earlier cut
# started the darkening 800 m inside it, reasoning that a ramp beginning at the
# boundary would put its first millimetre on the municipal edge and accidentally draw
# a border. Measured, that cost the town's outer kilometre 8.6% — the streets closest
# to the line were the dimmest part of the mission area, which is precisely backwards.
#
# Starting on the line costs nothing, because smootherstep has zero slope at both of
# its ends: the boundary is the flattest point in the entire field, the one place
# where nothing is changing. There is no coincidence for the eye to find because
# there is no change there to notice.
INNER_KM = 0.0
# Three point two kilometres past the line. It was four while the ramp still began
# 800 m inside; moving the start onto the line pushed the whole curve outward and the
# country two to three kilometres out came back 6 points brighter than the version
# already approved. Shortening the reach by the same 800 m puts the shape back where
# it was, without touching either end.
OUTER_KM = 3.2

# --- the plate --------------------------------------------------------------------
#
# 700 m of feather, sitting slightly inside the line but crossing it: about 50 px at
# the dashboard's scale. That is the plate's own edge, and it has to be on the boundary
# rather than short of it — the whole effect is two surfaces meeting, and they cannot
# meet anywhere else without the shape stopping being the town's.
#
# An earlier cut stopped the lift 150 m short of the line, out of a fear of halos. That
# fear was correct for a lift drawn OVER the linework, which brightens roads and reads
# as a glow. It does not apply to a tint drawn UNDER it: a surface that fades across
# its own border is just a soft edge.
LIFT_FROM = -0.4
LIFT_TO = 0.3
# How much the ground under the town comes up. This is a lerp toward `stage` in the
# style, so the number here is only the ramp; the colour and its alpha live in
# tokens.ts and blacksburg.json with everything else.
LIFT = 1.0

# Peak alpha of the wash, and the one number worth arguing about.
#
# Two things make the arithmetic lie here, both in the same direction. A thin line is
# mostly antialiased edge — partial blends of road over land, sitting in the gamma
# part of the sRGB curve where a given alpha costs far more luminance than it does on
# either pure colour. And the map is made of thin lines. So 0.125 calculated at -13%
# and measured at -17.3%.
#
# And a third thing made it lie, until it was caught: the wash used to be drawn twice,
# once over the ground and once over the labels, because the prayer overlays were
# inserted between them. Two passes of 0.22 is one pass of 0.39, so the number in this
# file was never the number on the screen. Restructuring so the emphasis sits wholly
# below the overlay left one pass, and the alpha had to come up to match what was
# already shipped.
#
# 0.35 measures at -40%, which is the level already approved. It was 0.39 for as long
# as the road ramp carried a global +7% lift; taking that back out (the plate does that
# job now) deepened the region by five points on its own, and the alpha came down to
# meet it. Any change here should be re-measured on a render, not recalculated —
# see docs/20 §2.
ALPHA = 0.35

# Band spacing, in kilometres, outward from the line. The first stretch needs fine
# steps because the lift does all of its work there; the far end of the darkening can
# be coarse because smootherstep has almost flattened by then. Inside the line nothing
# varies at all, so the whole town is a single feature.
STEPS = [(-0.4, 0.4, 0.05), (0.4, 1.6, 0.15), (1.6, 3.2, 0.2)]

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


def distances():
    """The signed distances at which rings are cut, inside to outside."""
    out = []
    for lo, hi, step in STEPS:
        d = lo
        while d < hi - 1e-9:
            out.append(round(d, 4))
            d += step
    out.append(STEPS[-1][1])
    return out


def wash_at(d):
    """How dark the ground is at signed distance `d` from the line."""
    return ALPHA * smootherstep((d - INNER_KM) / (OUTER_KM - INNER_KM))


def lift_at(d):
    """How lifted it is. Full inside the plate, gone just outside it."""
    return LIFT * (1.0 - smootherstep((d - LIFT_FROM) / (LIFT_TO - LIFT_FROM)))


def build(src=None):
    town = to_km(load_boundary(src))
    # Buffering a 1,757-point outline forty times is the slow part; a light
    # generalisation first costs nothing visible and makes it quick.
    town = town.simplify(0.03, preserve_topology=True)

    ds = distances()
    rings = []
    for d in ds:
        # A ring 4 km out has been smoothed into near-circular arcs by the buffer
        # itself and does not need the boundary's 1,757 points; the ones near the line
        # carry the plate's shape and keep the most detail. Nothing here is ever drawn
        # as a line, so the only cost of simplifying is where an invisible step sits.
        t = (d - ds[0]) / (ds[-1] - ds[0])
        tol = (SIMPLIFY_M[0] + (SIMPLIFY_M[1] - SIMPLIFY_M[0]) * t) / 1000.0
        g = town.buffer(d, quad_segs=16, join_style=1).simplify(tol)
        if g.is_empty:
            raise SystemExit(f'Ring at {d:+.2f} km collapsed — the town is only '
                             f'{town.area:.0f} km2 and much of it is narrow')
        rings.append(unary_union(g))

    features = []

    def add(geom, d_mid):
        if geom.is_empty:
            return
        props = {}
        a = round(wash_at(d_mid), 4)
        l = round(lift_at(d_mid), 4)
        # Only carry a value where it does something. The style filters on presence,
        # so a band with no lift costs nothing in the plate layer and vice versa.
        if a > 0.0005:
            props['a'] = a
        if l > 0.0005:
            props['l'] = l
        if props:
            features.append({'type': 'Feature', 'properties': props,
                             'geometry': mapping(to_deg(geom))})

    # The town's interior: one feature, full plate, no darkening. This is the part of
    # the map the whole exercise is pointing at, and it is uniform on purpose.
    add(rings[0], -0.8)

    for i in range(len(ds) - 1):
        # Each band is an annulus: the next ring out, with this one taken out of it.
        # Bands never overlap, so neither value ever compounds.
        add(rings[i + 1].difference(rings[i]), (ds[i] + ds[i + 1]) / 2)

    # Everything beyond the ramp, at full darkening. Generous enough to cover the
    # archive's own extent and then some: the field must not run out before the map does.
    from shapely.geometry import box
    world = box(-84.0, 34.0, -76.0, 40.5)
    features.append({
        'type': 'Feature', 'properties': {'a': ALPHA},
        'geometry': mapping(world.difference(to_deg(rings[-1]))),
    })

    # The line itself, for the frame. Simplified to 25 m: it is drawn under a pixel
    # wide and every vertex beyond that is bytes nobody can see.
    features.append({
        'type': 'Feature', 'properties': {'kind': 'town'},
        'geometry': mapping(to_deg(town.simplify(0.025).boundary)),
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
    n_a = sum(1 for f in fc['features'] if 'a' in f['properties'])
    n_l = sum(1 for f in fc['features'] if 'l' in f['properties'])
    print(f'{OUT}  {len(fc["features"])} features  '
          f'({n_a} darkened, {n_l} lifted, 1 outline)  '
          f'dark {INNER_KM:+.1f}..{OUTER_KM:+.1f} km to alpha {ALPHA}  '
          f'lift {LIFT_FROM:+.1f}..{LIFT_TO:+.1f} km  '
          f'{os.path.getsize(OUT) / 1024:.0f} KB')
