#!/usr/bin/env bash
# One-time setup for the rebuild/ app in a Codespace.
#
# Everything the app needs is already in this repository: the town boundary and
# the map archive are committed, so nothing is downloaded from a GIS service.
# That is not a design preference, it is the constraint the app was built under.
# See rebuild/docs/data-provenance.md.
set -euo pipefail
cd "$(dirname "$0")/../.."

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

say "1/5  Installing PostGIS"
sudo apt-get update -qq
# Debian bookworm ships Postgres 15. Ask apt what it actually installed rather
# than pinning a version that may move under us.
sudo apt-get install -y -qq postgresql postgresql-client >/dev/null
PGVER="$(ls /usr/lib/postgresql | sort -n | tail -1)"
sudo apt-get install -y -qq "postgresql-${PGVER}-postgis-3" >/dev/null
echo "postgres ${PGVER} with postgis"

say "2/5  Starting the database"
sudo pg_ctlcluster "$PGVER" main start 2>/dev/null || true
# Local connections trust, so no password lives in a config file anywhere.
HBA="/etc/postgresql/${PGVER}/main/pg_hba.conf"
sudo sed -i 's/^\(local\s\+all\s\+all\s\+\)peer/\1trust/' "$HBA"
sudo sed -i 's/^\(host\s\+all\s\+all\s\+127.0.0.1\/32\s\+\)scram-sha-256/\1trust/' "$HBA"
sudo sed -i 's/^\(host\s\+all\s\+all\s\+::1\/128\s\+\)scram-sha-256/\1trust/' "$HBA"
sudo pg_ctlcluster "$PGVER" main restart
until pg_isready -q -h 127.0.0.1; do sleep 1; done
sudo -u postgres psql -qc "create database bbg" 2>/dev/null || true
sudo -u postgres psql -qd bbg -c "create extension if not exists postgis"
echo "database bbg ready"

say "3/5  Installing dependencies"
pip install -q -r rebuild/api/requirements.txt
pip install -q pmtiles mapbox-vector-tile shapely pyproj
(cd rebuild/web && npm ci --silent 2>/dev/null || npm install --silent)

say "4/5  Building the street network"
# Reads the committed .pmtiles archive and the town boundary, and writes
# rebuild/data/out/network.geojson. About 1,600 segments.
python3 rebuild/data/pipeline/extract_network.py
python3 rebuild/db/load_network.py

say "5/5  Building the app"
(cd rebuild/web && npm run build)

say "Ready. It starts on its own when you open this Codespace."
