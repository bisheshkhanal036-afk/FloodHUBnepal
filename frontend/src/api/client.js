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

/** Fetches the computed risk surface GeoTIFF's raw bytes from data_url. */
export async function fetchRiskSurfaceBytes(dataUrl) {
  const response = await request(dataUrl)
  return response.arrayBuffer()
}

/** POST /api/overlay/criteria/breaks -- equal-interval/quantile/Jenks candidate reclassification breaks for one criterion over one AOI. */
export function computeCriterionBreaks(payload) {
  return requestJson('/api/overlay/criteria/breaks', { method: 'POST', body: JSON.stringify(payload) })
}
