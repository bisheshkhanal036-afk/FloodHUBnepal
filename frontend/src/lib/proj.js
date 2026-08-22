// EPSG:32645 (WGS 84 / UTM Zone 45N) <-> EPSG:4326 (WGS 84 lon/lat),
// mirroring backend/app/data/aoi.py's own CRS convention (SPEC.md, "CRS
// convention"): the risk surface's grid is stored in EPSG:32645 meters,
// but MapLibre needs EPSG:4326 degrees to place it on the map.
import proj4 from 'proj4'

proj4.defs('EPSG:32645', '+proj=utm +zone=45 +datum=WGS84 +units=m +no_defs +type=crs')

const toWgs84 = proj4('EPSG:32645', 'EPSG:4326')

/**
 * The 4 corners of a risk-surface grid (backend/app/data/grid.py's
 * AOIGrid: origin_x/origin_y is the top-left corner, Y increases
 * northward while raster rows increase southward), reprojected to
 * EPSG:4326 in the order MapLibre's `canvas`/`image` source coordinates
 * expect: [top-left, top-right, bottom-right, bottom-left].
 */
export function gridCornersToWgs84(grid) {
  const { origin_x: ox, origin_y: oy, width, height, resolution_m: res } = grid
  const widthM = width * res
  const heightM = height * res

  const corners = [
    [ox, oy], // top-left
    [ox + widthM, oy], // top-right
    [ox + widthM, oy - heightM], // bottom-right
    [ox, oy - heightM], // bottom-left
  ]

  return corners.map(([x, y]) => toWgs84.forward([x, y]))
}
