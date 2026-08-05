"""Extract the Blacksburg regional basemap corpus from public-domain USGS sources.

Everything here is US federal government work: The National Map (Transportation,
Hydrography, Small-scale) and GNIS. No OpenStreetMap geometry is touched, so the
output carries no ODbL share-alike obligation onto the Prayer Walk data.

Writes newline-delimited GeoJSON, one file per basemap layer, for tippecanoe.
"""
import json
import os
import sys

import shapefile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'ndjson')
os.makedirs(OUT, exist_ok=True)

# ~50 km around the town centroid (-80.4279, 37.2299). Wide enough that the New
# River, Christiansburg, Radford, Salem, Floyd, Pearisburg and both Jefferson
# National Forest arms are inside the frame, so the map keeps going in every
# direction rather than stopping at a rectangle drawn around the obligation.
W, S, E, N = -81.00, 36.80, -79.80, 37.65


def hits(bbox):
    """Shapefile bbox (xmin, ymin, xmax, ymax) intersects the region."""
    return not (bbox[2] < W or bbox[0] > E or bbox[3] < S or bbox[1] > N)


class Sink:
    def __init__(self, name):
        self.path = os.path.join(OUT, name + '.geojsonl')
        self.f = open(self.path, 'w')
        self.n = 0

    def add(self, geom, props):
        self.f.write(json.dumps(
            {'type': 'Feature', 'properties': props, 'geometry': geom},
            separators=(',', ':')) + '\n')
        self.n += 1

    def close(self):
        self.f.close()
        print(f'  {os.path.basename(self.path):24s} {self.n:>8,} features '
              f'{os.path.getsize(self.path) / 1e6:.1f} MB')


def rings(shape):
    """Shapefile polygon parts -> GeoJSON Polygon/MultiPolygon.

    Shapefiles do not record which ring belongs to which polygon, only winding
    order (clockwise = outer, counter-clockwise = hole). Rebuild the nesting from
    that, because a MultiPolygon whose holes are promoted to islands renders as a
    forest with solid patches where its lakes should be.
    """
    parts = list(shape.parts) + [len(shape.points)]
    polys, cur = [], None
    for i in range(len(parts) - 1):
        ring = [[round(x, 5), round(y, 5)] for x, y in shape.points[parts[i]:parts[i + 1]]]
        if len(ring) < 4:
            continue
        area = sum((ring[j + 1][0] - ring[j][0]) * (ring[j + 1][1] + ring[j][1])
                   for j in range(len(ring) - 1))
        if area > 0:          # clockwise: a new outer ring
            cur = [ring]
            polys.append(cur)
        elif cur is not None:  # counter-clockwise: a hole in the ring before it
            cur.append(ring)
    if not polys:
        return None
    if len(polys) == 1:
        return {'type': 'Polygon', 'coordinates': polys[0]}
    return {'type': 'MultiPolygon', 'coordinates': polys}


def lines(shape):
    parts = list(shape.parts) + [len(shape.points)]
    segs = [[[round(x, 5), round(y, 5)] for x, y in shape.points[parts[i]:parts[i + 1]]]
            for i in range(len(parts) - 1)]
    segs = [s for s in segs if len(s) >= 2]
    if not segs:
        return None
    if len(segs) == 1:
        return {'type': 'LineString', 'coordinates': segs[0]}
    return {'type': 'MultiLineString', 'coordinates': segs}


# ---------------------------------------------------------------- roads
# TNM functional road class -> the six classes the style knows about. The style
# spends luminance on this and nothing else, so the ramp has to be honest: an
# interstate really is the thing you orient by from thirty miles away, and a
# residential street really is not.
FRC = {1: 'motorway', 2: 'motorway', 3: 'trunk', 4: 'primary',
       5: 'secondary', 6: 'tertiary', 7: 'minor'}
# Driveways, parking aisles, alleys, bike paths, bridle trails, 4WD tracks. All of
# it is real, none of it helps anyone work out where they are.
SKIP_MTFCC = {'S1500', 'S1640', 'S1710', 'S1720', 'S1730', 'S1740',
              'S1750', 'S1780', 'S1820', 'S1830'}

# FRC ALONE IS NOT A HIERARCHY, AND BELIEVING IT WAS COST THE MAP ITS CENTRE.
#
# Measured on the shipped archive, 12,789 of 14,008 road features in a fifty-kilometre
# frame — 91% — came back as FRC 4, and were therefore drawn at `primary`: the third
# brightest rung of a five-rung luminance ramp built on the premise that the rungs mean
# something. Stanger Street and Drillfield Drive, both on the Virginia Tech campus, are
# FRC 4. So is every gravel lane in Montgomery County. The other four rungs rendered
# nothing at all, in the whole region, at any zoom.
#
# The consequence was not subtle: the countryside was drawn at exactly the weight of
# the town, so Blacksburg did not stand out, so three rounds of work went into painting
# emphasis effects over the map to put back a hierarchy the data had been carrying all
# along. There was never anything wrong with the ramp. There was something wrong with
# what was being fed into it.
#
# MTFCC is the Census feature class and it is the reliable discriminator at the bottom
# of the range, where FRC gives up: S1100 is a primary road, S1200 a secondary one,
# S1400 a local neighbourhood street. FRC is kept for the top, where it is right and
# MTFCC is coarse — it is what separates I-81 from US 460. Each field is used for the
# part of the range it actually knows about.
MTFCC_FLOOR = {
    'S1400': 'minor',      # local neighbourhood road, rural road, city street
    'S1200': 'secondary',  # secondary road — state and county highways
}
# Only ever demoted, never promoted. If FRC says a segment is an interstate, MTFCC
# saying "city street" is a disagreement to lose, not a correction to apply.
RANK = {'motorway': 5, 'trunk': 4, 'primary': 3, 'secondary': 2,
        'tertiary': 1, 'minor': 0, 'link': 0}


def route_ref(rec):
    """"Bus,460" -> "US 460 Bus"; "11,460" -> "US 11/460"; "460,Alt,11" -> "US 460/11".

    USGS packs concurrencies and qualifiers into one comma-delimited field, so a
    naive prefix produces "US Bus,460" on the sign for Main Street. Route numbers
    are the part people navigate by; a leading qualifier is kept because Business
    460 and 460 are genuinely different roads, and interior ones are dropped
    because "US 460/11 Alt" is not a thing anybody reads at walking pace.
    """
    for f, pre in (('interstate', 'I-'), ('us_route', 'US '), ('state_rout', 'VA ')):
        parts = [p.strip() for p in (rec[f] or '').split(',') if p.strip()]
        if not parts:
            continue
        numbers = [p for p in parts if p.isdigit()]
        # Virginia numbers its primary routes 1-599 and its secondary (county) roads
        # 600 and up. "VA 600" on a gravel lane is noise wearing a shield.
        if f == 'state_rout':
            numbers = [p for p in numbers if int(p) < 600]
        if not numbers:
            continue
        suffix = f' {parts[0]}' if not parts[0].isdigit() else ''
        return pre + '/'.join(numbers[:2]) + suffix
    return ''


def do_roads():
    sink = Sink('roads')
    for src in ('tran/Trans_RoadSegment_0', 'tran/Trans_RoadSegment_1'):
        r = shapefile.Reader(os.path.join(HERE, src),
                             encoding='latin-1', encodingErrors='replace')
        for sr in r.iterShapeRecords():
            if not hits(sr.shape.bbox):
                continue
            rec = sr.record
            mtfcc = (rec['mtfcc_code'] or '').strip()
            if mtfcc in SKIP_MTFCC:
                continue
            cls = 'link' if mtfcc == 'S1630' else FRC.get(rec['tnmfrc'] or 7, 'minor')
            ref = route_ref(rec)
            # A SHIELD OUTRANKS A FEATURE CODE. US 460 is MTFCC S1200 — Census calls
            # it a secondary road, which is true of its construction and false of its
            # place in the town. It is the thing everyone in Blacksburg orients by,
            # and demoting it to the rung that holds every county highway in the
            # region would trade one broken hierarchy for another. Where a road
            # carries an Interstate, US or primary state route number, FRC keeps it.
            floor = None if ref else MTFCC_FLOOR.get(mtfcc)
            if floor and RANK[floor] < RANK[cls]:
                cls = floor
            geom = lines(sr.shape)
            if geom is None:
                continue
            props = {'class': cls}
            name = (rec['name'] or '').strip()
            # The shield is the name people navigate by: nobody in Blacksburg calls
            # US 460 "Christiansburg Road". Where a route number exists it wins.
            if ref:
                props['name'] = ref
                props['ref'] = ref
            elif name:
                props['name'] = name
            sink.add(geom, props)
        r.close()
    sink.close()


def do_rail():
    sink = Sink('rail')
    r = shapefile.Reader(os.path.join(HERE, 'tran/Trans_RailFeature'),
                         encoding='latin-1', encodingErrors='replace')
    for sr in r.iterShapeRecords():
        if not hits(sr.shape.bbox):
            continue
        geom = lines(sr.shape)
        if geom is not None:
            sink.add(geom, {'class': 'rail'})
    r.close()
    sink.close()


# ---------------------------------------------------------------- water
# NHD `visibility` is the smallest map scale at which the feature is meant to be
# drawn — 2,000,000 for the New River, 100,000 for a farm pond. Using it as the
# zoom threshold means the water thins out the way a cartographer would thin it,
# rather than the way a tile-size budget would.
def zoom_for_visibility(v):
    v = v or 0
    if v >= 1000000:
        return 7
    if v >= 500000:
        return 9
    if v >= 250000:
        return 10
    if v >= 100000:
        return 11
    return 13


def do_water():
    poly = Sink('water')
    line = Sink('waterway')
    for src, kind in (('nhd/NHDWaterbody', 'body'), ('nhd/NHDArea', 'area')):
        r = shapefile.Reader(os.path.join(HERE, src),
                             encoding='latin-1', encodingErrors='replace')
        for sr in r.iterShapeRecords():
            if not hits(sr.shape.bbox):
                continue
            rec = sr.record
            # 343 = "area to be submerged", 445 = sea/ocean. Neither is water you
            # can see, and drawing them puts lakes in dry fields.
            if kind == 'area' and rec['ftype'] not in (460, 390, 361):
                continue
            geom = rings(sr.shape)
            if geom is None:
                continue
            props = {'kind': kind, 'minz': zoom_for_visibility(rec['visibility'])}
            if (rec['gnis_name'] or '').strip():
                props['name'] = rec['gnis_name'].strip()
            poly.add(geom, props)
        r.close()

    r = shapefile.Reader(os.path.join(HERE, 'nhd/NHDFlowline'),
                         encoding='latin-1', encodingErrors='replace')
    for sr in r.iterShapeRecords():
        if not hits(sr.shape.bbox):
            continue
        rec = sr.record
        # 428 = pipeline, 420 = underground conduit. Not landmarks.
        if rec['ftype'] in (420, 428):
            continue
        geom = lines(sr.shape)
        if geom is None:
            continue
        props = {'minz': zoom_for_visibility(rec['visibility'])}
        nm = (rec['gnis_name'] or '').strip()
        if nm:
            props['name'] = nm
        # The New River is the one piece of water in this region that anyone
        # navigates by. It gets to appear before anything else does.
        if nm in ('New River', 'Roanoke River'):
            props['minz'] = 7
            props['major'] = True
        line.add(geom, props)
    r.close()
    poly.close()
    line.close()


# ---------------------------------------------------------------- land
def do_land():
    sink = Sink('land')
    r = shapefile.Reader(os.path.join(HERE, 'ss/fedlanp010g'),
                         encoding='latin-1', encodingErrors='replace')
    for sr in r.iterShapeRecords():
        if not hits(sr.shape.bbox):
            continue
        rec = sr.record
        if (rec['FEATURE1'] or '') not in ('National Forest', 'National Park',
                                           'Wilderness', 'National Wildlife Refuge'):
            continue
        geom = rings(sr.shape)
        if geom is None:
            continue
        sink.add(geom, {'kind': 'forest',
                        'name': (rec['GNIS_Name1'] or '').strip()})
    r.close()
    sink.close()


# ---------------------------------------------------------------- places
def do_places():
    sink = Sink('place')
    r = shapefile.Reader(os.path.join(HERE, 'ss/citiesx010g'),
                         encoding='latin-1', encodingErrors='replace')
    for sr in r.iterShapeRecords():
        rec = sr.record
        lon, lat = rec['LONGITUDE'], rec['LATITUDE']
        if not (W <= lon <= E and S <= lat <= N):
            continue
        pop = int(rec['POP_2010'] or 0)
        # Rank drives both the zoom a name appears at and its size. Blacksburg and
        # Christiansburg are the two anchors; the hamlets are there so the map does
        # not look empty between them, not because anyone is going to Riner.
        rank = 1 if pop >= 20000 else 2 if pop >= 5000 else 3 if pop >= 1000 else 4
        sink.add({'type': 'Point', 'coordinates': [round(lon, 5), round(lat, 5)]},
                 {'name': (rec['NAME'] or '').strip(), 'pop': pop, 'rank': rank,
                  'kind': 'town'})
    r.close()

    # Ridges and summits. Brush Mountain is the horizon from most of Blacksburg,
    # and naming the ridges is the difference between "a valley" and "this valley".
    want = {'Ridge', 'Summit', 'Range', 'Gap'}
    with open(os.path.join(HERE, 'gnis/Text/DomesticNames_VA.txt'),
              encoding='utf-8-sig') as f:
        cols = f.readline().rstrip('\n').split('|')
        ix = {c: i for i, c in enumerate(cols)}
        for row in f:
            p = row.rstrip('\n').split('|')
            if len(p) < len(cols) or p[ix['feature_class']] not in want:
                continue
            try:
                lat = float(p[ix['prim_lat_dec']])
                lon = float(p[ix['prim_long_dec']])
            except ValueError:
                continue
            if not (W <= lon <= E and S <= lat <= N):
                continue
            sink.add({'type': 'Point', 'coordinates': [round(lon, 5), round(lat, 5)]},
                     {'name': p[ix['feature_name']], 'kind': 'terrain',
                      'terrain_class': p[ix['feature_class']]})
    sink.close()


if __name__ == '__main__':
    which = sys.argv[1:] or ['land', 'water', 'places', 'rail', 'roads']
    for job in which:
        print(job)
        globals()['do_' + job]()
