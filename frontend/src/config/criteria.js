// The 8 criterion sources currently registered in the backend's overlay
// engine (backend/app/overlay/sources.py's registry), with the metadata
// this UI needs that the backend doesn't itself hand back: a display
// label, which of the 5 canonical AHP clusters (backend/app/ahp/
// constants.py's CANONICAL_CLUSTERS) it belongs to, whether it's
// continuous or categorical (schemas/criterion.schema.json's
// resampling_method), and a default reclassification_rules array.
//
// Cluster assignment and reclassification_rules are both real
// methodological choices this project has never made before this phase
// — flagged explicitly for review, see the accompanying message.
//
// `building_density` is Exposure's first criterion (what's at risk --
// population, buildings, economic value): the other 7 are all terrain/
// hydrology/land-cover/proximity factors describing the hazard itself,
// not what it threatens. AHP mode's completeness check
// (state/AppStateContext.jsx's useFinalWeights) only requires every
// currently *selected* criterion's own cluster to be resolved, not every
// canonical cluster -- so before this addition, Exposure being
// permanently empty never blocked computing; it just meant the model
// had no real exposure signal at all.

// Must exactly match backend/app/ahp/constants.py's CANONICAL_CLUSTERS —
// order matters for the top-level 5x5 pairwise comparison, though the
// backend itself only checks set equality, not order.
export const CANONICAL_CLUSTERS = [
  'Topographic',
  'Hydrological',
  'Land Use',
  'Infrastructure',
  'Exposure',
]

export const CRITERIA = [
  {
    id: 'dem_elevation',
    label: 'Elevation',
    cluster: 'Topographic',
    type: 'continuous',
    riskDirection: 'descending', // low value -> high risk
    unit: 'm',
    description: 'Lower ground floods first — risk decreases with elevation.',
    defaultReclassificationRules: [
      { min: null, max: 1360, risk_class: 5 },
      { min: 1360, max: 1520, risk_class: 4 },
      { min: 1520, max: 1680, risk_class: 3 },
      { min: 1680, max: 1840, risk_class: 2 },
      { min: 1840, max: null, risk_class: 1 },
    ],
  },
  {
    id: 'dem_slope',
    label: 'Slope',
    cluster: 'Topographic',
    type: 'continuous',
    riskDirection: 'descending', // low value -> high risk
    unit: '°',
    description: 'Flatter ground drains slower — risk decreases with slope.',
    defaultReclassificationRules: [
      { min: null, max: 10, risk_class: 5 },
      { min: 10, max: 20, risk_class: 4 },
      { min: 20, max: 30, risk_class: 3 },
      { min: 30, max: 40, risk_class: 2 },
      { min: 40, max: null, risk_class: 1 },
    ],
  },
  {
    id: 'twi',
    label: 'Topographic Wetness Index',
    cluster: 'Topographic',
    type: 'continuous',
    riskDirection: 'ascending', // high value -> high risk
    unit: '',
    description: 'Higher TWI means wetter, more flood-prone ground.',
    defaultReclassificationRules: [
      { min: null, max: 5, risk_class: 1 },
      { min: 5, max: 10, risk_class: 2 },
      { min: 10, max: 15, risk_class: 3 },
      { min: 15, max: 20, risk_class: 4 },
      { min: 20, max: null, risk_class: 5 },
    ],
  },
  {
    id: 'dist_to_river',
    label: 'Distance to River',
    cluster: 'Hydrological',
    type: 'continuous',
    riskDirection: 'descending', // low value (close) -> high risk
    unit: 'm',
    description: 'Closer to a river means more direct hydrological connection to the flood source — risk decreases with distance.',
    defaultReclassificationRules: [
      { min: null, max: 100, risk_class: 5 },
      { min: 100, max: 200, risk_class: 4 },
      { min: 200, max: 300, risk_class: 3 },
      { min: 300, max: 400, risk_class: 2 },
      { min: 400, max: null, risk_class: 1 },
    ],
  },
  {
    id: 'drainage_density',
    label: 'Drainage Density',
    cluster: 'Hydrological',
    type: 'continuous',
    riskDirection: 'ascending', // high value -> high risk
    unit: 'km/km²',
    description: 'Denser local drainage channels concentrate flow — risk increases with density.',
    defaultReclassificationRules: [
      { min: null, max: 1, risk_class: 1 },
      { min: 1, max: 2, risk_class: 2 },
      { min: 2, max: 3, risk_class: 3 },
      { min: 3, max: 4, risk_class: 4 },
      { min: 4, max: null, risk_class: 5 },
    ],
  },
  {
    id: 'worldcover_land_cover',
    label: 'Land Cover',
    cluster: 'Land Use',
    type: 'categorical',
    unit: '',
    description: 'ESA WorldCover class — built-up, water, and wetland score highest risk; tree cover lowest.',
    // One rule per ESA WorldCover legend code (10-100); min === max marks
    // each as a categorical point rule (reclassify.py exempts these from
    // the continuous-range gap check). min_inclusive/max_inclusive must
    // BOTH be explicit `true` here -- the backend's default for
    // max_inclusive is `false` (correct for a continuous range's upper
    // bound), but for a point rule that makes the interval [40, 40)
    // *empty*, matching nothing at all. Verified live: omitting these
    // made every single worldcover_land_cover pixel come back "matched
    // no reclassification rule" (a 422 from the real backend).
    defaultReclassificationRules: [
      { min: 10, max: 10, min_inclusive: true, max_inclusive: true, risk_class: 1 }, // tree cover
      { min: 20, max: 20, min_inclusive: true, max_inclusive: true, risk_class: 2 }, // shrubland
      { min: 30, max: 30, min_inclusive: true, max_inclusive: true, risk_class: 2 }, // grassland
      { min: 40, max: 40, min_inclusive: true, max_inclusive: true, risk_class: 3 }, // cropland
      { min: 50, max: 50, min_inclusive: true, max_inclusive: true, risk_class: 5 }, // built-up
      { min: 60, max: 60, min_inclusive: true, max_inclusive: true, risk_class: 4 }, // bare / sparse vegetation
      { min: 70, max: 70, min_inclusive: true, max_inclusive: true, risk_class: 1 }, // snow and ice
      { min: 80, max: 80, min_inclusive: true, max_inclusive: true, risk_class: 5 }, // permanent water bodies
      { min: 90, max: 90, min_inclusive: true, max_inclusive: true, risk_class: 5 }, // herbaceous wetland
      { min: 95, max: 95, min_inclusive: true, max_inclusive: true, risk_class: 3 }, // mangroves
      { min: 100, max: 100, min_inclusive: true, max_inclusive: true, risk_class: 2 }, // moss and lichen
    ],
  },
  {
    id: 'dist_to_road',
    label: 'Distance to Road',
    cluster: 'Infrastructure',
    type: 'continuous',
    riskDirection: 'ascending', // high value (far) -> high risk
    unit: 'm',
    description: 'Farther from a road means harder evacuation and access — risk increases with distance.',
    defaultReclassificationRules: [
      { min: null, max: 200, risk_class: 1 },
      { min: 200, max: 400, risk_class: 2 },
      { min: 400, max: 600, risk_class: 3 },
      { min: 600, max: 800, risk_class: 4 },
      { min: 800, max: null, risk_class: 5 },
    ],
  },
  {
    id: 'building_density',
    label: 'Building Density',
    cluster: 'Exposure',
    type: 'continuous',
    riskDirection: 'ascending', // high value -> high risk
    unit: '',
    description:
      'Local building-footprint coverage (0-1) — denser building clusters mean more people/property exposed if flooded.',
    defaultReclassificationRules: [
      { min: null, max: 0.15, risk_class: 1 },
      { min: 0.15, max: 0.3, risk_class: 2 },
      { min: 0.3, max: 0.45, risk_class: 3 },
      { min: 0.45, max: 0.6, risk_class: 4 },
      { min: 0.6, max: null, risk_class: 5 },
    ],
  },
]

// Human-readable names for worldcover_land_cover's categorical codes —
// used wherever that criterion's reclassification_rules are displayed
// (e.g. ResultPanel), since "code 50 -> class 5" means nothing on its
// own. Matches the codes/order in that criterion's own
// defaultReclassificationRules above.
export const WORLDCOVER_LABELS = {
  10: 'Tree cover',
  20: 'Shrubland',
  30: 'Grassland',
  40: 'Cropland',
  50: 'Built-up',
  60: 'Bare / sparse vegetation',
  70: 'Snow and ice',
  80: 'Permanent water bodies',
  90: 'Herbaceous wetland',
  95: 'Mangroves',
  100: 'Moss and lichen',
}

export const CRITERIA_BY_ID = Object.fromEntries(CRITERIA.map((c) => [c.id, c]))

export function criteriaByCluster() {
  const map = Object.fromEntries(CANONICAL_CLUSTERS.map((c) => [c, []]))
  for (const criterion of CRITERIA) map[criterion.cluster].push(criterion)
  return map
}
