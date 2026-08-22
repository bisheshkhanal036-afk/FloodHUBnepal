// Pure helpers for building/resizing Saaty pairwise comparison matrices
// client-side, kept independent of React state so they're easy to reason
// about and test in isolation.

/** An n x n identity-ish "everything equal" matrix -- the default starting point for a fresh comparison. */
export function identityMatrix(n) {
  return Array.from({ length: n }, (_, i) => Array.from({ length: n }, (_, j) => (i === j ? 1 : 1)))
}

/**
 * Rebuilds a pairwise matrix for `newItems`, reusing every judgment from
 * `oldMatrix`/`oldItems` for item pairs that still exist in both, and
 * defaulting new pairs (a new item compared against anything) to 1
 * (equal importance) -- so switching which criteria are checked never
 * silently discards judgments the user already made for the criteria
 * that are still selected.
 */
export function resizeMatrix(oldItems, oldMatrix, newItems) {
  const oldIndex = Object.fromEntries(oldItems.map((id, i) => [id, i]))
  return newItems.map((rowId) =>
    newItems.map((colId) => {
      const oi = oldIndex[rowId]
      const oj = oldIndex[colId]
      if (rowId === colId) return 1
      if (oi !== undefined && oj !== undefined && oldMatrix?.[oi]?.[oj] !== undefined) {
        return oldMatrix[oi][oj]
      }
      return 1
    })
  )
}

/** Sets matrix[i][j] = value and matrix[j][i] = 1/value (reciprocal, per the Saaty scale), returning a new matrix. */
export function withPairwiseValue(matrix, i, j, value) {
  const next = matrix.map((row) => [...row])
  next[i][j] = value
  next[j][i] = 1 / value
  return next
}

/** True if every off-diagonal entry is exactly 1 (the untouched default) -- used to decide whether switching away from AHP mode needs a discard confirmation. */
export function isDefaultMatrix(matrix) {
  return matrix.every((row, i) => row.every((v, j) => i === j || v === 1))
}
