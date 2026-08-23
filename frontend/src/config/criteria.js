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
// `building_density` and `population_density` are Exposure's criteria
// (what's at risk -- population, buildings, economic value): the other 7
// are all terrain/hydrology/land-cover/proximity factors describing the
// hazard itself, not what it threatens. AHP mode's completeness check
// (state/AppStateContext.jsx's useFinalWeights) only requires every
// currently *selected* criterion's own cluster to be resolved, not every
// canonical cluster -- so before building_density's addition, Exposure
// being permanently empty never blocked computing; it just meant the
// model had no real exposure signal at all.
//
// dist_to_river stays in Hydrological, not Exposure: it was already
// there before this addition, and that's the methodologically correct
// placement (proximity to the hazard's own source is a hydrological/
// hazard-proximity factor, same category as drainage_density -- Exposure
// is reserved for what's at risk, i.e. population/buildings, not the
// hazard itself). Flagged as a decision to confirm.

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
    id: 'hand',
    label: 'Height Above Nearest Drainage (HAND)',
    cluster: 'Hydrological',
    type: 'continuous',
    riskDirection: 'descending', // low value (close to drainage level) -> high risk
    unit: 'm',
    description:
      'Elevation above the nearest stream cell along the D8 flow path (not straight-line distance) — ground close to its local drainage floods first, so risk decreases with HAND.',
    // Placeholder equal-interval breakpoints, the same "structurally
    // reasonable, not literature-calibrated" pattern as every other
    // criterion here (SPEC.md already documents this for
    // drainage_density/population_density) -- picked from the rough
    // range HAND-based flood-susceptibility studies commonly use (e.g.
    // Nobre et al. 2011, Zheng et al. 2018 typically treat single-digit-
    // metre HAND as flood-prone), not derived from any Kathmandu-Valley-
    // specific analysis. Flagged as a decision to confirm. Shares
    // backend/app/data/config.py's DRAINAGE_DENSITY_THRESHOLD_CELLS with
    // drainage_density (same synthetic stream network both measure
    // against) -- recalibrating that one threshold later changes both
    // criteria's underlying values together, though not these display
    // breakpoints, which are independent of it.
    defaultReclassificationRules: [
      { min: null, max: 2, risk_class: 5 },
      { min: 2, max: 5, risk_class: 4 },
      { min: 5, max: 10, risk_class: 3 },
      { min: 10, max: 20, risk_class: 2 },
      { min: 20, max: null, risk_class: 1 },
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
    id: 'ndvi',
    label: 'Vegetation (NDVI)',
    cluster: 'Land Use',
    type: 'continuous',
    riskDirection: 'descending', // low NDVI (bare/built/water) -> high risk
    unit: '',
    description:
      'Sentinel-2 vegetation greenness (−1 to 1) — denser vegetation slows runoff and stabilizes soil (lower risk); bare, built, or water surfaces (low/negative NDVI) shed water faster (higher risk).',
    defaultReclassificationRules: [
      { min: null, max: 0.1, risk_class: 5 }, // water / built / bare
      { min: 0.1, max: 0.25, risk_class: 4 },
      { min: 0.25, max: 0.4, risk_class: 3 },
      { min: 0.4, max: 0.6, risk_class: 2 },
      { min: 0.6, max: null, risk_class: 1 }, // dense, vigorous vegetation
    ],
  },
  {
    id: 'soil_infiltration',
    label: 'Soil Infiltration Capacity',
    cluster: 'Land Use',
    type: 'continuous',
    riskDirection: 'descending', // low sand content (finer, less permeable soil) -> high risk
    unit: '%',
    description:
      'ISRIC SoilGrids topsoil (0-5cm) sand content, used as an infiltration-capacity proxy — sandier soil drains faster, so risk decreases with sand content.',
    // Placeholder equal-interval breakpoints over SoilGrids' real 0-100%
    // sand-content range, the same "structurally reasonable, not
    // literature-calibrated" pattern as every other criterion here.
    // Values are a simple topsoil sand-content proxy for infiltration
    // capacity, not a full USDA Hydrologic Soil Group (which would also
    // need clay content and a texture-triangle lookup) -- flagged as a
    // decision to confirm. Shares this file's Land Use cluster with
    // worldcover_land_cover/ndvi (surface-characteristic factors
    // affecting runoff, not topography or channel network) -- also
    // flagged as a decision to confirm.
    defaultReclassificationRules: [
      { min: null, max: 20, risk_class: 5 },
      { min: 20, max: 40, risk_class: 4 },
      { min: 40, max: 60, risk_class: 3 },
      { min: 60, max: 80, risk_class: 2 },
      { min: 80, max: null, risk_class: 1 },
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
  {
    id: 'population_density',
    label: 'Population Density',
    cluster: 'Exposure',
    type: 'continuous',
    riskDirection: 'ascending', // high value -> high risk
    unit: 'people/km²',
    description:
      'Meta/CIESIN HRSL population density (converted from per-pixel count to people/km² at native resolution before resampling — see SPEC.md §2.2) — denser population means more people exposed if flooded.',
    // Placeholder equal-interval breakpoints, the same "structurally-
    // reasonable, not literature-calibrated" placeholder pattern SPEC.md
    // already documents for drainage_density -- picked from the real
    // resampled density range seen in live testing over Kathmandu Valley
    // (~25,000-121,000 people/km² for that AOI's dense urban core), not
    // derived from any population-risk literature. Flagged as a decision
    // to confirm. NOTE: this scale is specific to HRSL's people/km²
    // density output, not a raw per-pixel count -- see backend/app/data/
    // population.py's _count_to_density for why count had to be
    // converted before these numbers were even meaningful to pick.
    defaultReclassificationRules: [
      { min: null, max: 30000, risk_class: 1 },
      { min: 30000, max: 60000, risk_class: 2 },
      { min: 60000, max: 90000, risk_class: 3 },
      { min: 90000, max: 120000, risk_class: 4 },
      { min: 120000, max: null, risk_class: 5 },
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

// drainage_density and hand are measured against the exact same
// synthetic stream network (flow_accumulation thresholded by one shared
// cell-count minimum — backend/app/data/config.py's
// DRAINAGE_DENSITY_THRESHOLD_CELLS) -- the one place this list lives, so
// CriteriaPanel (rendering the shared threshold control), ComputePanel
// (attaching stream_threshold_cells to the right criteria), and
// ClassificationEditor (refetching breaks previews when the threshold
// changes) can never disagree about which criteria it applies to.
export const STREAM_THRESHOLD_SOURCE_IDS = ['drainage_density', 'hand']

export const CRITERIA_BY_ID = Object.fromEntries(CRITERIA.map((c) => [c.id, c]))

export function criteriaByCluster() {
  const map = Object.fromEntries(CANONICAL_CLUSTERS.map((c) => [c, []]))
  for (const criterion of CRITERIA) map[criterion.cluster].push(criterion)
  return map
}
