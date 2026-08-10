/**
 * The whole map style, built from design tokens. Nothing here is a MapLibre
 * default: every layer that draws a pixel is listed below and gets its colour
 * from src/design/tokens.ts.
 *
 * Tiles come from the file at /basemap/blacksburg.pmtiles, on the device. There
 * is no tile server anywhere in this app.
 */

import type { StyleSpecification } from 'maplibre-gl'
import { color, mapWidth } from '../design/tokens'

export const BASEMAP_URL = 'pmtiles:///basemap/blacksburg.pmtiles'
export const FONT = ['Prayer Walk Regular']

export const BLACKSBURG = { lon: -80.4139, lat: 37.2296 }
export const BLACKSBURG_BOUNDS: [number, number, number, number] = [
  -80.52, 37.16, -80.34, 37.31,
]

const EMPTY = { type: 'FeatureCollection', features: [] } as const

export function buildStyle(): StyleSpecification {
  return {
    version: 8,
    name: 'Blacksburg Prayer Walk',
    glyphs: '/fonts/{fontstack}/{range}.pbf',
    sources: {
      base: {
        type: 'vector',
        url: BASEMAP_URL,
        attribution: 'USGS National Map',
      },
      boundary: { type: 'geojson', data: '/basemap/boundary.json' },
      network: { type: 'geojson', data: EMPTY as never, promoteId: 'seg_id' },
      route: { type: 'geojson', data: EMPTY as never },
      walker: { type: 'geojson', data: EMPTY as never },
    },
    layers: [
      // ---- ground ------------------------------------------------------
      { id: 'ground', type: 'background', paint: { 'background-color': color.ground } },
      {
        id: 'land',
        type: 'fill',
        source: 'base',
        'source-layer': 'land',
        paint: { 'fill-color': color.land },
      },
      {
        id: 'water',
        type: 'fill',
        source: 'base',
        'source-layer': 'water',
        paint: { 'fill-color': color.water },
      },
      // A near-black ground leaves almost no room to go darker, so water on its
      // own sits 1.03:1 below it and cannot be seen. The shoreline is what makes
      // the hole read. Still value, still no hue.
      {
        id: 'water-edge',
        type: 'line',
        source: 'base',
        'source-layer': 'water',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': color.waterEdge,
          'line-width': ['interpolate', ['linear'], ['zoom'], 9, 0.6, 13, 1.0, 17, 1.6],
        },
      },
      {
        id: 'waterway',
        type: 'line',
        source: 'base',
        'source-layer': 'waterway',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': color.waterway,
          'line-width': [
            'interpolate',
            ['linear'],
            ['zoom'],
            8, ['case', ['to-boolean', ['get', 'major']], 0.8, 0.3],
            11, ['case', ['to-boolean', ['get', 'major']], 1.6, 0.5],
            14, ['case', ['to-boolean', ['get', 'major']], 2.4, 1.0],
            17, ['case', ['to-boolean', ['get', 'major']], 4.4, 1.8],
          ],
        },
      },
      {
        id: 'rail',
        type: 'line',
        source: 'base',
        'source-layer': 'rail',
        minzoom: 11,
        paint: {
          'line-color': color.rail,
          'line-width': ['interpolate', ['linear'], ['zoom'], 11, 0.5, 14, 0.8, 17, 1.3],
          'line-dasharray': [2.5, 3],
        },
      },

      // ---- the regional road network, greyscale by importance ----------
      road('road-minor', ['in', ['get', 'class'], ['literal', ['minor', 'link', 'tertiary']]], color.roadMinor, 12, [0.6, 1.1, 2.0, 3.4]),
      road('road-secondary', ['==', ['get', 'class'], 'secondary'], color.roadSecondary, 10, [0.8, 1.5, 2.8, 4.6]),
      road('road-primary', ['==', ['get', 'class'], 'primary'], color.roadPrimary, 9, [0.95, 1.75, 3.2, 5.4]),
      road('road-trunk', ['==', ['get', 'class'], 'trunk'], color.roadTrunk, 7, [1.15, 2.1, 3.9, 6.5]),
      road('road-motorway', ['==', ['get', 'class'], 'motorway'], color.roadMotorway, 7, [1.35, 2.5, 4.6, 7.6]),

      {
        id: 'town-line',
        type: 'line',
        source: 'boundary',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': color.boundary,
          // 0.34 on a 1px dash was a boundary nobody could find. The town edge
          // is the one piece of civic geometry on this map and it should be
          // quietly legible: a dashed hairline you can follow if you look for it.
          'line-opacity': 0.85,
          'line-dasharray': [3, 4],
          'line-width': ['interpolate', ['linear'], ['zoom'], 9, 1.0, 12, 1.4, 16, 1.8],
        },
      },

      // ---- prayer coverage: the only place colour means anything --------
      // Prayed or not is a feature state, which MapLibre allows in paint but
      // not in a filter, so one layer draws both and switches colour.
      {
        id: 'seg-coverage',
        type: 'line',
        source: 'network',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': [
            'case',
            ['boolean', ['feature-state', 'prayed'], false],
            color.prayed,
            color.unprayed,
          ],
          'line-width': mapWidth.segment as never,
          'line-opacity': [
            'case',
            ['boolean', ['feature-state', 'prayed'], false],
            0.95,
            0.85,
          ],
        },
      },

      // A fat invisible line so a thumb can hit a street on a phone.
      {
        id: 'seg-hit',
        type: 'line',
        source: 'network',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': color.ground, 'line-opacity': 0, 'line-width': 24 },
      },

      // ---- the route you were given ------------------------------------
      {
        id: 'route-casing',
        type: 'line',
        source: 'route',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': color.groundSunk,
          'line-width': mapWidth.routeCasing as never,
          'line-opacity': 0.9,
        },
      },
      {
        id: 'route-line',
        type: 'line',
        source: 'route',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': color.route,
          'line-width': mapWidth.route as never,
          'line-opacity': 0.92,
        },
      },

      // ---- streets you have walked on this walk, not yet on the town map
      {
        id: 'seg-claimed',
        type: 'line',
        source: 'network',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': color.prayed,
          'line-width': mapWidth.segmentWide as never,
          'line-opacity': ['case', ['boolean', ['feature-state', 'claimed'], false], 1, 0],
        },
      },
      {
        id: 'seg-claimed-core',
        type: 'line',
        source: 'network',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          // Was a raw #FFFFFF, the one hard-coded colour left on the map and a
          // second white competing with the walker. A street you claimed is
          // still a prayed street: it belongs to the amber, only brighter.
          'line-color': color.prayedLift,
          'line-width': mapWidth.segmentCore as never,
          'line-opacity': ['case', ['boolean', ['feature-state', 'claimed'], false], 0.85, 0],
        },
      },

      // ---- labels: small, sparse, quiet --------------------------------
      {
        id: 'label-waterway',
        type: 'symbol',
        source: 'base',
        'source-layer': 'waterway',
        minzoom: 11,
        filter: ['all', ['has', 'name'], ['to-boolean', ['get', 'major']]],
        layout: {
          'symbol-placement': 'line',
          'text-field': ['get', 'name'],
          'text-font': FONT,
          'text-size': ['interpolate', ['linear'], ['zoom'], 11, 9, 15, 11],
          'text-letter-spacing': 0.12,
          'text-max-angle': 32,
          'symbol-spacing': 420,
        },
        paint: {
          'text-color': color.labelFaint,
          'text-halo-color': color.ground,
          'text-halo-width': 1.1,
        },
      },
      {
        id: 'label-shield',
        type: 'symbol',
        source: 'base',
        'source-layer': 'roads',
        minzoom: 11,
        filter: [
          'all',
          ['has', 'ref'],
          ['in', ['get', 'class'], ['literal', ['motorway', 'trunk', 'primary']]],
        ],
        layout: {
          'symbol-placement': 'line',
          'text-field': ['get', 'ref'],
          'text-font': FONT,
          'text-size': ['interpolate', ['linear'], ['zoom'], 11, 9, 15, 11.5],
          'text-letter-spacing': 0.05,
          'text-max-angle': 30,
          'text-padding': 16,
          'symbol-spacing': 700,
        },
        paint: {
          'text-color': color.labelQuiet,
          'text-halo-color': color.ground,
          'text-halo-width': 1.4,
        },
      },
      {
        id: 'label-terrain',
        type: 'symbol',
        source: 'base',
        'source-layer': 'place',
        minzoom: 11.5,
        maxzoom: 14,
        filter: ['==', ['get', 'kind'], 'terrain'],
        layout: {
          'text-field': ['get', 'name'],
          'text-font': FONT,
          'text-size': 9.5,
          'text-letter-spacing': 0.16,
          'text-max-width': 8,
          'text-padding': 8,
        },
        paint: {
          'text-color': color.labelFaint,
          'text-halo-color': color.ground,
          'text-halo-width': 1.1,
        },
      },
      {
        id: 'label-place',
        type: 'symbol',
        source: 'base',
        'source-layer': 'place',
        minzoom: 8,
        maxzoom: 14,
        filter: ['==', ['get', 'kind'], 'town'],
        layout: {
          'text-field': ['get', 'name'],
          'text-font': FONT,
          'text-transform': ['step', ['get', 'rank'], 'uppercase', 3, 'none'],
          'text-size': [
            'interpolate', ['linear'], ['zoom'],
            8, ['step', ['get', 'rank'], 10, 2, 9, 3, 8],
            13, ['step', ['get', 'rank'], 13, 2, 11.5, 3, 10],
          ],
          'text-letter-spacing': ['step', ['get', 'rank'], 0.2, 3, 0.08],
          'text-max-width': 7,
          'text-padding': 10,
        },
        paint: {
          'text-color': [
            'case',
            ['==', ['get', 'name'], 'Blacksburg'], color.labelPlace,
            ['step', ['get', 'rank'], color.labelQuiet, 3, color.labelFaint],
          ],
          'text-halo-color': color.ground,
          'text-halo-width': 1.3,
        },
      },
      // Street names, only close in, and only where a walker needs them.
      {
        id: 'label-street',
        type: 'symbol',
        source: 'network',
        // Was 15 with 260px spacing, which put ten or more names on one phone
        // screen and repeated half of them. A street name is a thing you look
        // for, not a thing you read; one instance per street per screen is the
        // whole job.
        minzoom: 15.5,
        layout: {
          'symbol-placement': 'line',
          'text-field': ['get', 'name'],
          'text-font': FONT,
          'text-size': ['interpolate', ['linear'], ['zoom'], 15.5, 9.5, 18, 11],
          'text-letter-spacing': 0.06,
          'text-max-angle': 30,
          'symbol-spacing': 620,
          'text-padding': 14,
        },
        paint: {
          // One colour, whatever the prayer state. The line underneath already
          // says prayed or not; tinting the name as well drew dark brown text
          // on top of a bright amber line, which was the least readable thing
          // on the map, and spent the prayed colour twice for one meaning.
          'text-color': color.labelQuiet,
          'text-halo-color': color.ground,
          'text-halo-width': 1.6,
        },
      },

      // ---- you ----------------------------------------------------------
      {
        id: 'walker-accuracy',
        type: 'circle',
        source: 'walker',
        paint: {
          'circle-color': color.walker,
          'circle-opacity': 0.07,
          'circle-radius': [
            'interpolate', ['linear'], ['zoom'],
            13, 6, 16, ['max', 10, ['/', ['get', 'accuracy_m'], 3]], 19, ['max', 18, ['get', 'accuracy_m']],
          ],
          'circle-stroke-color': color.walker,
          'circle-stroke-opacity': 0.22,
          'circle-stroke-width': 1,
        },
      },
      {
        id: 'walker-dot',
        type: 'circle',
        source: 'walker',
        paint: {
          'circle-color': color.walker,
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 12, 5, 16, 7.5, 19, 9.5],
          'circle-stroke-color': color.groundSunk,
          'circle-stroke-width': 3,
        },
      },
    ] as never,
  } as StyleSpecification
}

function road(
  id: string,
  filter: unknown,
  lineColor: string,
  minzoom: number,
  widths: [number, number, number, number],
) {
  return {
    id,
    type: 'line',
    source: 'base',
    'source-layer': 'roads',
    minzoom,
    filter,
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': lineColor,
      'line-width': [
        'interpolate', ['linear'], ['zoom'],
        12, widths[0], 14, widths[1], 16, widths[2], 18, widths[3],
      ],
    },
  }
}
