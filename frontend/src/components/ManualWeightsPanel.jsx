// "Type weights" mode: a plain numeric input per selected criterion.
// Values are raw relative shares, not required to sum to any particular
// total -- useFinalWeights (AppStateContext) normalizes them to sum to 1
// for the actual request, and this panel shows that normalized
// percentage live next to each input so the user sees the real effect
// of what they typed.
import { CRITERIA_BY_ID } from '../config/criteria'
import { useAppState, useFinalWeights, useSelectedCriteriaIds } from '../state/AppStateContext'

export default function ManualWeightsPanel() {
  const { state, dispatch } = useAppState()
  const selectedIds = useSelectedCriteriaIds()
  const { finalWeights } = useFinalWeights()

  return (
    <div className="manual-weights">
      <p className="ahp-section__hint">
        Type a relative weight for each criterion — they don't need to add up to any particular total, they're
        normalized automatically.
      </p>
      <ul className="manual-weights__list">
        {selectedIds.map((id) => (
          <li key={id} className="manual-weights__row">
            <span className="manual-weights__label">{CRITERIA_BY_ID[id].label}</span>
            <input
              type="number"
              min="0"
              step="any"
              className="manual-weights__input"
              value={state.manualWeights[id] ?? ''}
              onChange={(e) => {
                const value = e.target.value === '' ? 0 : Number(e.target.value)
                dispatch({ type: 'SET_MANUAL_WEIGHT', id, value: Number.isFinite(value) ? Math.max(0, value) : 0 })
              }}
            />
            <span className="manual-weights__normalized">
              {finalWeights ? `${(finalWeights[id] * 100).toFixed(1)}%` : '—'}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
