// Color ramps shared by the map legend and the risk-surface canvas
// renderer, so the two can never silently drift apart.

// Green -> yellow -> red, low risk -> high risk. A standard 5-stop
// ColorBrewer-style RdYlGn (reversed), chosen for being immediately
// legible as a risk gradient without a legend, while the legend is
// still always shown per the brief.
const RISK_STOPS = [
  [0.0, [26, 152, 80]], // #1a9850 -- low risk
  [0.25, [145, 207, 96]], // #91cf60
  [0.5, [254, 224, 139]], // #fee08a -- medium risk
  [0.75, [252, 141, 89]], // #fc8d59
  [1.0, [215, 48, 39]], // #d73027 -- high risk
]

function lerp(a, b, t) {
  return a + (b - a) * t
}

/** value in [0, 1] -> [r, g, b] (0-255 each). Clamped outside that range. */
export function riskValueToRgb(value) {
  const v = Math.min(1, Math.max(0, value))
  for (let i = 0; i < RISK_STOPS.length - 1; i++) {
    const [v0, c0] = RISK_STOPS[i]
    const [v1, c1] = RISK_STOPS[i + 1]
    if (v >= v0 && v <= v1) {
      const t = v1 === v0 ? 0 : (v - v0) / (v1 - v0)
      return [Math.round(lerp(c0[0], c1[0], t)), Math.round(lerp(c0[1], c1[1], t)), Math.round(lerp(c0[2], c1[2], t))]
    }
  }
  return RISK_STOPS[RISK_STOPS.length - 1][1]
}

export function riskValueToCssColor(value) {
  const [r, g, b] = riskValueToRgb(value)
  return `rgb(${r}, ${g}, ${b})`
}

export const RISK_LEGEND_STOPS = RISK_STOPS.map(([v, rgb]) => ({
  value: v,
  color: `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`,
}))

// Basin support_status colors (backend/app/data/basins.py's support-
// status classifier) -- matches the brief's own suggested mapping.
export const SUPPORT_STATUS_COLORS = {
  fully_in_nepal: '#2ca25f', // green
  partial_likely_adequate: '#dfc27d', // yellow
  likely_degraded_at_edges: '#c9524a', // red
}

export const SUPPORT_STATUS_LABELS = {
  fully_in_nepal: 'Fully in Nepal',
  partial_likely_adequate: 'Partial (likely adequate)',
  likely_degraded_at_edges: 'Likely degraded at edges',
}
