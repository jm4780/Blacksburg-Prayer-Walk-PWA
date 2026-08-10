/**
 * The walk in progress, and the device identity.
 *
 * Every change is written to IndexedDB before it reaches the screen, so a
 * reload, a phone call, or a battery-saver kill picks up exactly where the
 * walker left off.
 */

import { kv } from '../data/idb'
import type { WalkState } from '../types'

const WALK_KEY = 'walk:current'
const DEVICE_KEY = 'device:id'
const NAME_KEY = 'device:name'

export function newId(): string {
  const c = globalThis.crypto
  if (c && 'randomUUID' in c) return c.randomUUID()
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (ch) => {
    const r = (Math.random() * 16) | 0
    const v = ch === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

export function emptyWalk(): WalkState {
  return {
    phase: 'idle',
    client_walk_id: newId(),
    started_at: null,
    minutes: 30,
    start: null,
    route: null,
    claimed: [],
    suggested: [],
    manual: false,
    trace: [],
  }
}

export async function deviceId(): Promise<string> {
  let id = await kv.get<string>(DEVICE_KEY)
  if (!id) {
    id = newId()
    await kv.set(DEVICE_KEY, id)
  }
  return id
}

export async function displayName(): Promise<string> {
  return (await kv.get<string>(NAME_KEY)) ?? ''
}

export async function setDisplayName(name: string): Promise<void> {
  await kv.set(NAME_KEY, name)
}

export async function loadWalk(): Promise<WalkState> {
  const w = await kv.get<WalkState>(WALK_KEY)
  if (!w) return emptyWalk()
  return { ...emptyWalk(), ...w }
}

export async function saveWalk(w: WalkState): Promise<void> {
  await kv.set(WALK_KEY, w)
}

export async function clearWalk(): Promise<void> {
  await kv.del(WALK_KEY)
}
