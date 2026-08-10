/**
 * The offline queue.
 *
 * A confirmed walk is written to IndexedDB first and sent second. If the phone
 * has no signal, the walk sits in the queue and is retried forever with the
 * same client_walk_id, which is what makes retrying safe: the server keys on
 * (device_id, client_walk_id), so ten deliveries of the same walk commit once.
 *
 * Nothing enters this queue that the walker has not confirmed by tapping.
 */

import { ApiError, api } from '../data/api'
import { outbox } from '../data/idb'
import type { OutboxItem } from '../types'

type Listener = (items: OutboxItem[]) => void
const listeners = new Set<Listener>()

export function subscribe(fn: Listener): () => void {
  listeners.add(fn)
  void list().then(fn)
  return () => listeners.delete(fn)
}

async function announce() {
  const items = await list()
  listeners.forEach((fn) => fn(items))
}

export async function list(): Promise<OutboxItem[]> {
  const items = await outbox.all<OutboxItem>()
  return items.sort((a, b) => a.queued_at.localeCompare(b.queued_at))
}

export async function enqueue(body: OutboxItem['body']): Promise<OutboxItem> {
  const existing = await outbox.get<OutboxItem>(body.client_walk_id)
  if (existing) return existing
  const item: OutboxItem = {
    client_walk_id: body.client_walk_id,
    body,
    attempts: 0,
    queued_at: new Date().toISOString(),
    last_error: null,
    status: 'pending',
  }
  await outbox.put(item)
  await announce()
  return item
}

/** One pass over the queue. Returns how many are still waiting. */
export async function flushOnce(): Promise<{ sent: number; pending: number; stuck: number }> {
  const items = await list()
  let sent = 0
  let stuck = 0
  let pending = 0

  for (const item of items) {
    if (item.status === 'sent') continue
    if (item.status === 'stuck') {
      stuck += 1
      continue
    }
    try {
      const res = await api.walk(item.body)
      item.status = 'sent'
      item.walk_id = res.walk_id
      item.newly_covered = res.newly_covered
      item.last_error = null
      item.attempts += 1
      await outbox.put(item)
      sent += 1
    } catch (e) {
      item.attempts += 1
      item.last_error = e instanceof Error ? e.message : String(e)
      if (e instanceof ApiError && !e.retryable) {
        // Retrying will not fix a rejected body. Stop, and say so on screen.
        item.status = 'stuck'
        stuck += 1
      } else {
        pending += 1
      }
      await outbox.put(item)
    }
  }
  if (sent || stuck) await prune()
  await announce()
  return { sent, pending, stuck }
}

/** Keep the last few sent walks for the screen, drop the rest. */
async function prune() {
  const items = await list()
  const done = items.filter((i) => i.status === 'sent')
  for (const item of done.slice(0, Math.max(0, done.length - 5))) {
    await outbox.del(item.client_walk_id)
  }
}

let timer: ReturnType<typeof setTimeout> | null = null
let delay = 0

const MIN_DELAY = 4000
const MAX_DELAY = 60000

/** Retries forever, backing off to a minute, and jumps the moment the phone
 *  says it is back online. */
export function startFlushLoop(): () => void {
  let stopped = false

  const tick = async () => {
    if (stopped) return
    let waiting = 0
    try {
      const r = await flushOnce()
      waiting = r.pending
    } catch {
      waiting = 1
    }
    delay = waiting === 0 ? MAX_DELAY : Math.min(MAX_DELAY, Math.max(MIN_DELAY, delay * 2 || MIN_DELAY))
    timer = setTimeout(tick, delay)
  }

  const onOnline = () => {
    delay = 0
    if (timer) clearTimeout(timer)
    void tick()
  }

  void tick()
  if (typeof window !== 'undefined') {
    window.addEventListener('online', onOnline)
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') onOnline()
    })
  }

  return () => {
    stopped = true
    if (timer) clearTimeout(timer)
    if (typeof window !== 'undefined') window.removeEventListener('online', onOnline)
  }
}
