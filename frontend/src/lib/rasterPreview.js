// Shared GeoTIFF-decode-to-canvas-dataURL logic -- MapView.jsx's own
// risk-surface map layer and CriterionSnapshot.jsx's per-criterion
// thumbnails both need "decode a single-band GeoTIFF, color each pixel,
// produce a data: URL", differing only in target size and color
// function. One implementation, not two.
import { fromArrayBuffer } from 'geotiff'

/**
 * Decodes a single-band GeoTIFF's raw bytes into a `data:image/png` URL,
 * coloring each pixel via `colorFn(value) -> [r, g, b]` and treating
 * `nodata` pixels as fully transparent.
 *
 * `maxSize`, when given, requests a downsampled decode at most that many
 * pixels on the longer side, via geotiff.js's own readRasters resize
 * support (`resampleMethod: 'nearest'` -- never bilinear/average, since
 * a downsampled preview of discrete/categorical class values must never
 * blend across class boundaries, matching this project's own
 * established resampling-method convention for categorical data --
 * SPEC.md §2.2). Omit for a full-resolution decode (MapView's own
 * map-layer rendering, which needs every pixel accurate for correct
 * geographic display).
 *
 * Returns `{ dataUrl, width, height }` -- the decoded (possibly
 * downsampled) pixel dimensions, for a caller that needs to know the
 * actual canvas size (e.g. to size an <img>).
 */
export async function decodeGeoTiffToDataUrl(bytes, { nodata, colorFn, maxSize } = {}) {
  const tiff = await fromArrayBuffer(bytes)
  const image = await tiff.getImage()

  let width = image.getWidth()
  let height = image.getHeight()
  const readOptions = {}
  if (maxSize && Math.max(width, height) > maxSize) {
    const scale = maxSize / Math.max(width, height)
    width = Math.max(1, Math.round(width * scale))
    height = Math.max(1, Math.round(height * scale))
    readOptions.width = width
    readOptions.height = height
    readOptions.resampleMethod = 'nearest'
  }

  const [raster] = await image.readRasters(readOptions)

  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  const imageData = ctx.createImageData(width, height)

  for (let i = 0; i < raster.length; i++) {
    const v = raster[i]
    const o = i * 4
    if (nodata !== undefined && nodata !== null && v === nodata) {
      imageData.data[o + 3] = 0
      continue
    }
    const [r, g, b] = colorFn(v)
    imageData.data[o] = r
    imageData.data[o + 1] = g
    imageData.data[o + 2] = b
    imageData.data[o + 3] = 255
  }
  ctx.putImageData(imageData, 0, 0)
  return { dataUrl: canvas.toDataURL('image/png'), width, height }
}
