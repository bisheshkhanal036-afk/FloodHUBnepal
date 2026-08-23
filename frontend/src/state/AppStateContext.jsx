// Central app state for the one cohesive page (map + AOI + criteria +
// weighting + compute): a single reducer, exposed via context, so
// sibling panels (AOI, criteria, weighting, compute, map) all read and
// act on the same source of truth without prop-drilling. Structured as
// its own module (not folded into App.jsx) specifically so a future
// phase (vulnerability classification, shelter markers) can extend this
// state rather than needing to restructure it.
import { createContext, useContext, useEffect, useMemo, useReducer } from 'react'
import { CANONICAL_CLUSTERS, CRITERIA, CRITERIA_BY_ID, criteriaByCluster } from '../config/criteria'
import { identityMatrix, resizeMatrix } from '../lib/ahpMatrix'
import { defaultClassificationEntry } from '../lib/classification'

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

    aoiMode: 'draw',
    aoi: null, // { bbox: [minx,miny,maxx,maxy], polygon: geom|null, source: 'draw'|'basin', basinId?, label? }
    areaWarning: null,

    basins: { status: 'idle', data: null, error: null },
    selectedBasinId: null,

    criteriaEnabled: Object.fromEntries(CRITERIA.map((c) => [c.id, false])),

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

    // The vulnerability-classification/computation report (POST /api/
    // overlay/report) -- a separate, heavier, optional follow-up to a
    // successful compute, not part of the core AOI->criteria->weighting
    // ->compute flow, so it gets its own status slice rather than being
    // folded into `overlay`. Reset whenever a new compute starts
    // (OVERLAY_LOADING) -- any existing report describes a result that's
    // about to be superseded, so it can't stay displayed as current.
    report: { status: 'idle', result: null, error: null },
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
      }
    }

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
      return { ...state, report: { status: 'loaded', result: action.result, error: null } }
    case 'REPORT_ERROR':
      return { ...state, report: { status: 'error', result: null, error: action.error } }

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
