/**
 * A very small IndexedDB wrapper. Two stores:
 *
 *   kv      the walk in progress, the device id, the cached network
 *   outbox  walks waiting to reach the server, keyed by client_walk_id
 *
 * Everything the app knows lives here, not in memory, so closing the app in the
 * middle of a walk costs nothing.
 */

const DB_NAME = 'prayer-walk'
const DB_VERSION = 1

let dbp: Promise<IDBDatabase> | null = null

function open(): Promise<IDBDatabase> {
  if (dbp) return dbp
  dbp = new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains('kv')) db.createObjectStore('kv')
      if (!db.objectStoreNames.contains('outbox'))
        db.createObjectStore('outbox', { keyPath: 'client_walk_id' })
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
  return dbp
}

function tx<T>(store: string, mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return open().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const t = db.transaction(store, mode)
        const req = fn(t.objectStore(store))
        req.onsuccess = () => resolve(req.result)
        req.onerror = () => reject(req.error)
      }),
  )
}

export const kv = {
  get: <T>(key: string): Promise<T | undefined> => tx<T>('kv', 'readonly', (s) => s.get(key) as IDBRequest<T>),
  set: (key: string, value: unknown): Promise<unknown> =>
    tx('kv', 'readwrite', (s) => s.put(value, key) as IDBRequest<unknown>),
  del: (key: string): Promise<unknown> => tx('kv', 'readwrite', (s) => s.delete(key) as IDBRequest<unknown>),
}

export const outbox = {
  all: <T>(): Promise<T[]> => tx<T[]>('outbox', 'readonly', (s) => s.getAll() as IDBRequest<T[]>),
  get: <T>(id: string): Promise<T | undefined> =>
    tx<T>('outbox', 'readonly', (s) => s.get(id) as IDBRequest<T>),
  put: (item: unknown): Promise<unknown> =>
    tx('outbox', 'readwrite', (s) => s.put(item) as IDBRequest<unknown>),
  del: (id: string): Promise<unknown> =>
    tx('outbox', 'readwrite', (s) => s.delete(id) as IDBRequest<unknown>),
}

/** Test seam. Closes and drops the handle so a fresh database can be opened. */
export function _resetForTests() {
  const open = dbp
  dbp = null
  if (open) void open.then((db) => db.close()).catch(() => {})
}
