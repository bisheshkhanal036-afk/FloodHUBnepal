// Client-side geometry helpers for the "draw a bbox" AOI path.
//
// AREA_CAP_KM2 mirrors schemas/aoi.schema.json's max_area_km2 default /
// backend/app/common/aoi.py's MAX_AREA_KM2 — kept as a literal constant
// here (not fetched from the backend) since it's a fixed schema default,
// not runtime config; the backend's own POST endpoints remain the
// authoritative check regardless of what this constant says.
export const AREA_CAP_KM2 = 500.0

/**
 * Approximate area of a EPSG:4326 bbox in km^2, via an equirectangular
 * (flat-earth) approximation scaled by the bbox's mean latitude. This is
 * deliberately NOT the same UTM-reprojected calculation
 * backend/app/data/aoi.py's AOI.area_km2 performs (SPEC.md, "CRS
 * convention": area must be computed in EPSG:32645, never raw degrees)
 * -- doing that precisely in the browser would need a real UTM
 * projection of all 4 corners for a result that's only ever used here
 * as a fast pre-submit warning. The backend's own area-cap check (same
 * endpoints this app calls) is what actually enforces the cap; this is
 * just close enough to warn the user before they submit, not the
 * authority on whether a request will be accepted.
 */
export function approxBboxAreaKm2([minLng, minLat, maxLng, maxLat]) {
  const meanLatRad = ((minLat + maxLat) / 2) * (Math.PI / 180)
  const metersPerDegLng = 111_320 * Math.cos(meanLatRad)
  const metersPerDegLat = 110_540
  const widthM = (maxLng - minLng) * metersPerDegLng
  const heightM = (maxLat - minLat) * metersPerDegLat
  return Math.abs(widthM * heightM) / 1_000_000
}

/** Normalizes two arbitrary drag corners into [minLng, minLat, maxLng, maxLat]. */
export function cornersToBbox([lng1, lat1], [lng2, lat2]) {
  return [Math.min(lng1, lng2), Math.min(lat1, lat2), Math.max(lng1, lng2), Math.max(lat1, lat2)]
}

/** A bbox as a closed GeoJSON Polygon ring, for map preview/highlight layers. */
export function bboxToPolygon([minLng, minLat, maxLng, maxLat]) {
  return {
    type: 'Polygon',
    coordinates: [
      [
        [minLng, minLat],
        [maxLng, minLat],
        [maxLng, maxLat],
        [minLng, maxLat],
        [minLng, minLat],
      ],
    ],
  }
}
