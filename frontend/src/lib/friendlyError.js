// Translates an ApiError (api/apiError.js) into a plain-language
// headline a non-technical user can actually act on, keyed off the
// backend's own `error` code (every HTTPException(detail={"error": ...})
// this app's backend raises — see backend/app/*/router.py) and
// `status`/network-failure case. The raw backend message is never
// discarded — ErrorNotice.jsx still shows it underneath, collapsed, so
// this is a friendlier HEADLINE on top of the real detail, not a
// replacement for it (this project's own "document the real cause,
// never hide it" convention, applied to end-user-facing text too).
//
// New backend error codes don't need a matching entry here to work —
// UNMAPPED_FALLBACK covers anything this list doesn't yet know about,
// same as `fallback` covers a `null`/network-less error entirely — this
// is a translation layer, not a whitelist of what's allowed to fail.
const CODE_MESSAGES = {
  data_source_unavailable: 'One of the data sources this needs is temporarily unavailable.',
  overlay_validation_error: "This request isn't valid for the current setup.",
  overlay_data_error: 'The source data for this area had a data-quality problem.',
  ahp_validation_error: 'The pairwise comparison matrix is not a valid input.',
  ahp_consistency_check_failed: 'Your pairwise comparisons are too inconsistent to use — see the flagged pairs below.',
  shelter_validation_error: "This request isn't valid for shelter identification.",
  basin_not_found: "That basin couldn't be found.",
  basins_unavailable: 'Basin data is temporarily unavailable.',
  district_not_found: "That district couldn't be found.",
  districts_unavailable: 'District data is temporarily unavailable.',
  invalid_basin_level: 'That basin level is not supported.',
  meteor_tile_not_found: 'METEOR has no data for this map tile.',
  criterion_raster_not_found: "This criterion's raster isn't available yet — generate the report first.",
  risk_surface_not_found: "This result isn't available yet — try computing again.",
  validation_event_not_found: "That validation event isn't available.",
  citizen_data_unavailable: 'Citizen Mode data is temporarily unavailable.',
}

const UNMAPPED_FALLBACK = 'The request to the server failed.'

/**
 * Returns { headline, detail } for a caught error. `error` is normally
 * an ApiError (api/apiError.js) but this degrades gracefully for a
 * plain JS Error too (never assume the shape), and for `null`/`undefined`
 * (falls back entirely to the caller-supplied `fallback`).
 */
export function friendlyErrorMessage(error, fallback = 'Something went wrong.') {
  if (!error) return { headline: fallback, detail: null }

  // api/client.js's own network-failure path (fetch() itself threw,
  // e.g. the backend isn't running) — status 0, no backend error code
  // at all, so it needs its own distinct headline rather than a generic
  // "request failed" that would misleadingly suggest the backend
  // actually responded.
  if (error.status === 0) {
    return { headline: "Can't reach the backend — check that it's running.", detail: error.message || null }
  }

  const headline = (error.code && CODE_MESSAGES[error.code]) || fallback || UNMAPPED_FALLBACK
  const detail = error.message && error.message !== headline ? error.message : null
  return { headline, detail }
}
