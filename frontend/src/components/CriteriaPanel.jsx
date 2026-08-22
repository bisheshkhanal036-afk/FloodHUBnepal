// Checkbox list of the 7 available criteria, grouped by their AHP
// cluster (see src/config/criteria.js for the id -> cluster assignment).
// Each checked criterion also gets an expandable "Customize breaks"
// section (ClassificationEditor) — manual / equal-interval / quantile /
// Jenks reclassification, per criterion.
import { CANONICAL_CLUSTERS, criteriaByCluster } from '../config/criteria'
import { useAppState } from '../state/AppStateContext'
import ClassificationEditor from './ClassificationEditor'

export default function CriteriaPanel() {
  const { state, dispatch } = useAppState()
  const byCluster = criteriaByCluster()

  return (
    <div className="criteria-panel">
      {CANONICAL_CLUSTERS.map((cluster) => (
        <div className="criteria-panel__cluster" key={cluster}>
          <h4>{cluster}</h4>
          {byCluster[cluster].map((criterion) => (
            <div key={criterion.id}>
              <label className="criteria-panel__item" title={criterion.description}>
                <input
                  type="checkbox"
                  checked={state.criteriaEnabled[criterion.id]}
                  onChange={() => dispatch({ type: 'TOGGLE_CRITERION', id: criterion.id })}
                />
                <span>
                  {criterion.label}
                  {criterion.unit ? <span className="criteria-panel__unit"> ({criterion.unit})</span> : null}
                </span>
              </label>
              {state.criteriaEnabled[criterion.id] && (
                <details className="criteria-panel__classification">
                  <summary>Customize breaks</summary>
                  <ClassificationEditor criterion={criterion} />
                </details>
              )}
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}
