// A transient toast, floating over the map, warning about a real
// documented data-coverage gap the moment a user checks `hand` or
// `soil_infiltration` (see config/criteria.js's DATA_GAP_DISCLAIMERS for
// the exact, measured figures each message cites) -- shown right when
// it becomes relevant, rather than buried in a modal nobody opens.
// Auto-dismisses after DISMISS_AFTER_MS; also closable early. Floats
// over the map (not the sidebar) so it doesn't add to the "sidebar is
// too crowded" problem this same pass also addressed for the report.
import { useEffect } from 'react'
import { DATA_GAP_DISCLAIMERS } from '../config/criteria'
import { useAppState } from '../state/AppStateContext'

const DISMISS_AFTER_MS = 9000

export default function DataGapNotice() {
  const { state, dispatch } = useAppState()
  const ids = state.dataGapNotice

  useEffect(() => {
    if (!ids) return
    const timer = setTimeout(() => dispatch({ type: 'DISMISS_DATA_GAP_NOTICE' }), DISMISS_AFTER_MS)
    return () => clearTimeout(timer)
    // Re-arms the timer on every new notice, including re-checking the
    // same criterion after it already auto-dismissed once -- `ids` is a
    // fresh array each time TOGGLE_CRITERION/SELECT_ALL_CRITERIA fires,
    // so this effect re-runs correctly rather than reusing a stale timer.
  }, [ids, dispatch])

  if (!ids) return null

  return (
    <div className="data-gap-notice" role="alert">
      {ids.map((id) => (
        <p key={id} className="data-gap-notice__message">
          <strong>{id}:</strong> {DATA_GAP_DISCLAIMERS[id]}
        </p>
      ))}
      <button
        type="button"
        className="data-gap-notice__close"
        onClick={() => dispatch({ type: 'DISMISS_DATA_GAP_NOTICE' })}
        aria-label="Dismiss"
        title="Dismiss"
      >
        ×
      </button>
    </div>
  )
}
