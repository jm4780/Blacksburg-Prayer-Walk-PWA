import type { OutboxItem } from '../types'

/** Says plainly what is waiting to reach the map, and why. */
export function QueueBar({ online, queue }: { online: boolean; queue: OutboxItem[] }) {
  const waiting = queue.filter((q) => q.status === 'pending')
  const stuck = queue.filter((q) => q.status === 'stuck')

  if (stuck.length > 0) {
    return (
      <div className="queue-bar">
        <span className="dot" />
        <span>
          {stuck.length === 1 ? 'A walk was' : `${stuck.length} walks were`} turned down by the server. Nothing
          is lost. Show this to whoever set the app up.
        </span>
      </div>
    )
  }

  if (waiting.length > 0) {
    return (
      <div className="queue-bar">
        <span className="dot" />
        <span>
          {waiting.length === 1 ? '1 walk is' : `${waiting.length} walks are`} saved on your phone, waiting for
          signal. It keeps trying.
        </span>
      </div>
    )
  }

  if (!online) {
    return (
      <div className="queue-bar">
        <span className="dot" />
        <span>No signal. The map and your walk still work.</span>
      </div>
    )
  }

  return null
}
