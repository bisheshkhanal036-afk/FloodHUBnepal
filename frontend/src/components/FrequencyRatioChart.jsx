// Frequency ratio per hazard class: 5 ordinal categories (hazard class
// 1-5), one magnitude each (what fraction of that class's own pixels
// actually flooded) -- a magnitude-by-category job, so a bar chart, per
// the dataviz skill's own form heuristic, not a line (there's no
// meaningful "between class 2 and class 3" to interpolate). A single
// series, so no legend box (dataviz skill: "a single series needs no
// legend box"); each bar is instead colored by ITS OWN hazard class,
// reusing riskValueToCssColor((hazard_class-1)/4) -- the exact same
// mapping CriterionSnapshot.jsx/ReportOverlay.jsx already use for a
// discrete 1-5 class swatch, so a bar's color always means the same
// thing everywhere in this app, not a chart-local palette invented here.
//
// The y-axis auto-scales to the real data range rather than a fixed
// [0, 100%]: for a point-inventory validation event (see
// ValidationPanel.jsx), every fraction is a tiny number by design (a
// handful of point-pixels out of millions) -- a fixed 0-100% axis would
// flatten every bar to invisible. A class absent from this AOI
// (flooded_fraction === null) draws as a hollow/dashed outline, not a
// 0-height bar, so "doesn't occur here" is never visually confused with
// "occurs here and never floods" (a real 0).
import { useState } from 'react'
import { riskValueToCssColor } from '../lib/colorRamp'
import { formatFraction } from '../lib/formatFraction'

const WIDTH = 100
const HEIGHT = 100
const PAD_LEFT = 8
const PAD_BOTTOM = 12
const PAD_TOP = 6
const PAD_RIGHT = 4
const PLOT_W = WIDTH - PAD_LEFT - PAD_RIGHT
const PLOT_H = HEIGHT - PAD_TOP - PAD_BOTTOM
const BAR_GAP = 1.2

export default function FrequencyRatioChart({ byClass, monotonic }) {
  const [hoverIndex, setHoverIndex] = useState(null)

  const present = byClass.filter((c) => c.flooded_fraction !== null)
  const maxFraction = present.length > 0 ? Math.max(...present.map((c) => c.flooded_fraction)) : 0
  // Headroom above the tallest bar so its own direct label never
  // collides with the plot's top edge; a floor so an all-zero result
  // still renders a real (if flat) baseline, not a divide-by-zero scale.
  const yMax = maxFraction > 0 ? maxFraction * 1.25 : 1

  const barWidth = PLOT_W / byClass.length - BAR_GAP
  const toBarX = (i) => PAD_LEFT + i * (PLOT_W / byClass.length) + BAR_GAP / 2
  const toBarY = (fraction) => PAD_TOP + PLOT_H * (1 - (fraction ?? 0) / yMax)
  const baselineY = PAD_TOP + PLOT_H

  const hovered = hoverIndex != null ? byClass[hoverIndex] : null

  return (
    <div className="frequency-ratio-chart">
      <div className="frequency-ratio-chart__header">
        <span className={`frequency-ratio-chart__monotonic frequency-ratio-chart__monotonic--${monotonic ? 'yes' : 'no'}`}>
          {monotonic ? '✓ Increases monotonically across classes' : '✗ Does not increase monotonically'}
        </span>
      </div>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="frequency-ratio-chart__svg" role="img" aria-label="Frequency ratio per hazard class">
        <line x1={PAD_LEFT} y1={baselineY} x2={WIDTH - PAD_RIGHT} y2={baselineY} className="frequency-ratio-chart__axis" />

        {byClass.map((c, i) => {
          const x = toBarX(i)
          const color = riskValueToCssColor((c.hazard_class - 1) / 4)
          const isHovered = hoverIndex === i
          if (c.flooded_fraction === null) {
            // Absent from this AOI -- a hollow outline at a nominal
            // height, not a bar with a real value.
            return (
              <rect
                key={c.hazard_class}
                x={x}
                y={baselineY - 3}
                width={barWidth}
                height={3}
                rx={0.6}
                className="frequency-ratio-chart__bar-absent"
                style={{ stroke: color }}
                onMouseEnter={() => setHoverIndex(i)}
                onMouseLeave={() => setHoverIndex(null)}
              />
            )
          }
          const y = toBarY(c.flooded_fraction)
          const height = Math.max(baselineY - y, 0.6)
          return (
            <rect
              key={c.hazard_class}
              x={x}
              y={y}
              width={barWidth}
              height={height}
              rx={0.8}
              style={{ fill: color, opacity: isHovered ? 1 : 0.88 }}
              onMouseEnter={() => setHoverIndex(i)}
              onMouseLeave={() => setHoverIndex(null)}
            />
          )
        })}

        {byClass.map((c, i) => (
          <text
            key={c.hazard_class}
            x={toBarX(i) + barWidth / 2}
            y={baselineY + 4}
            className="frequency-ratio-chart__class-label"
            textAnchor="middle"
          >
            {c.hazard_class}
          </text>
        ))}
      </svg>

      <div className="frequency-ratio-chart__legend-labels">
        <span>Very Low</span>
        <span>Very High</span>
      </div>

      <p className="frequency-ratio-chart__tooltip">
        {hovered ? (
          hovered.flooded_fraction === null ? (
            <>
              <strong>{hovered.hazard_label}</strong> (class {hovered.hazard_class}) doesn't occur anywhere in this AOI.
            </>
          ) : (
            <>
              <strong>{hovered.hazard_label}</strong> (class {hovered.hazard_class}): <strong>{formatFraction(hovered.flooded_fraction)}</strong> flooded (
              {hovered.flooded_pixel_count.toLocaleString()} of {hovered.pixel_count.toLocaleString()} pixels).
            </>
          )
        ) : (
          'Hover a bar for the exact count.'
        )}
      </p>
    </div>
  )
}
