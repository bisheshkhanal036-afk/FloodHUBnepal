// The success-rate curve itself: cumulative % of AOI area (x, sorted by
// descending model risk score) against cumulative % of "flooding"
// captured (y) -- `capturedLabel` names what that means for the caller
// (ValidationPanel.jsx's real, satellite-observed flooding by default;
// MeteorComparisonPanel.jsx passes its own METEOR-modeled wording, since
// this same chart is reused there and must never imply METEOR's output
// is "observed" data). A single real data series (per dataviz skill:
// "a single series needs no legend box"), plotted against a dashed
// diagonal reference line (y = x, the "random ranking" baseline, AUC
// 0.5) -- an annotation, not a second data series, so it gets a small
// direct label rather than a formal legend entry. Plain inline SVG, no
// charting library, matching this project's existing chart
// (ReportOverlay.jsx's population-by-hazard-class bars) staying
// dependency-free.
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

export default function SuccessRateChart({ curve, capturedLabel = 'real observed flooding' }) {
  const [hoverIndex, setHoverIndex] = useState(null)

  const points = curve.map(([area, capture]) => `${toPlotX(area)},${toPlotY(capture)}`).join(' ')

  function handleMove(e) {
    const svg = e.currentTarget
    const rect = svg.getBoundingClientRect()
    const xFrac = (e.clientX - rect.left) / rect.width
    const areaFrac = Math.max(0, Math.min(1, (xFrac * WIDTH - PAD_LEFT) / PLOT_W))
    // Nearest curve sample by area fraction -- curve is evenly spaced,
    // so a direct index lookup is exact (no need to search).
    const idx = Math.round(areaFrac * (curve.length - 1))
    setHoverIndex(Math.max(0, Math.min(curve.length - 1, idx)))
  }

  const hovered = hoverIndex != null ? curve[hoverIndex] : null

  return (
    <div className="success-rate-chart" role="img" aria-label={`Success-rate curve: cumulative area versus cumulative ${capturedLabel} captured`}>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="success-rate-chart__svg"
        onMouseMove={handleMove}
        onMouseLeave={() => setHoverIndex(null)}
      >
        {/* Recessive axis lines */}
        <line x1={PAD_LEFT} y1={PAD_TOP} x2={PAD_LEFT} y2={HEIGHT - PAD_BOTTOM} className="success-rate-chart__axis" />
        <line x1={PAD_LEFT} y1={HEIGHT - PAD_BOTTOM} x2={WIDTH - PAD_RIGHT} y2={HEIGHT - PAD_BOTTOM} className="success-rate-chart__axis" />

        {/* Random-ranking reference diagonal (AUC 0.5), dashed + muted -- an annotation, not a data series */}
        <line
          x1={toPlotX(0)}
          y1={toPlotY(0)}
          x2={toPlotX(1)}
          y2={toPlotY(1)}
          className="success-rate-chart__reference"
        />

        {/* The real success-rate curve */}
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
        <text x={toPlotX(1) - 1} y={toPlotY(1) - 2} className="success-rate-chart__label success-rate-chart__label--reference" textAnchor="end">
          Random
        </text>
      </svg>

      <div className="success-rate-chart__axis-labels">
        <span>Highest-risk area, cumulative →</span>
        <span>↑ {capturedLabel[0].toUpperCase() + capturedLabel.slice(1)} captured</span>
      </div>

      {hovered && (
        <p className="success-rate-chart__tooltip">
          Highest-risk <strong>{(hovered[0] * 100).toFixed(0)}%</strong> of this AOI captures{' '}
          <strong>{(hovered[1] * 100).toFixed(0)}%</strong> of the {capturedLabel}.
        </p>
      )}
    </div>
  )
}
