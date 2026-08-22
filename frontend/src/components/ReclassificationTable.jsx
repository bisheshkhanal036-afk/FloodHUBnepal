// Renders one criterion's reclassification_rules as a readable table —
// "how the rasters were reclassified" (per the brief), using the exact
// same interval semantics reclassify.py enforces server-side
// (min_inclusive defaults true, max_inclusive defaults false), so this
// is never just an approximation of what actually ran.
import { WORLDCOVER_LABELS } from '../config/criteria'

// Only worldcover_land_cover is categorical today; keyed by criterion id
// (not hardcoded inline below) so a future categorical criterion just
// needs an entry here, nothing structural in this component.
const CATEGORICAL_CODE_LABELS = {
  worldcover_land_cover: WORLDCOVER_LABELS,
}

function formatBound(value) {
  return value === null ? '∞' : value
}

function formatContinuousRule(rule) {
  const minIncl = rule.min_inclusive !== false
  const maxIncl = rule.max_inclusive === true
  const lo = rule.min === null ? '−∞' : rule.min
  const hi = formatBound(rule.max)
  return `${minIncl ? '[' : '('}${lo}, ${hi}${maxIncl ? ']' : ')'}`
}

export default function ReclassificationTable({ criterion, rules }) {
  const isCategorical = criterion.type === 'categorical'
  const codeLabels = CATEGORICAL_CODE_LABELS[criterion.id]

  return (
    <table className="reclass-table">
      <tbody>
        {rules.map((rule, i) => (
          <tr key={i}>
            <td className="reclass-table__range">
              {isCategorical
                ? `${codeLabels?.[rule.min] || rule.min} (${rule.min})`
                : `${formatContinuousRule(rule)}${criterion.unit ? ` ${criterion.unit}` : ''}`}
            </td>
            <td className="reclass-table__arrow">→</td>
            <td className="reclass-table__class">class {rule.risk_class}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
