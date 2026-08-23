// Thin fetch wrappers around the 5 real backend endpoints this app uses.
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

/** GET /api/basins -- a GeoJSON FeatureCollection, ~3.9MB uncompressed. */
export function listBasins() {
  return requestJson('/api/basins')
}

/** GET /api/basins/{hybas_id}/aoi -- {bbox, polygon}, ready for AOIInput. */
export function getBasinAOI(hybasId) {
  return requestJson(`/api/basins/${hybasId}/aoi`)
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

/** Absolute, downloadable URL for a backend-relative data_url (risk_surface/hazard_classes GeoTIFFs) -- a plain `<a href>` needs the full origin, unlike fetchRiskSurfaceBytes's own internal fetch(). */
export function absoluteDataUrl(relativeUrl) {
  return `${API_BASE_URL}${relativeUrl}`
}
