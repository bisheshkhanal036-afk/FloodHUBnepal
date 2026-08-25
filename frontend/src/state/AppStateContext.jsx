// Central app state for the one cohesive page (map + AOI + criteria +
// weighting + compute): a single reducer, exposed via context, so
// sibling panels (AOI, criteria, weighting, compute, map) all read and
// act on the same source of truth without prop-drilling. Structured as
// its own module (not folded into App.jsx) specifically so a future
// phase (vulnerability classification, shelter markers) can extend this
// state rather than needing to restructure it.
import { createContext, useContext, useEffect, useMemo, useReducer } from 'react'
import {
  CANONICAL_CLUSTERS,
  CRITERIA,
  CRITERIA_BY_ID,
  DATA_GAP_CRITERIA,
  STREAM_THRESHOLD_SOURCE_IDS,
  criteriaByCluster,
} from '../config/criteria'
import { identityMatrix, resizeMatrix } from '../lib/ahpMatrix'
import { defaultClassificationEntry } from '../lib/classification'
import { DEFAULT_RISK_COLOR_SCHEME } from '../lib/colorRamp'

const AppStateContext = createContext(null)

const THEME_STORAGE_KEY = 'flood-risk-theme'

function initialTheme() {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY)
    if (stored === 'light' || stored === 'dark') return stored
  } catch {
    // localStorage unavailable (private browsing, etc.) -- fall through to the default below
  }
  // Dark-first by deliberate product decision (the "midnight precision
  // instrument" redesign) -- unlike before, this no longer follows
  // prefers-color-scheme for a first-time visitor. Still fully overridable
  // via the sidebar's theme toggle and persisted the same way afterward.
  return 'dark'
}

function initialState() {
  const theme = initialTheme()
  return {
    theme,

    // Independent of `theme` (the app chrome's own light/dark CSS) --
    // the map's basemap is its own choice among several free, no-key
    // raster tile providers (see components/MapView.jsx's BASEMAPS).
    // Defaulted to match the initial theme purely so the first paint
    // looks coherent (a dark sidebar over a bright OSM map would look
    // like a bug on first load), not because the two are coupled after
    // that -- the user can pick any basemap regardless of app theme.
    basemapStyle: theme === 'dark' ? 'dark' : 'street',
    basemapVisible: true,

    // METEOR Project's live Nepal flood hazard reference overlay (WMTS
    // tiles, see components/MapView.jsx's MeteorFloodControl/
    // meteorFloodTiles) -- an independent map layer, not the same thing
    // as the flood_hazard_meteor *criterion* (overlay/sources.py), which
    // reads the same organization's downloadable numeric GeoTIFFs
    // instead. Off by default (an opt-in reference layer, not part of
    // the base map); type/return-period mirror backend/app/data/
    // config.py's METEOR_FLOOD_TYPE/METEOR_FLOOD_RETURN_PERIOD naming
    // convention, though this dropdown talks to METEOR's own live WMTS
    // tile service directly, not the backend, so it isn't limited to
    // whichever single local GeoTIFF a deployment happens to have
    // downloaded for the criterion.
    meteorFloodVisible: false,
    meteorFloodType: 'fd', // 'fd' | 'fu' | 'p' -- Fluvial Defended | Fluvial Undefended | Pluvial
    meteorFloodReturnPeriod: 100, // years; one of MapView.jsx's METEOR_FLOOD_RETURN_PERIODS

    aoiMode: 'draw', // 'draw' | 'basin' | 'district'
    aoi: null, // { bbox: [minx,miny,maxx,maxy], polygon: geom|null, source: 'draw'|'basin'|'district', basinId?, basinLevel?, districtPcode?, label? }
    areaWarning: null,

    // Which HydroBASINS resolution 'basin' mode browses/fetches -- 8
    // (~547 basins over Nepal's rough extent, coarser/larger catchments,
    // the original default) or 9 (finer sub-catchments). Independent of
    // `basins` below: changing this resets that fetch back to 'idle' (see
    // SET_BASIN_LEVEL) so AOIPanel's effect re-fetches at the new level.
    basinLevel: 8,
    basins: { status: 'idle', data: null, error: null },
    selectedBasinId: null,

    // District mode (an alternative AOI-selection path alongside basins,
    // not a replacement for either) -- mirrors `basins`/`selectedBasinId`
    // exactly, but has no level concept (Nepal has one fixed set of 77
    // districts).
    districts: { status: 'idle', data: null, error: null },
    selectedDistrictPcode: null,

    criteriaEnabled: Object.fromEntries(CRITERIA.map((c) => [c.id, false])),

    // Shared override for drainage_density/hand's synthetic stream-
    // network threshold (backend/app/data/config.py's
    // DRAINAGE_DENSITY_THRESHOLD_CELLS -- mirrored here as a UI default,
    // same "mirror a backend constant with a comment" pattern lib/geo.js's
    // AREA_CAP_KM2 already uses). ONE shared value, not per-criterion:
    // drainage_density and hand are measured against the exact same
    // stream network, so letting them diverge would be scientifically
    // inconsistent between the two results in a single compute. See
    // config/criteria.js's STREAM_THRESHOLD_SOURCE_IDS for which
    // criteria this applies to.
    streamThresholdCells: 500,

    weightMode: 'equal', // 'equal' | 'ahp' | 'manual'
    ahpMatrices: {
      cluster: { items: CANONICAL_CLUSTERS, matrix: identityMatrix(CANONICAL_CLUSTERS.length) },
      withinCluster: {}, // { [clusterName]: { items: [criterionId, ...], matrix } }, only for clusters with >=1 checked criterion
    },
    ahp: { status: 'idle', result: null, error: null },

    // Raw (not-yet-normalized) typed values for 'manual' mode, one per
    // currently-selected criterion -- see useFinalWeights for how these
    // become an actual final_weights set (normalized to sum to 1).
    manualWeights: {},

    // Per-criterion reclassification classification (manual / equal-
    // interval / quantile / Jenks natural breaks) -- see lib/
    // classification.js. Seeded when a criterion is checked, dropped
    // when unchecked, and reset for every still-checked criterion when
    // the AOI changes (equal-interval/quantile/jenks breaks are
    // computed from that AOI's actual data, so they're meaningless for
    // a different one; manual edits reset too, for the same reason
    // `overlay` itself resets on AOI change -- a full, predictable
    // reset rather than a partial one).
    classification: {},

    overlay: { status: 'idle', result: null, error: null, criteriaUsed: null, weightsUsed: null, progressLog: [] },

    // Independent of `overlay` itself -- purely how the already-computed
    // risk surface is displayed, not part of the compute result. Reused
    // across every subsequent compute (not reset on OVERLAY_LOADING like
    // `overlay`/`report` are), since a user picking, say, a colorblind-
    // safe scheme almost certainly wants it to stay picked for their next
    // AOI/compute too, not silently revert.
    riskSurfaceVisible: true,
    riskColorScheme: DEFAULT_RISK_COLOR_SCHEME, // one of RISK_COLOR_SCHEMES (lib/colorRamp.js)

    // The vulnerability-classification/computation report (POST /api/
    // overlay/report) -- a separate, heavier, optional follow-up to a
    // successful compute, not part of the core AOI->criteria->weighting
    // ->compute flow, so it gets its own status slice rather than being
    // folded into `overlay`. Reset whenever a new compute starts
    // (OVERLAY_LOADING) -- any existing report describes a result that's
    // about to be superseded, so it can't stay displayed as current.
    report: { status: 'idle', result: null, error: null },

    // Whether ReportOverlay (the full infographic-style report, absolutely
    // positioned over the map -- see App.jsx) is currently shown. Kept
    // separate from `report.status` so the user can dismiss it without
    // discarding the underlying result (re-opening doesn't need a
    // regenerate), and separate from the sidebar's own "Vulnerability
    // report" step, which stays a compact trigger regardless -- moving the
    // heavy content off the sidebar (a crowded-sidebar complaint) is the
    // entire point of this split. Auto-set true on REPORT_LOADED (a freshly
    // generated report should be immediately visible, not require a second
    // click), reset false on OVERLAY_LOADING (a new compute invalidates the
    // report it was showing, same trigger `report` itself resets on).
    reportOverlayVisible: false,

    // Real-flood validation (POST /api/overlay/validate) -- success-
    // rate/AUC-checks the just-computed risk surface against a real,
    // satellite-observed flood extent (backend/app/data/
    // validation_extent.py), never against another model's output (see
    // that module's own docstring for why METEOR specifically is
    // deliberately not used THIS way -- METEOR agreement is its own,
    // separate `meteorComparison` state below, never merged into this
    // one). Same shape/reset trigger as `report` above -- a separate,
    // optional follow-up to a successful compute, reset on
    // OVERLAY_LOADING since it describes a result about to be
    // superseded.
    validation: { status: 'idle', result: null, error: null },
    // GET /api/overlay/validation-events's own fetch lifecycle --
    // independent of `validation` itself (the list of what's available
    // to validate against, not a validation result), fetched once and
    // never reset on compute.
    validationEvents: { status: 'idle', list: [], error: null },
    // METEOR model-agreement comparison (POST /api/overlay/compare-
    // meteor, MeteorComparisonPanel.jsx) -- deliberately its own state
    // slice, never folded into `validation` above: this checks
    // agreement with another model's own output, not real-world
    // accuracy (see backend/app/overlay/meteor_comparison.py's own
    // docstring). Same shape/reset trigger as `validation`.
    meteorComparison: { status: 'idle', result: null, error: null },
    // Which event's key (from validationEvents.list) the picker is
    // currently set to -- persists across computes/resets, same
    // reasoning riskColorScheme above already documents (a user's
    // choice here almost certainly should stick, not silently revert).
    // Shared by both ValidationPanel's own event dropdown AND
    // MapView.jsx's ValidationExtentControl (the map-corner overlay
    // toggle, same UI slot MeteorFloodControl already occupies) -- one
    // selection drives both, so picking an event to validate against
    // and picking which event's real extent to see on the map are
    // never allowed to silently disagree.
    selectedValidationEvent: null,
    // The real observed flood-extent overlay's own visibility -- off by
    // default, same as meteorFloodVisible above, since it's an opt-in
    // reference layer, not part of the base map.
    validationExtentVisible: false,

    // The transient "this criterion has known data gaps" disclaimer
    // (DataGapNotice.jsx) -- null when hidden, otherwise an array of
    // criterion ids (config/criteria.js's DATA_GAP_CRITERIA) to show
    // messages for at once. Set on checking `hand`/`soil_infiltration`
    // (TOGGLE_CRITERION) or SELECT_ALL_CRITERIA; cleared by
    // DISMISS_DATA_GAP_NOTICE, which the toast dispatches itself either
    // after an auto-dismiss timeout or on a manual close click.
    dataGapNotice: null,
  }
}

function resyncWithinClusterMatrices(ahpMatrices, criteriaEnabled) {
  const byCluster = criteriaByCluster()
  const withinCluster = {}
  for (const cluster of CANONICAL_CLUSTERS) {
    const checkedIds = byCluster[cluster].filter((c) => criteriaEnabled[c.id]).map((c) => c.id)
    if (checkedIds.length === 0) continue
    const prev = ahpMatrices.withinCluster[cluster]
    withinCluster[cluster] = {
      items: checkedIds,
      matrix: resizeMatrix(prev?.items || [], prev?.matrix || [], checkedIds),
    }
  }
  return { ...ahpMatrices, withinCluster }
}

/** Keeps manualWeights in sync with whichever criteria are currently checked -- new ones default to an equal (1) raw share, unselected ones drop out, existing typed values for still-selected criteria are preserved. */
function resyncManualWeights(manualWeights, criteriaEnabled) {
  const next = {}
  for (const criterion of CRITERIA) {
    if (!criteriaEnabled[criterion.id]) continue
    next[criterion.id] = manualWeights[criterion.id] ?? 1
  }
  return next
}

/** Fresh classification entries for every currently-checked criterion -- used on AOI change, where any previously-fetched breaks are no longer valid for the new AOI. */
function resetClassificationForCheckedCriteria(criteriaEnabled) {
  return Object.fromEntries(
    CRITERIA.filter((c) => criteriaEnabled[c.id]).map((c) => [c.id, defaultClassificationEntry(c)])
  )
}

function reducer(state, action) {
  switch (action.type) {
    case 'SET_THEME': {
      try {
        localStorage.setItem(THEME_STORAGE_KEY, action.theme)
      } catch {
        // localStorage unavailable -- theme still applies for this session, just won't persist
      }
      return { ...state, theme: action.theme }
    }

    case 'SET_BASEMAP_STYLE':
      return { ...state, basemapStyle: action.style }

    case 'TOGGLE_BASEMAP_VISIBLE':
      return { ...state, basemapVisible: !state.basemapVisible }

    case 'TOGGLE_METEOR_FLOOD_VISIBLE':
      return { ...state, meteorFloodVisible: !state.meteorFloodVisible }

    case 'SET_METEOR_FLOOD_TYPE':
      return { ...state, meteorFloodType: action.floodType }

    case 'SET_METEOR_FLOOD_RETURN_PERIOD':
      return { ...state, meteorFloodReturnPeriod: action.returnPeriod }

    case 'TOGGLE_RISK_SURFACE_VISIBLE':
      return { ...state, riskSurfaceVisible: !state.riskSurfaceVisible }

    case 'SET_RISK_COLOR_SCHEME':
      return { ...state, riskColorScheme: action.scheme }

    case 'SET_AOI_MODE':
      return { ...state, aoiMode: action.mode }

    case 'SET_AOI':
      return {
        ...state,
        aoi: action.aoi,
        areaWarning: null,
        classification: resetClassificationForCheckedCriteria(state.criteriaEnabled),
        overlay: { status: 'idle', result: null, error: null, criteriaUsed: null, weightsUsed: null, progressLog: [] },
      }

    case 'CLEAR_AOI':
      return {
        ...state,
        aoi: null,
        selectedBasinId: null,
        selectedDistrictPcode: null,
        classification: {},
        overlay: { status: 'idle', result: null, error: null, criteriaUsed: null, weightsUsed: null, progressLog: [] },
      }

    case 'SET_AREA_WARNING':
      return { ...state, areaWarning: action.message }

    case 'BASINS_LOADING':
      return { ...state, basins: { status: 'loading', data: null, error: null } }
    case 'BASINS_LOADED':
      return { ...state, basins: { status: 'loaded', data: action.data, error: null } }
    case 'BASINS_ERROR':
      return { ...state, basins: { status: 'error', data: null, error: action.error } }

    case 'SET_SELECTED_BASIN_ID':
      return { ...state, selectedBasinId: action.hybasId }

    case 'SET_BASIN_LEVEL':
      // A different level means a different basin set entirely -- reset
      // the fetch back to 'idle' so AOIPanel's effect (keyed on
      // aoiMode/basins.status) re-fetches at the new level, the same
      // "reset status to trigger a refetch" mechanism SET_STREAM_
      // THRESHOLD_CELLS uses for classification breaks below. Also drops
      // any basin selected under the old level, since its polygon
      // belongs to a layer that's about to be replaced.
      return {
        ...state,
        basinLevel: action.level,
        basins: { status: 'idle', data: null, error: null },
        selectedBasinId: null,
      }

    case 'DISTRICTS_LOADING':
      return { ...state, districts: { status: 'loading', data: null, error: null } }
    case 'DISTRICTS_LOADED':
      return { ...state, districts: { status: 'loaded', data: action.data, error: null } }
    case 'DISTRICTS_ERROR':
      return { ...state, districts: { status: 'error', data: null, error: action.error } }

    case 'SET_SELECTED_DISTRICT':
      return { ...state, selectedDistrictPcode: action.pcode }

    case 'SET_STREAM_THRESHOLD_CELLS': {
      // A changed threshold makes any already-fetched (or in-flight)
      // equal-interval/quantile/Jenks breaks for drainage_density/hand
      // stale -- they were computed against the OLD threshold's value
      // distribution. Reset just those two criteria's fetch state back
      // to 'idle' (only if currently checked and classified at all) so
      // ClassificationEditor's own effect re-fetches automatically, the
      // same mechanism an AOI change already relies on
      // (resetClassificationForCheckedCriteria) -- scoped to only the
      // two affected criteria here, not every checked one, since nothing
      // else depends on this threshold.
      const classification = { ...state.classification }
      for (const id of STREAM_THRESHOLD_SOURCE_IDS) {
        if (!classification[id]) continue
        classification[id] = {
          ...classification[id],
          fetch: { status: 'idle', min: null, max: null, equal_interval: null, quantile: null, jenks: null, error: null },
        }
      }
      return { ...state, streamThresholdCells: action.cells, classification }
    }

    case 'TOGGLE_CRITERION': {
      const nowChecked = !state.criteriaEnabled[action.id]
      const criteriaEnabled = { ...state.criteriaEnabled, [action.id]: nowChecked }

      const classification = { ...state.classification }
      if (nowChecked) {
        classification[action.id] = defaultClassificationEntry(CRITERIA_BY_ID[action.id])
      } else {
        delete classification[action.id]
      }

      return {
        ...state,
        criteriaEnabled,
        ahpMatrices: resyncWithinClusterMatrices(state.ahpMatrices, criteriaEnabled),
        manualWeights: resyncManualWeights(state.manualWeights, criteriaEnabled),
        classification,
        overlay: { status: 'idle', result: null, error: null, criteriaUsed: null, weightsUsed: null, progressLog: [] },
        dataGapNotice: nowChecked && DATA_GAP_CRITERIA.includes(action.id) ? [action.id] : state.dataGapNotice,
      }
    }

    case 'SELECT_ALL_CRITERIA': {
      const criteriaEnabled = Object.fromEntries(CRITERIA.map((c) => [c.id, true]))

      const classification = { ...state.classification }
      for (const criterion of CRITERIA) {
        if (!classification[criterion.id]) classification[criterion.id] = defaultClassificationEntry(criterion)
      }

      return {
        ...state,
        criteriaEnabled,
        ahpMatrices: resyncWithinClusterMatrices(state.ahpMatrices, criteriaEnabled),
        manualWeights: resyncManualWeights(state.manualWeights, criteriaEnabled),
        classification,
        overlay: { status: 'idle', result: null, error: null, criteriaUsed: null, weightsUsed: null, progressLog: [] },
        // Selecting all always includes hand/soil_infiltration, so always
        // (re-)show both their disclaimers together -- simpler and more
        // honest than only showing whichever happened not to be checked
        // already, and a deliberate bulk action is a reasonable moment to
        // reinforce both caveats at once.
        dataGapNotice: DATA_GAP_CRITERIA,
      }
    }

    case 'DISMISS_DATA_GAP_NOTICE':
      return { ...state, dataGapNotice: null }

    case 'SET_CLASSIFICATION_METHOD':
      return {
        ...state,
        classification: {
          ...state.classification,
          [action.id]: { ...state.classification[action.id], method: action.method },
        },
      }

    case 'SET_CLASSIFICATION_BREAKS':
      return {
        ...state,
        classification: {
          ...state.classification,
          [action.id]: { ...state.classification[action.id], breaks: action.breaks },
        },
      }

    case 'SET_CLASSIFICATION_CODE_CLASS':
      return {
        ...state,
        classification: {
          ...state.classification,
          [action.id]: {
            ...state.classification[action.id],
            riskClassByCode: { ...state.classification[action.id].riskClassByCode, [action.code]: action.riskClass },
          },
        },
      }

    case 'CLASSIFICATION_BREAKS_LOADING':
      return {
        ...state,
        classification: {
          ...state.classification,
          [action.id]: {
            ...state.classification[action.id],
            fetch: { ...state.classification[action.id].fetch, status: 'loading', error: null },
          },
        },
      }

    case 'CLASSIFICATION_BREAKS_LOADED':
      return {
        ...state,
        classification: {
          ...state.classification,
          [action.id]: {
            ...state.classification[action.id],
            fetch: { status: 'loaded', error: null, ...action.data },
          },
        },
      }

    case 'CLASSIFICATION_BREAKS_ERROR':
      return {
        ...state,
        classification: {
          ...state.classification,
          [action.id]: {
            ...state.classification[action.id],
            fetch: { ...state.classification[action.id].fetch, status: 'error', error: action.error },
          },
        },
      }

    case 'SET_WEIGHT_MODE':
      return action.mode === 'equal'
        ? {
            ...state,
            weightMode: 'equal',
            ahpMatrices: {
              cluster: { items: CANONICAL_CLUSTERS, matrix: identityMatrix(CANONICAL_CLUSTERS.length) },
              withinCluster: resyncWithinClusterMatrices(
                { withinCluster: {} },
                state.criteriaEnabled
              ).withinCluster,
            },
            ahp: { status: 'idle', result: null, error: null },
            manualWeights: resyncManualWeights({}, state.criteriaEnabled),
          }
        : { ...state, weightMode: action.mode }

    case 'SET_MANUAL_WEIGHT':
      return { ...state, manualWeights: { ...state.manualWeights, [action.id]: action.value } }

    case 'SET_CLUSTER_PAIRWISE':
      return {
        ...state,
        ahpMatrices: { ...state.ahpMatrices, cluster: { ...state.ahpMatrices.cluster, matrix: action.matrix } },
      }

    case 'SET_WITHIN_CLUSTER_PAIRWISE':
      return {
        ...state,
        ahpMatrices: {
          ...state.ahpMatrices,
          withinCluster: {
            ...state.ahpMatrices.withinCluster,
            [action.cluster]: { ...state.ahpMatrices.withinCluster[action.cluster], matrix: action.matrix },
          },
        },
      }

    case 'AHP_LOADING':
      return { ...state, ahp: { status: 'loading', result: state.ahp.result, error: null } }
    case 'AHP_LOADED':
      return { ...state, ahp: { status: 'loaded', result: action.result, error: null } }
    case 'AHP_ERROR':
      return { ...state, ahp: { status: 'error', result: null, error: action.error } }

    case 'OVERLAY_LOADING':
      return {
        ...state,
        overlay: { status: 'loading', result: null, error: null, criteriaUsed: null, weightsUsed: null, progressLog: [] },
        report: { status: 'idle', result: null, error: null },
        reportOverlayVisible: false,
        validation: { status: 'idle', result: null, error: null },
        meteorComparison: { status: 'idle', result: null, error: null },
      }
    // Real, backend-sent progress messages (POST /api/overlay/compute/
    // stream -- see api/client.js's computeOverlayStream and backend/
    // app/overlay/progress_stream.py's own docstring for why this is
    // genuine incremental progress, not an animated/fabricated bar).
    // Appended one at a time as each SSE event arrives, kept (not
    // cleared) through LOADED/ERROR below so the finished log stays
    // visible -- only OVERLAY_LOADING resets it, for the next compute.
    case 'OVERLAY_PROGRESS':
      return { ...state, overlay: { ...state.overlay, progressLog: [...state.overlay.progressLog, action.message] } }
    case 'OVERLAY_LOADED':
      // criteriaUsed/weightsUsed are a snapshot of exactly what was sent
      // to POST /api/overlay/compute for *this* result (ComputePanel
      // passes them through) -- read back by ResultPanel to show how
      // each raster was actually reclassified, so that display can never
      // drift out of sync with the live criteria/weighting panels if the
      // user changes a checkbox after computing but before recomputing.
      return {
        ...state,
        overlay: {
          status: 'loaded',
          result: action.result,
          error: null,
          criteriaUsed: action.criteriaUsed,
          weightsUsed: action.weightsUsed,
          progressLog: state.overlay.progressLog,
        },
      }
    case 'OVERLAY_ERROR':
      return {
        ...state,
        overlay: {
          status: 'error', result: null, error: action.error, criteriaUsed: null, weightsUsed: null,
          progressLog: state.overlay.progressLog,
        },
      }

    case 'REPORT_LOADING':
      return { ...state, report: { status: 'loading', result: null, error: null } }
    case 'REPORT_LOADED':
      // Auto-show the overlay -- a freshly generated report should be
      // immediately visible, not require a second click to reveal.
      return { ...state, report: { status: 'loaded', result: action.result, error: null }, reportOverlayVisible: true }
    case 'REPORT_ERROR':
      return { ...state, report: { status: 'error', result: null, error: action.error } }

    case 'TOGGLE_REPORT_OVERLAY':
      return { ...state, reportOverlayVisible: !state.reportOverlayVisible }

    case 'VALIDATION_EVENTS_LOADING':
      return { ...state, validationEvents: { status: 'loading', list: [], error: null } }
    case 'VALIDATION_EVENTS_LOADED':
      // Auto-select the first event if nothing's picked yet -- so the
      // picker (and the "Validate" button it gates) is immediately
      // usable without an extra click, the same reasoning
      // BasemapControl's own select defaults to state.basemapStyle
      // rather than requiring an explicit first choice.
      return {
        ...state,
        validationEvents: { status: 'loaded', list: action.events, error: null },
        selectedValidationEvent: state.selectedValidationEvent ?? action.events[0]?.key ?? null,
      }
    case 'VALIDATION_EVENTS_ERROR':
      return { ...state, validationEvents: { status: 'error', list: [], error: action.error } }

    case 'SET_VALIDATION_EVENT':
      return { ...state, selectedValidationEvent: action.event }

    case 'TOGGLE_VALIDATION_EXTENT_VISIBLE':
      return { ...state, validationExtentVisible: !state.validationExtentVisible }

    case 'VALIDATION_LOADING':
      return { ...state, validation: { status: 'loading', result: null, error: null } }
    case 'VALIDATION_LOADED':
      return { ...state, validation: { status: 'loaded', result: action.result, error: null } }
    case 'VALIDATION_ERROR':
      return { ...state, validation: { status: 'error', result: null, error: action.error } }

    case 'METEOR_COMPARISON_LOADING':
      return { ...state, meteorComparison: { status: 'loading', result: null, error: null } }
    case 'METEOR_COMPARISON_LOADED':
      return { ...state, meteorComparison: { status: 'loaded', result: action.result, error: null } }
    case 'METEOR_COMPARISON_ERROR':
      return { ...state, meteorComparison: { status: 'error', result: null, error: action.error } }

    default:
      return state
  }
}

export function AppStateProvider({ children }) {
  const [state, dispatch] = useReducer(reducer, undefined, initialState)
  const value = useMemo(() => ({ state, dispatch }), [state])

  // Applied here (not wherever SET_THEME happens to be dispatched from)
  // so the <html> attribute driving the dark CSS variables in index.css
  // is always in sync with state.theme, regardless of what triggers a change
  // (the toggle button, or a future "follow system" option).
  useEffect(() => {
    document.documentElement.dataset.theme = state.theme
  }, [state.theme])

  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>
}

export function useAppState() {
  const ctx = useContext(AppStateContext)
  if (!ctx) throw new Error('useAppState must be used within an AppStateProvider')
  return ctx
}

/** Criterion ids currently checked, in CRITERIA's own stable order. */
export function useSelectedCriteriaIds() {
  const { state } = useAppState()
  return useMemo(() => CRITERIA.filter((c) => state.criteriaEnabled[c.id]).map((c) => c.id), [state.criteriaEnabled])
}

/**
 * The final_weights this app would submit to POST /api/overlay/compute
 * right now, and whether that weight set is actually usable -- the
 * single source of truth both the weighting UI and the compute button
 * read, so they can never disagree about whether compute is allowed.
 */
export function useFinalWeights() {
  const { state } = useAppState()
  const selectedIds = useSelectedCriteriaIds()

  return useMemo(() => {
    if (selectedIds.length === 0) {
      return { finalWeights: null, complete: false, reason: 'Select at least one criterion.' }
    }

    if (state.weightMode === 'equal') {
      const w = 1 / selectedIds.length
      return { finalWeights: Object.fromEntries(selectedIds.map((id) => [id, w])), complete: true, reason: null }
    }

    if (state.weightMode === 'manual') {
      const total = selectedIds.reduce((sum, id) => sum + (state.manualWeights[id] || 0), 0)
      if (total <= 0) {
        return { finalWeights: null, complete: false, reason: 'Enter at least one positive weight.' }
      }
      const finalWeights = Object.fromEntries(selectedIds.map((id) => [id, (state.manualWeights[id] || 0) / total]))
      return { finalWeights, complete: true, reason: null }
    }

    // AHP mode. A successful (200) response already guarantees every
    // matrix actually submitted -- the top-level 5-cluster comparison,
    // plus a within-cluster comparison for every cluster that has >=1
    // selected criterion -- passed CR < 0.10 (backend/app/ahp/
    // hierarchy.py raises before returning anything if any matrix
    // fails), and that every currently selected criterion already has a
    // weight in `final_weights` (useAhpAutoCompute builds
    // within_cluster_comparisons from exactly the selected criteria's
    // clusters, so nothing selected is ever left out of a successful
    // response).
    //
    // Deliberately NOT gating on the backend's own `complete` flag: that
    // flag means "all 5 canonical clusters have a within-cluster
    // matrix", which this app doesn't require (mirroring equal-weights
    // mode, which never required a criterion in every cluster either --
    // see config/criteria.js's note on the empty Exposure cluster). A
    // cluster with no selected criteria still "spends" some of the top-
    // level comparison's weight mass with nothing to receive it, so the
    // raw final_weights restricted to the selected criteria doesn't sum
    // to 1 -- renormalizing over just those recovers a valid, complete
    // weight set that preserves the AHP-computed *relative* proportions
    // among what's actually selected.
    if (state.ahp.status === 'error') {
      const failures = state.ahp.error?.failures
      const reason = failures
        ? `Inconsistent judgments (CR ≥ 0.10) in: ${failures.map((f) => `${f.matrix} (CR=${f.consistency_ratio.toFixed(2)})`).join(', ')}.`
        : state.ahp.error?.message || 'AHP computation failed.'
      return { finalWeights: null, complete: false, reason }
    }
    if (state.ahp.status !== 'loaded' || !state.ahp.result) {
      return { finalWeights: null, complete: false, reason: 'Set pairwise comparisons to compute AHP weights.' }
    }
    const raw = state.ahp.result.final_weights
    const total = selectedIds.reduce((sum, id) => sum + (raw[id] || 0), 0)
    if (total <= 0) {
      return { finalWeights: null, complete: false, reason: 'AHP weights not yet available for the selected criteria.' }
    }
    const finalWeights = Object.fromEntries(selectedIds.map((id) => [id, raw[id] / total]))
    return { finalWeights, complete: true, reason: null }
  }, [selectedIds, state.weightMode, state.ahp, state.manualWeights])
}
