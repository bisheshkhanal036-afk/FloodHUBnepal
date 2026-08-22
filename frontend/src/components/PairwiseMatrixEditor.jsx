// A reusable Saaty 1-9 pairwise comparison editor for one n x n matrix.
// Used for both the top-level 5-cluster comparison and each cluster's
// own within-cluster comparison (AHPPanel) -- the UI and the underlying
// math don't care which level they're at.
import { withPairwiseValue } from '../lib/ahpMatrix'

// Signed scale: positive k means the row item is favored k times over
// the column item (matrix[i][j] = k); negative k means the column item
// is favored |k| times (matrix[i][j] = 1/|k|). This is the standard
// Saaty 1-9 scale presented as one dropdown per pair instead of two
// separate "which is more important" + "how much more" controls.
const SCALE = [-9, -8, -7, -6, -5, -4, -3, -2, 1, 2, 3, 4, 5, 6, 7, 8, 9]

function scaleToMatrixValue(k) {
  return k > 0 ? k : 1 / Math.abs(k)
}

function matrixValueToScale(value) {
  if (Math.abs(value - 1) < 1e-9) return 1
  return value > 1 ? Math.round(value) : -Math.round(1 / value)
}

function scaleLabel(k, rowLabel, colLabel) {
  if (k === 1) return 'Equal importance'
  return k > 0 ? `${rowLabel} is ${k}× more important` : `${colLabel} is ${Math.abs(k)}× more important`
}

export default function PairwiseMatrixEditor({ items, labels, matrix, onChange, disabled = false }) {
  if (items.length < 2) return null

  return (
    <div className="pairwise-editor">
      {items.map((rowId, i) =>
        items.slice(i + 1).map((colId, offset) => {
          const j = i + 1 + offset
          const rowLabel = labels[rowId] || rowId
          const colLabel = labels[colId] || colId
          const currentScale = matrixValueToScale(matrix[i][j])

          return (
            <div className="pairwise-row" key={`${rowId}-${colId}`}>
              <span className="pairwise-row__pair">
                {rowLabel} <span className="pairwise-row__vs">vs.</span> {colLabel}
              </span>
              <select
                className="pairwise-row__select"
                disabled={disabled}
                value={currentScale}
                onChange={(e) => {
                  const k = Number(e.target.value)
                  onChange(withPairwiseValue(matrix, i, j, scaleToMatrixValue(k)))
                }}
              >
                {SCALE.map((k) => (
                  <option key={k} value={k}>
                    {scaleLabel(k, rowLabel, colLabel)}
                  </option>
                ))}
              </select>
            </div>
          )
        })
      )}
    </div>
  )
}
