import type { OutboxItem, Segment } from '../types'

export function Sent({
  item,
  claimedSegments,
  onDone,
}: {
  item: OutboxItem | undefined
  claimedSegments: Segment[]
  onDone: () => void
}) {
  const landed = item?.status === 'sent'
  const stuck = item?.status === 'stuck'

  return (
    <div className="sheet">
      {landed ? (
        <>
          <h1>It's on the map.</h1>
          <p>
            {claimedSegments.length} streets from this walk.{' '}
            {(item?.newly_covered?.length ?? 0) > 0
              ? `${item?.newly_covered?.length} of them had never been prayed for before.`
              : 'Someone had already covered these, and your walk still counts.'}
          </p>
        </>
      ) : stuck ? (
        <>
          <h1>Saved, but the server turned it down.</h1>
          <p>Your walk is still on this phone. Nothing is lost. Tell whoever set the app up.</p>
        </>
      ) : (
        <>
          <h1>Saved on your phone.</h1>
          <p>
            It goes up the moment you have signal. You can close the app, restart the phone, or walk
            again. It keeps trying until it lands, and it can only land once.
          </p>
        </>
      )}
      <button className="btn btn-primary" onClick={onDone}>
        Done
      </button>
    </div>
  )
}
