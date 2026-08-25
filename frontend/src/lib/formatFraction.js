// A 0-1 fraction -> a percentage string, widening precision only when
// the value would otherwise vanish to "0.00%" -- a real concern here
// specifically because a point-inventory validation event (see
// ValidationPanel.jsx) produces genuinely tiny fractions by design (a
// handful of known-occurrence pixels out of millions), unlike a
// polygon-extent event's normal-sized percentages. Shared by
// ValidationPanel.jsx, MeteorComparisonPanel.jsx, and
// FrequencyRatioChart.jsx so all three describe the same number the
// same way rather than three copies that could drift.
export function formatFraction(fraction) {
  if (fraction === null || fraction === undefined) return 'n/a'
  const pct = fraction * 100
  if (pct === 0) return '0%'
  if (pct < 0.01) return `${pct.toExponential(1)}%`
  if (pct < 1) return `${pct.toFixed(3)}%`
  return `${pct.toFixed(1)}%`
}
