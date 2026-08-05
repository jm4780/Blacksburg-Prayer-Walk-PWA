"""Generate the emphasis wash — web/public/basemap/emphasis.json.

The regional basemap is one corpus, drawn one way, everywhere. That is what makes it
feel like a real place rather than a town with scenery glued around it, and it is not
being changed. What this adds is *emphasis*: a soft, centred falloff that lets the eye
settle on Blacksburg without ever finding an edge to settle against.

Two things about the shape of it are deliberate:

  IT IS AN ELLIPSE, NOT THE TOWN BOUNDARY. Washing exactly the town limits would draw
  the town limits — a shape you can trace, and the one thing the brief rules out. The
  falloff is centred on the town and runs for kilometres, so there is nowhere it
  visibly starts. It also means no Town of Blacksburg geometry ends up in this public
  repository, which release gate G1 requires anyway (docs/05).

  IT DARKENS BY COMPOSITING, NOT BY RESTYLING. One near-black fill at low alpha over
  everything below it. Alpha compositing moves every colour a fixed fraction toward
  the wash, so the same single control produces all three effects the brief asks for:
  darker (values fall), lower contrast (differences shrink by the same fraction), and
  less saturated (chroma collapses toward a neutral). Nothing has to be tuned three
  times, and nothing can drift out of agreement with itself.

Run:  python3 -m pipeline.basemap.emphasis
"""
import json
import math
import os

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'web', 'public', 'basemap', 'emphasis.json')

# The town centroid, as used everywhere else in the app.
CENTRE = (-80.4279, 37.2299)
KM_LAT = 110.57
KM_LON = 111.32 * math.cos(math.radians(CENTRE[1]))

# Semi-axes, km, measured against the frame the dashboard actually draws rather than
# against the town's own dimensions — which is the mistake the first cut made. The
# compact dashboard shows +/-7.3 km east-west and +/-5.4 km north-south; a falloff that
# only reached full strength at 11 km never engaged inside it at all, and the whole
# refinement was invisible.
#
# So: untouched out to 3 km, which is downtown, campus and the neighbourhoods either
# side of them.
INNER = (3.0, 3.5)
# Full strength by 7.5-8 km, which is the edge of the dashboard frame and a little
# past the obligation. The obligation itself runs to about 4 km east-west and 5 km
# north-south, so its outer streets sit in the first quarter of the ramp — a few
# percent, well under the point where anything is visible as a change.
OUTER = (7.5, 8.0)

# Peak alpha of the wash, and the one number worth arguing about.
#
# The colour arithmetic says 0.15 takes about 16% off a road. Measured on the rendered
# frame it took 21.7%, because a thin line is mostly antialiased edge — partial blends
# of road over land, which sit in the gamma part of the sRGB curve where the same alpha
# costs far more luminance than it does on either pure colour. The map is made of thin
# lines, so the rendered number is the real one.
#
# 0.125 measures at -18%, which is the middle of the 15-20% asked for. Any change here
# should be re-measured on a render, not recalculated.
ALPHA = 0.125

# Rings across the feather. Sixteen over four and a half kilometres puts under one
# alpha-percent between neighbours, which is below the point where a gradient bands on
# an 8-bit display. Smoothness is what makes the falloff unfindable; length is not.
RINGS = 16
# Vertices per ring. At this radius 144 puts a vertex every ~450 m, well under a
# pixel of chord error at any zoom the app uses.
STEPS = 144


def smootherstep(t):
    """Zero slope at both ends, so neither the start nor the end of the falloff is a
    place the eye can catch."""
    t = max(0.0, min(1.0, t))
    return t * t * t * (t * (t * 6 - 15) + 10)


def ellipse(scale):
    """Ring at `scale` of the way from INNER to OUTER, as [lon, lat] pairs."""
    a = INNER[0] + (OUTER[0] - INNER[0]) * scale
    b = INNER[1] + (OUTER[1] - INNER[1]) * scale
    pts = []
    for i in range(STEPS + 1):
        th = 2 * math.pi * i / STEPS
        pts.append([round(CENTRE[0] + a * math.cos(th) / KM_LON, 5),
                    round(CENTRE[1] + b * math.sin(th) / KM_LAT, 5)])
    pts[-1] = pts[0]
    return pts


def build():
    features = []
    rings = [ellipse(i / RINGS) for i in range(RINGS + 1)]
    for i in range(RINGS):
        # Each band is an annulus: the next ring out, with this one punched out of it.
        # Bands never overlap, so alpha never compounds and the ramp stays the ramp.
        alpha = ALPHA * smootherstep((i + 0.5) / RINGS)
        features.append({
            'type': 'Feature',
            'properties': {'a': round(alpha, 4)},
            'geometry': {'type': 'Polygon',
                         'coordinates': [rings[i + 1], rings[i][::-1]]},
        })
    # Everything beyond the feather, at full strength. Generous enough to cover the
    # archive's own extent and then some, because the wash must not run out before
    # the map does.
    world = [[-84.0, 34.0], [-76.0, 34.0], [-76.0, 40.5], [-84.0, 40.5], [-84.0, 34.0]]
    features.append({
        'type': 'Feature',
        'properties': {'a': ALPHA},
        'geometry': {'type': 'Polygon', 'coordinates': [world, rings[-1][::-1]]},
    })
    return {'type': 'FeatureCollection', 'features': features}


if __name__ == '__main__':
    fc = build()
    with open(OUT, 'w') as f:
        json.dump(fc, f, separators=(',', ':'))
    print(f'{OUT}  {len(fc["features"])} bands  '
          f'{os.path.getsize(OUT) / 1024:.0f} KB')
