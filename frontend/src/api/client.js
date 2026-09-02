// Thin fetch wrappers around the real backend endpoints this app uses.
// No mocking/stubbing anywhere in this module — every function here
// hits the actual FastAPI service.
import { ApiError, parseErrorDetail } from './apiError'

// The browser (not the Vite dev server) makes these calls, so this must
// be the backend's own host-exposed origin (docker-compose.yml binds it
// to 127.0.0.1:8000), not a same-origin relative path. Overridable via
// a .env file for any other deployment.
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

async function request(path, options = {}) {
  let response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: { 'Content-Type': 'application/json', ...options.headers },
      ...options,
    })
  } catch (networkError) {
    throw new ApiError(
      `Could not reach the backend at ${API_BASE_URL} (${networkError.message}). Is it running?`,
      { status: 0 }
    )
  }

  if (!response.ok) {
    let body = null
    try {
      body = await response.json()
    } catch {
      // non-JSON error body -- parseErrorDetail falls back to a generic message
    }
    throw parseErrorDetail(response.status, body)
  }

  return response
}

async function requestJson(path, options) {
  const response = await request(path, options)
  return response.json()
}

/** POST /api/ahp/compute -- see backend/app/ahp/models.py for the exact shape. */
export function computeAHP(payload) {
  return requestJson('/api/ahp/compute', { method: 'POST', body: JSON.stringify(payload) })
}

/**
 * GET /api/basins?level=8|9 -- a GeoJSON FeatureCollection. `level`
 * selects which HydroBASINS resolution to fetch: 8 (~547 basins over
 * Nepal's rough extent, coarser/larger catchments) or 9 (finer
 * sub-catchments, more/smaller features -- a noticeably bigger payload).
 * Defaults to 8, matching the backend's own default
 * (app.data.basins.DEFAULT_BASIN_LEVEL) so an omitted level behaves
 * exactly as before this parameter existed.
 */
export function listBasins(level = 8) {
  return requestJson(`/api/basins?level=${level}`)
}

/** GET /api/basins/{hybas_id}/aoi?level=8|9 -- {bbox, polygon}, ready for AOIInput. `level` must match whichever level `hybasId` was listed at (HYBAS_IDs never collide across levels, but the backend only searches the requested level's file). */
export function getBasinAOI(hybasId, level = 8) {
  return requestJson(`/api/basins/${hybasId}/aoi?level=${level}`)
}

/** GET /api/districts -- a GeoJSON FeatureCollection of all 77 of Nepal's districts. */
export function listDistricts() {
  return requestJson('/api/districts')
}

/** GET /api/districts/{pcode}/aoi -- {bbox, polygon}, ready for AOIInput. */
export function getDistrictAOI(pcode) {
  return requestJson(`/api/districts/${pcode}/aoi`)
}

/** POST /api/overlay/compute -- see backend/app/overlay/models.py. */
export function computeOverlay(payload) {
  return requestJson('/api/overlay/compute', { method: 'POST', body: JSON.stringify(payload) })
}

/**
 * POST /api/overlay/compute/stream -- same computation as computeOverlay,
 * but consumes real Server-Sent Events as the backend actually does the
 * work (see backend/app/overlay/progress_stream.py's own docstring: this
 * is genuine incremental progress, not a fabricated/animated bar).
 * `onProgress(message)` fires for each progress event; the returned
 * promise resolves with the same result shape computeOverlay's does, or
 * rejects with an ApiError matching parseErrorDetail's shape (so
 * existing error-rendering code doesn't need to know this used a
 * different transport than computeOverlay).
 *
 * No EventSource here: the browser's native SSE client only supports
 * GET with no custom body, and this needs a POST with a JSON payload --
 * a plain fetch() + manually reading/parsing the streamed response body
 * is the standard way to do SSE-over-POST, and keeps this file's own
 * "thin wrappers, no new dependency" convention (see this file's header
 * comment) rather than adding an SSE library for one endpoint.
 */
export async function computeOverlayStream(payload, onProgress) {
  const response = await request('/api/overlay/compute/stream', { method: 'POST', body: JSON.stringify(payload) })
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // SSE frames are separated by a blank line ("\n\n") -- split off
    // every COMPLETE frame currently in the buffer, leaving any trailing
    // partial frame (a chunk boundary can land mid-frame) for the next read.
    const frames = buffer.split('\n\n')
    buffer = frames.pop()

    for (const frame of frames) {
      const line = frame.split('\n').find((l) => l.startsWith('data: '))
      if (!line) continue
      const event = JSON.parse(line.slice('data: '.length))

      if (event.type === 'progress') {
        onProgress(event.message)
      } else if (event.type === 'done') {
        return event.result
      } else if (event.type === 'error') {
        throw new ApiError(event.message, { status: response.status, code: event.error })
      }
    }
  }

  // The stream ended without ever sending a "done"/"error" terminal
  // event -- a connection drop, not a clean completion. Never silently
  // report success for this.
  throw new ApiError('The compute stream ended unexpectedly before finishing.', { status: response.status })
}

/** Fetches the computed risk surface GeoTIFF's raw bytes from data_url. */
export async function fetchRiskSurfaceBytes(dataUrl) {
  const response = await request(dataUrl)
  return response.arrayBuffer()
}

/** POST /api/overlay/criteria/breaks -- equal-interval/quantile/Jenks candidate reclassification breaks for one criterion over one AOI. */
export function computeCriterionBreaks(payload) {
  return requestJson('/api/overlay/criteria/breaks', { method: 'POST', body: JSON.stringify(payload) })
}

/** POST /api/overlay/report -- the vulnerability-classification/computation report. See backend/app/overlay/models.py's VulnerabilityReportRequest/Response. */
export function generateReport(payload) {
  return requestJson('/api/overlay/report', { method: 'POST', body: JSON.stringify(payload) })
}

/**
 * POST /api/overlay/shelters -- ranks real OSM building footprints in
 * the AOI as candidate emergency-shelter sites (safety/accessibility/
 * service-value suitability; see backend/app/overlay/shelters.py's own
 * docstring). Same aoi/criteria/final_weights/complete shape as
 * computeOverlay's own payload, plus the optional shelter-specific
 * knobs; reuses POST /compute's own cache the same way generateReport
 * does.
 */
export function identifyShelterSites(payload) {
  return requestJson('/api/overlay/shelters', { method: 'POST', body: JSON.stringify(payload) })
}

/** GET /api/overlay/validation-events -- [{key, label}] for every real, satellite-observed flood event a risk surface can be validated against (backend/app/data/validation_extent.py's config.VALIDATION_EVENTS). */
export function listValidationEvents() {
  return requestJson('/api/overlay/validation-events')
}

/**
 * POST /api/overlay/validate -- success-rate/AUC validation of a
 * computed risk surface against a real, satellite-observed flood
 * extent (not another model's output -- see backend/app/overlay/
 * validate.py's own docstring). Same aoi/criteria/final_weights/complete
 * shape as computeOverlay's own payload, plus `event`; reuses POST
 * /compute's own cache, so validating an AOI/criteria/weights
 * combination already computed via computeOverlay doesn't recompute the
 * risk surface.
 */
export function validateRiskSurface(payload) {
  return requestJson('/api/overlay/validate', { method: 'POST', body: JSON.stringify(payload) })
}

/** GET /api/overlay/validation-events/{event}/extent.geojson -- the named event's real flood-extent polygon, for the map's own toggleable reference overlay (MapView.jsx's ValidationExtentControl) -- display-simplified, never used for the actual validation math itself. */
export function getValidationExtentGeoJSON(event) {
  return requestJson(`/api/overlay/validation-events/${encodeURIComponent(event)}/extent.geojson`)
}

/**
 * POST /api/overlay/compare-meteor -- agreement between a computed risk
 * surface and METEOR's own modeled flood hazard, NOT validation against
 * real-world accuracy (see backend/app/overlay/meteor_comparison.py's
 * own docstring, and MeteorComparisonPanel.jsx, which is deliberately a
 * separate component/step from ValidationPanel.jsx for the same
 * reason). Same aoi/criteria/final_weights/complete shape as
 * computeOverlay's own payload -- no `event` field, since only one
 * METEOR flood_type/return_period is ever locally available at a time
 * (the response's own meteor_flood_type/meteor_return_period say
 * which). Reuses POST /compute's own cache the same way validateRiskSurface does.
 */
export function compareToMeteor(payload) {
  return requestJson('/api/overlay/compare-meteor', { method: 'POST', body: JSON.stringify(payload) })
}

/** Absolute, downloadable URL for a backend-relative data_url (risk_surface/hazard_classes GeoTIFFs) -- a plain `<a href>` needs the full origin, unlike fetchRiskSurfaceBytes's own internal fetch(). */
export function absoluteDataUrl(relativeUrl) {
  return `${API_BASE_URL}${relativeUrl}`
}

// --- Citizen Mode -----------------------------------------------------
// Deliberately separate from the overlay endpoints above: Citizen Mode
// asks one fixed question with one validated configuration, and cannot
// be reconfigured from the client (see backend/app/citizen/router.py).

/** Flood susceptibility at one point, in plain language. `lang` is 'en' | 'ne'. */
export function assessLocation({ lat, lon, lang = 'en' }) {
  return requestJson('/api/citizen/assess', {
    method: 'POST',
    body: JSON.stringify({ lat, lon, lang }),
  })
}

/** What Citizen Mode covers and how accurate it measured. */
export function fetchCitizenCoverage() {
  return requestJson('/api/citizen/coverage')
}
