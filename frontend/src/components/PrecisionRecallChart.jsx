// The precision-recall curve: recall (x, of everything that really
// flooded, what fraction was captured at this cutoff) against precision
// (y, of everything predicted flooded at this cutoff, what fraction
// really flooded). Same single-series-plus-dashed-reference-line shape
// as SuccessRateChart.jsx (reuses its own CSS classes -- visually
// identical chart language, just a different curve and a different
// reference), but the reference here is a HORIZONTAL line at
// `observedFloodedFraction` (what a random ranking's precision hovers
// around at every cutoff), not the diagonal a success-rate curve uses --
// see backend/app/overlay/success_rate.py's own module docstring for
// why PR-AUC's baseline isn't 0.5.
import { useState } from 'react'

const WIDTH = 100
const HEIGHT = 100
const PAD_LEFT = 8
const PAD_BOTTOM = 8
const PAD_TOP = 4
const PAD_RIGHT = 4
const PLOT_W = WIDTH - PAD_LEFT - PAD_RIGHT
const PLOT_H = HEIGHT - PAD_TOP - PAD_BOTTOM

function toPlotX(frac) {
  return PAD_LEFT + frac * PLOT_W
}
function toPlotY(frac) {
  return PAD_TOP + (1 - frac) * PLOT_H
}

export default function PrecisionRecallChart({ curve, observedFloodedFraction }) {
  const [hoverIndex, setHoverIndex] = useState(null)

  const points = curve.map(([recall, precision]) => `${toPlotX(recall)},${toPlotY(precision)}`).join(' ')

  function handleMove(e) {
    const svg = e.currentTarget
    const rect = svg.getBoundingClientRect()
    const xFrac = (e.clientX - rect.left) / rect.width
    const recallFrac = Math.max(0, Math.min(1, (xFrac * WIDTH - PAD_LEFT) / PLOT_W))
    // The curve isn't evenly spaced in recall (unlike SuccessRateChart's
    // curve, which is evenly spaced in area) -- recall can plateau while
    // area keeps advancing, so a direct index-by-fraction lookup would
    // drift. Find the nearest sample by actual recall value instead.
    let nearest = 0
    let nearestDist = Infinity
    curve.forEach(([recall], i) => {
      const dist = Math.abs(recall - recallFrac)
      if (dist < nearestDist) {
        nearestDist = dist
        nearest = i
      }
    })
    setHoverIndex(nearest)
  }

  const hovered = hoverIndex != null ? curve[hoverIndex] : null

  return (
    <div className="success-rate-chart" role="img" aria-label="Precision-recall curve">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="success-rate-chart__svg"
        onMouseMove={handleMove}
        onMouseLeave={() => setHoverIndex(null)}
      >
        {/* Recessive axis lines */}
        <line x1={PAD_LEFT} y1={PAD_TOP} x2={PAD_LEFT} y2={HEIGHT - PAD_BOTTOM} className="success-rate-chart__axis" />
        <line x1={PAD_LEFT} y1={HEIGHT - PAD_BOTTOM} x2={WIDTH - PAD_RIGHT} y2={HEIGHT - PAD_BOTTOM} className="success-rate-chart__axis" />

        {/* Random-ranking reference: a horizontal line at the base flooded rate, dashed + muted -- an annotation, not a data series */}
        <line
          x1={toPlotX(0)}
          y1={toPlotY(observedFloodedFraction)}
          x2={toPlotX(1)}
          y2={toPlotY(observedFloodedFraction)}
          className="success-rate-chart__reference"
        />

        {/* The real precision-recall curve */}
        <polyline points={points} className="success-rate-chart__curve" />

        {/* Hover crosshair + point */}
        {hovered && (
          <>
            <line
              x1={toPlotX(hovered[0])}
              y1={PAD_TOP}
              x2={toPlotX(hovered[0])}
              y2={HEIGHT - PAD_BOTTOM}
              className="success-rate-chart__crosshair"
            />
            <circle cx={toPlotX(hovered[0])} cy={toPlotY(hovered[1])} r={1.6} className="success-rate-chart__point" />
          </>
        )}

        <text x={toPlotX(1) - 1} y={toPlotY(curve[curve.length - 1][1]) - 2} className="success-rate-chart__label success-rate-chart__label--curve" textAnchor="end">
          Model
        </text>
        {/* Labeled at the LEFT end, unlike SuccessRateChart's diagonal
            (labeled at right) -- this curve typically converges toward
            the reference's own height by the right edge (precision
            trends toward the base rate as recall -> 1), so a right-side
            label would collide with "Model" above; the reference line's
            constant height makes the left end just as valid a place to
            label it. */}
        <text x={toPlotX(0) + 1} y={toPlotY(observedFloodedFraction) - 2} className="success-rate-chart__label success-rate-chart__label--reference" textAnchor="start">
          Random
        </text>
      </svg>

      <div className="success-rate-chart__axis-labels">
        <span>Recall →</span>
        <span>↑ Precision</span>
      </div>

      {hovered && (
        <p className="success-rate-chart__tooltip">
          At <strong>{(hovered[0] * 100).toFixed(0)}%</strong> recall, precision is{' '}
          <strong>{(hovered[1] * 100).toFixed(0)}%</strong>.
        </p>
      )}
    </div>
  )
}
