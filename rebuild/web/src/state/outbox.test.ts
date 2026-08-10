/**
 * The promise the offline queue makes: a walk queued with the network down is
 * retried forever with the same client_walk_id, and lands exactly once.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enqueue, flushOnce, list } from './outbox'
import { outbox } from '../data/idb'

const BODY = {
  device_id: '11111111-2222-3333-4444-555555555555',
  client_walk_id: 'walk-abc-123',
  display_name: null,
  started_at: '2026-08-10T14:00:00Z',
  seg_ids: [1, 2, 3],
}

/** Stands in for the server, including its idempotency rule. */
function fakeServer() {
  const seen = new Map<string, { walk_id: string; newly_covered: number[] }>()
  const posts: { client_walk_id: string; seg_ids: number[] }[] = []
  let offlineFor = 0

  const fetchImpl = async (_url: string, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body))
    posts.push({ client_walk_id: body.client_walk_id, seg_ids: body.seg_ids })
    if (offlineFor > 0) {
      offlineFor -= 1
      throw new TypeError('Failed to fetch')
    }
    const key = `${body.device_id}:${body.client_walk_id}`
    const first = !seen.has(key)
    if (first) seen.set(key, { walk_id: 'walk-uuid-1', newly_covered: body.seg_ids })
    const res = first ? seen.get(key)! : { walk_id: 'walk-uuid-1', newly_covered: [] }
    return new Response(JSON.stringify(res), { status: 200, headers: { 'content-type': 'application/json' } })
  }

  return {
    posts,
    seen,
    setOffline: (n: number) => {
      offlineFor = n
    },
    install: () => vi.stubGlobal('fetch', fetchImpl as unknown as typeof fetch),
  }
}

describe('the offline queue', () => {
  let server: ReturnType<typeof fakeServer>

  beforeEach(async () => {
    for (const item of await list()) await outbox.del(item.client_walk_id)
    server = fakeServer()
    server.install()
  })

  afterEach(() => vi.unstubAllGlobals())

  it('holds a walk while the network is down and sends it once when it returns', async () => {
    server.setOffline(3)
    await enqueue(BODY)

    // Three failed attempts. The walk stays put, nothing is lost.
    for (let i = 0; i < 3; i++) {
      const r = await flushOnce()
      expect(r.sent).toBe(0)
      expect(r.pending).toBe(1)
    }

    const fourth = await flushOnce()
    expect(fourth.sent).toBe(1)

    // Every attempt carried the same client_walk_id. That is what makes the
    // retries safe.
    expect(server.posts).toHaveLength(4)
    expect(new Set(server.posts.map((p) => p.client_walk_id))).toEqual(new Set(['walk-abc-123']))

    // The server accepted it once.
    expect(server.seen.size).toBe(1)

    // Later passes do not send it again.
    await flushOnce()
    await flushOnce()
    expect(server.posts).toHaveLength(4)

    const items = await list()
    expect(items[0].status).toBe('sent')
    expect(items[0].newly_covered).toEqual([1, 2, 3])
  })

  it('sends a walk once even when the queue is flushed twice over', async () => {
    await enqueue(BODY)
    await enqueue(BODY) // a double tap must not double the walk
    expect((await list()).length).toBe(1)
    await Promise.all([flushOnce(), flushOnce()])
    expect(server.seen.size).toBe(1)
  })

  it('stops retrying a walk the server rejects outright, and keeps it', async () => {
    vi.stubGlobal('fetch', async () =>
      new Response(JSON.stringify({ message: 'A walk needs at least one street.' }), { status: 400 }),
    )
    await enqueue({ ...BODY, client_walk_id: 'walk-bad', seg_ids: [] })
    const r = await flushOnce()
    expect(r.sent).toBe(0)
    const item = (await list()).find((i) => i.client_walk_id === 'walk-bad')
    expect(item?.status).toBe('stuck')
    expect(item?.last_error).toContain('at least one street')
  })
})
