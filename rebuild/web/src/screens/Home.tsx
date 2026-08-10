export function Home({
  onStart,
  segmentsReady,
  notice,
}: {
  onStart: () => void
  segmentsReady: boolean
  notice: string | null
}) {
  return (
    <div className="sheet">
      <h1>Pray for Blacksburg, one street at a time.</h1>
      <p>
        Tell the app how long you have. It hands you a loop that starts and ends in the same place and
        takes in streets nobody has covered yet.
      </p>
      {notice && <p className="notice notice-warn">{notice}</p>}
      <button className="btn btn-primary" onClick={onStart} disabled={!segmentsReady}>
        Start a walk
      </button>
      <p className="privacy">
        Your location stays on this phone. The map is stored on the phone too, so nothing you do here is
        tracked. The only thing that ever reaches the server is the list of streets you tick, after you tap
        confirm.
      </p>
    </div>
  )
}
