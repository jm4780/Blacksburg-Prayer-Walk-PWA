/**
 * The self-hosted vector basemap.
 *
 * This is the piece docs/02-technical-plan.md §1.1 specified at the start and that
 * never got built: "MapLibre GL JS + Protomaps `.pmtiles` basemap served as a static
 * file". Until now the ground under the prayer data was drawn entirely from the
 * town's own GeoJSON, which is why Blacksburg looked like it floated in a void — the
 * town publishes the town, and nothing beyond it.
 *
 * One file, `/basemap/blacksburg.pmtiles`, covering roughly 50 km in every direction.
 * No API key, no tile host, no vendor account for the church to manage, and one cache
 * entry for the service worker to hold.
 *
 * WHY A CUSTOM SOURCE, AND NOT pmtiles' OWN `FetchSource`
 *
 * PMTiles is normally read with HTTP range requests, and `FetchSource` does exactly
 * that. It also treats a 200 answer to a range request as a misconfigured host, and
 * throws:
 *
 *     if (status === 200 && (!len || +len > length)) throw new Error(...)
 *
 * A Workbox precache serves precisely that — the whole file, status 200 — for any
 * request to a precached URL, range header or not. So the stock source works online
 * and throws the moment the app goes offline, which is the one situation this app
 * exists to survive.
 *
 * `ArchiveSource` reads that 200 as what it actually is: the entire archive,
 * delivered early. It keeps the buffer and answers every later read from memory.
 * Online with a cold cache it uses ranges and pulls a few tens of kilobytes; offline,
 * or behind the service worker, it takes the whole file once and never touches the
 * network again. Hosts that ignore `Range` altogether fall into the same branch, for
 * free.
 */
import { addProtocol } from 'maplibre-gl'
import { PMTiles, Protocol } from 'pmtiles'

/** Where the archive lives, and the key the style's `pmtiles://` URL resolves to. */
export const ARCHIVE_URL = '/basemap/blacksburg.pmtiles'

/** The style document MapLibre loads. Overridable per deployment — see MapView. */
export const DEFAULT_STYLE_URL = '/basemap/blacksburg.json'

class ArchiveSource {
  /** The whole archive, once some response has handed it to us. */
  private whole: ArrayBuffer | null = null
  /** Dedupes the full fetch: MapLibre asks for a dozen tiles at once. */
  private pending: Promise<ArrayBuffer> | null = null

  constructor(private readonly url: string) {}

  getKey() {
    return this.url
  }

  async getBytes(offset: number, length: number, signal?: AbortSignal) {
    if (this.whole) return { data: this.whole.slice(offset, offset + length) }
    if (this.pending) {
      this.whole = await this.pending
      return { data: this.whole.slice(offset, offset + length) }
    }

    const resp = await fetch(this.url, {
      signal,
      headers: { range: `bytes=${offset}-${offset + length - 1}` },
    })
    if (resp.status === 206) return { data: await resp.arrayBuffer() }
    if (resp.status === 200) {
      this.pending = resp.arrayBuffer()
      this.whole = await this.pending
      this.pending = null
      return { data: this.whole.slice(offset, offset + length) }
    }
    throw new Error(`Basemap archive ${this.url} returned ${resp.status}`)
  }
}

let registered = false

/**
 * Teach MapLibre to read `pmtiles://` source URLs.
 *
 * Idempotent, and safe to call before any map exists. Our own archive is seeded with
 * `ArchiveSource`; any other `pmtiles://` URL a deployment points at falls through to
 * pmtiles' default range-request source, which is the right behaviour for a host that
 * does support byte serving.
 */
export function registerBasemapProtocol() {
  if (registered) return
  registered = true
  const protocol = new Protocol()
  protocol.add(new PMTiles(new ArchiveSource(ARCHIVE_URL) as any))
  addProtocol('pmtiles', protocol.tile)
}
