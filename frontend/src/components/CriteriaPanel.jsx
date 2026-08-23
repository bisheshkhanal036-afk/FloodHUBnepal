// Checkbox list of the available criteria, grouped by their AHP cluster
// (see src/config/criteria.js for the id -> cluster assignment). Each row
// carries a per-feature info (ⓘ) button that opens LiteratureModal — the
// well-cited write-up of what the feature is and how its reclassification
// ranges are set (src/config/literature.js). Each checked criterion also
// gets an expandable "Customize breaks" section (ClassificationEditor).
import { useState } from 'react'
import { CANONICAL_CLUSTERS, criteriaByCluster } from '../config/criteria'
import { LITERATURE } from '../config/literature'
import { useAppState } from '../state/AppStateContext'
import ClassificationEditor from './ClassificationEditor'
import LiteratureModal from './LiteratureModal'

export default function CriteriaPanel() {
  const { state, dispatch } = useAppState()
  const byCluster = criteriaByCluster()
  // Which feature's literature is open in the modal (null = closed).
  const [litFocusId, setLitFocusId] = useState(null)

  return (
    <div className="criteria-panel">
      {CANONICAL_CLUSTERS.map((cluster) => (
        <div className="criteria-panel__cluster" key={cluster}>
          <h4>{cluster}</h4>
          {byCluster[cluster].map((criterion) => (
            <div key={criterion.id}>
              <div className="criteria-panel__row">
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
                {LITERATURE[criterion.id] && (
                  <button
                    type="button"
                    className="criteria-panel__info"
                    onClick={() => setLitFocusId(criterion.id)}
                    title={`What is ${criterion.label}? Literature & how its ranges are set`}
                    aria-label={`Literature for ${criterion.label}`}
                  >
                    ⓘ
                  </button>
                )}
              </div>
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

      {litFocusId && <LiteratureModal focusId={litFocusId} onClose={() => setLitFocusId(null)} />}
    </div>
  )
}
