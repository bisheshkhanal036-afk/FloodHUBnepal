// Color ramps shared by the map legend and the risk-surface canvas
// renderer, so the two can never silently drift apart.

// Three named risk color schemes, selectable via state.riskColorScheme
// (AOIPanel/ResultPanel's own scheme picker, scoped to the map raster +
// its legend only -- hazard-class swatches elsewhere, e.g. ReportPanel's
// zonal table and CriterionSnapshot, deliberately keep using the 'risk'
// default via riskValueToRgb's own default parameter, an explicit
// decision per the discussion that added this: those are a discrete
// 1-5 class display, a different visual job than a continuous field).
//
// 'risk' is the original default (kept unchanged, not redesigned).
// 'viridis' and 'diverging' were checked against dataviz skill's
// validate_palette.js: both pass CVD separation and the normal-vision
// floor on their own adjacent stops (the tool's categorical-only
// lightness-band/chroma-floor checks don't apply to a continuous ramp,
// per the validator's own footer note -- what actually matters here,
// monotonic lightness for 'viridis' and a symmetric light midpoint for
// 'diverging', both hold by construction).
const RISK_SCHEMES = {
  risk: {
    label: 'Risk (green–yellow–red)',
    // Standard 5-stop ColorBrewer-style RdYlGn (reversed), chosen for
    // being immediately legible as a risk gradient without a legend,
    // while the legend is still always shown per the brief.
    stops: [
      [0.0, [26, 152, 80]], // #1a9850 -- low risk
      [0.25, [145, 207, 96]], // #91cf60
      [0.5, [254, 224, 139]], // #fee08a -- medium risk
      [0.75, [252, 141, 89]], // #fc8d59
      [1.0, [215, 48, 39]], // #d73027 -- high risk
    ],
  },
  viridis: {
    label: 'Colorblind-safe (viridis)',
    // The standard 5-stop viridis colormap -- perceptually uniform,
    // monotonically increasing lightness, the widely-adopted default
    // for continuous scientific/geospatial data specifically because it
    // reads correctly under every common form of color vision
    // deficiency (unlike a hue-cycling "rainbow"/jet colormap).
    stops: [
      [0.0, [68, 1, 84]], // #440154
      [0.25, [59, 82, 139]], // #3b528b
      [0.5, [33, 145, 140]], // #21918c
      [0.75, [94, 201, 98]], // #5ec962
      [1.0, [253, 231, 37]], // #fde725
    ],
  },
  diverging: {
    label: 'Diverging (blue–white–red)',
    // ColorBrewer RdBu: blue/red poles + a near-white neutral midpoint,
    // symmetric per arm -- the standard alternative convention for
    // risk/hazard maps (cool = low/safe, warm = high/danger).
    stops: [
      [0.0, [33, 102, 172]], // #2166ac
      [0.25, [103, 169, 207]], // #67a9cf
      [0.5, [247, 247, 247]], // #f7f7f7
      [0.75, [239, 138, 98]], // #ef8a62
      [1.0, [178, 24, 43]], // #b2182b
    ],
  },
}

export const DEFAULT_RISK_COLOR_SCHEME = 'risk'
export const RISK_COLOR_SCHEMES = Object.keys(RISK_SCHEMES)
export const RISK_COLOR_SCHEME_LABELS = Object.fromEntries(
  Object.entries(RISK_SCHEMES).map(([id, s]) => [id, s.label])
)

function lerp(a, b, t) {
  return a + (b - a) * t
}

function stopsFor(scheme) {
  return (RISK_SCHEMES[scheme] || RISK_SCHEMES[DEFAULT_RISK_COLOR_SCHEME]).stops
}

/** value in [0, 1] -> [r, g, b] (0-255 each). Clamped outside that range. `scheme` defaults to 'risk' -- every existing caller that doesn't pass one keeps its original coloring unchanged. */
export function riskValueToRgb(value, scheme = DEFAULT_RISK_COLOR_SCHEME) {
  const stops = stopsFor(scheme)
  const v = Math.min(1, Math.max(0, value))
  for (let i = 0; i < stops.length - 1; i++) {
    const [v0, c0] = stops[i]
    const [v1, c1] = stops[i + 1]
    if (v >= v0 && v <= v1) {
      const t = v1 === v0 ? 0 : (v - v0) / (v1 - v0)
      return [Math.round(lerp(c0[0], c1[0], t)), Math.round(lerp(c0[1], c1[1], t)), Math.round(lerp(c0[2], c1[2], t))]
    }
  }
  return stops[stops.length - 1][1]
}

export function riskValueToCssColor(value, scheme = DEFAULT_RISK_COLOR_SCHEME) {
  const [r, g, b] = riskValueToRgb(value, scheme)
  return `rgb(${r}, ${g}, ${b})`
}

/** Legend stops for the given scheme (defaults to 'risk') -- was a static RISK_LEGEND_STOPS export; now a function since there are 3 schemes to choose from. */
export function riskLegendStops(scheme = DEFAULT_RISK_COLOR_SCHEME) {
  return stopsFor(scheme).map(([v, rgb]) => ({ value: v, color: `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})` }))
}

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

// District fill color: a single flat color, not a support_status ramp --
// unlike a basin, a district is by definition entirely within Nepal
// (backend/app/data/districts.py's module docstring), so there's no
// per-feature status to distinguish by color. A blue distinct from every
// support_status color above and from the risk ramp itself, so a
// district layer is never mistaken for either.
export const DISTRICT_FILL_COLOR = '#3b82c4'
