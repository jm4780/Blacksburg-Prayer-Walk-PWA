#!/usr/bin/env bash
#
# Rebuild web/public/basemap/blacksburg.pmtiles from public USGS downloads.
#
#   pipeline/basemap/build.sh [workdir]
#
# Needs: tippecanoe (apt install tippecanoe), python3 with pyshp, ~2 GB of scratch
# and a few minutes. Nothing here is committed except this script, extract.py and
# filters.json — the sources are 500 MB of public-domain shapefiles that anyone can
# fetch again, and the output is 4.4 MB that lives in the app.
#
# Every source below is US federal government work and therefore public domain
# (17 U.S.C. §105). There is deliberately no OpenStreetMap in this pipeline: see
# docs/01-data-audit.md §2.4 and docs/20 §2 for why the ODbL is kept away from this
# repository entirely.
set -euo pipefail

WORK="${1:-/tmp/bpw-basemap}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$(cd "$HERE/../.." && pwd)/web/public/basemap/blacksburg.pmtiles"
S3=https://prd-tnm.s3.amazonaws.com/StagedProducts

mkdir -p "$WORK"
cd "$WORK"

fetch() {  # url, destination
  [ -s "$2" ] || curl -fsSL --retry 4 -o "$2" "$1"
  echo "  $2  $(du -h "$2" | cut -f1)"
}

echo "sources"
# Roads and railways, statewide. The road file is the big one; it is also the only
# source of a complete street fabric outside the town limits.
fetch "$S3/Tran/Shape/TRAN_Virginia_State_Shape.zip" tran_va.zip
# Hydrography for HUC-4 subregion 0505 — the New River basin. A tenth the size of
# the statewide product and it contains every creek that matters here.
fetch "$S3/Hydrography/NHD/HU4/Shape/NHD_H_0505_HU4_Shape.zip" nhd_0505.zip
# Place names, for the ridges and gaps that the small-scale cities file has no idea
# about. Brush Mountain is the horizon from most of Blacksburg.
fetch "$S3/GeographicNames/DomesticNames/DomesticNames_VA_Text.zip" gnis_va.zip
# Federal lands (Jefferson National Forest) and populated places with 2010 counts,
# both from the 1:1,000,000 Small-scale collection. Coarse, and correct at the only
# zooms they are drawn at.
fetch "$S3/Small-scale/data/Boundaries/fedlanp010g.shp_nt00966.tar.gz" fedlan.tar.gz
fetch "$S3/Small-scale/data/Boundaries/citiesx010g_shp_nt00962.tar.gz" cities.tar.gz
# Incorporated places, for the Blacksburg municipal limits the basemap draws as its
# town boundary. Census-sourced and public domain, which is the whole reason it can be
# checked in — the Town's own boundary file cannot (docs/05, G1).
fetch "$S3/GovtUnit/Shape/GOVTUNIT_Virginia_State_Shape.zip" govt_va.zip

echo "unpack"
unzip -o -q -j tran_va.zip "Shape/Trans_RoadSegment_*" "Shape/Trans_RailFeature.*" -d tran
unzip -o -q -j nhd_0505.zip "Shape/NHDFlowline.*" "Shape/NHDWaterbody.*" "Shape/NHDArea.*" -d nhd
unzip -o -q gnis_va.zip -d gnis
unzip -o -q -j govt_va.zip "Shape/GU_IncorporatedPlace.*" -d gu
mkdir -p ss && tar xzf fedlan.tar.gz -C ss && tar xzf cities.tar.gz -C ss

echo "extract"
cp "$HERE/extract.py" .
python3 extract.py

echo "tile"
# -z13 rather than -z14 halves the archive for no visible loss: MapLibre overzooms
# vector tiles cleanly, and at z13 a tile unit is about 1.2 m on the ground.
tippecanoe -o blacksburg.pmtiles --force \
  -Z6 -z13 \
  --clip-bounding-box=-81.00,36.80,-79.80,37.65 \
  --simplification=4 \
  --drop-densest-as-needed \
  -j "$(cat "$HERE/filters.json")" \
  -N "Blacksburg Regional Basemap" \
  -A "USGS The National Map" \
  -L land:ndjson/land.geojsonl \
  -L water:ndjson/water.geojsonl \
  -L waterway:ndjson/waterway.geojsonl \
  -L roads:ndjson/roads.geojsonl \
  -L rail:ndjson/rail.geojsonl \
  -L place:ndjson/place.geojsonl

cp blacksburg.pmtiles "$OUT"
echo "wrote $OUT  $(du -h "$OUT" | cut -f1)"

# The municipal limits, extracted from the GovtUnit download and written next to the
# archive. Cheap, and regenerating it here re-caches the boundary so a later rebuild
# does not need the 69 MB statewide file again.
( cd "$(cd "$HERE/../.." && pwd)" && python3 -m pipeline.basemap.boundary "$WORK/gu/GU_IncorporatedPlace" )
