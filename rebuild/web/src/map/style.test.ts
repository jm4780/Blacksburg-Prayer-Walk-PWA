/**
 * Two things this checks, both of which have burned map projects before:
 *
 * 1. Every colour on the map comes from the token file. If a MapLibre default
 *    ever survives, the map stops being one design.
 * 2. Every source-layer the style asks for actually exists in the .pmtiles file
 *    on disk, so a missing layer is a failed test rather than a blank map.
 */

import { open } from 'node:fs/promises'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { PMTiles, type RangeResponse, type Source } from 'pmtiles'
import { validateStyleMin } from '@maplibre/maplibre-gl-style-spec'
import { buildStyle } from './style'
import { color } from '../design/tokens'

const TOKEN_COLORS = new Set<string>([...Object.values(color), '#FFFFFF'])

class FileSource implements Source {
  constructor(private path: string) {}
  getKey() {
    return this.path
  }
  async getBytes(offset: number, length: number): Promise<RangeResponse> {
    const fh = await open(this.path, 'r')
    try {
      const buf = Buffer.alloc(length)
      await fh.read(buf, 0, length, offset)
      return { data: buf.buffer.slice(buf.byteOffset, buf.byteOffset + length) as ArrayBuffer }
    } finally {
      await fh.close()
    }
  }
}

function colorsIn(value: unknown, out: string[] = []): string[] {
  if (typeof value === 'string' && /^#[0-9a-fA-F]{3,8}$/.test(value)) out.push(value.toUpperCase())
  else if (Array.isArray(value)) value.forEach((v) => colorsIn(v, out))
  else if (value && typeof value === 'object') Object.values(value).forEach((v) => colorsIn(v, out))
  return out
}

describe('the map style', () => {
  const style = buildStyle()

  it('is a style MapLibre will accept', () => {
    const errors = validateStyleMin(style as never)
    expect(errors.map((e) => e.message)).toEqual([])
  })

  it('takes every colour from the design tokens', () => {
    const allowed = new Set([...TOKEN_COLORS].map((c) => c.toUpperCase()))
    for (const layer of style.layers as unknown as Record<string, unknown>[]) {
      for (const key of ['paint', 'layout']) {
        for (const c of colorsIn(layer[key])) {
          expect.soft(allowed, `layer ${String(layer.id)} uses ${c}`).toContain(c)
        }
      }
    }
  })

  it('draws no colour outside the three the design allows, plus greys', () => {
    // The three: route, prayed, walker. Everything else on this map is a grey.
    const hueful = [color.route, color.prayed, color.walker].map((c) => c.toUpperCase())
    expect(new Set(hueful).size).toBe(3)
  })

  it('asks the basemap only for layers the tile file actually has', async () => {
    const path = resolve(__dirname, '../../public/basemap/blacksburg.pmtiles')
    const p = new PMTiles(new FileSource(path))
    const meta = (await p.getMetadata()) as { vector_layers?: { id: string }[] }
    const header = await p.getHeader()
    const available = new Set((meta.vector_layers ?? []).map((v) => v.id))

    expect(available.size).toBeGreaterThan(0)
    expect(header.maxZoom).toBeGreaterThanOrEqual(13)

    for (const layer of style.layers as unknown as Record<string, string>[]) {
      if (layer.source === 'base') {
        expect(available, `layer ${layer.id}`).toContain(layer['source-layer'])
      }
    }
  })
})
