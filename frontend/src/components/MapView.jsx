// The map: basemap, draw-rectangle AOI interaction, basin polygon layer
// (color-coded by support_status, clickable), and the computed risk
// surface rendered as a colorized raster overlay. All MapLibre-specific
// code lives here, kept separate from the panels so a future phase
// (shelter markers, vulnerability classes) can add its own layers here
// without touching the state/panel logic.
import { fromArrayBuffer } from 'geotiff'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useRef } from 'react'
import { fetchRiskSurfaceBytes, getBasinAOI } from '../api/client'
import { riskValueToRgb, SUPPORT_STATUS_COLORS } from '../lib/colorRamp'
import { AREA_CAP_KM2, approxBboxAreaKm2, bboxToPolygon, cornersToBbox } from '../lib/geo'
import { gridCornersToWgs84 } from '../lib/proj'
import { useAppState } from '../state/AppStateContext'

const KATHMANDU_CENTER = [85.324, 27.7172]
const DEFAULT_ZOOM = 11

// Two free, no-API-key raster basemaps for night mode: OSM's own
// standard ("Carto" light) tile set, and CARTO's free "Dark Matter"
// tiles (rendered from OSM data too, no key/signup required, verified
// live) for dark mode -- OSM itself doesn't publish an official dark
// style. Both attributions are shown together regardless of which is
// currently active, simplest way to always satisfy both licenses'
// attribution requirement without wiring a second dynamic control.
const LIGHT_TILES = [
  'https://a.tile.openstreetmap.org/{z}/{x}/{y}.png',
  'https://b.tile.openstreetmap.org/{z}/{x}/{y}.png',
  'https://c.tile.openstreetmap.org/{z}/{x}/{y}.png',
]
const DARK_TILES = [
  'https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
  'https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
  'https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
  'https://d.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
]
const BASEMAP_ATTRIBUTION = '© OpenStreetMap contributors © CARTO'

function basemapStyle(theme) {
  return {
    version: 8,
    sources: {
      osm: {
        type: 'raster',
        tiles: theme === 'dark' ? DARK_TILES : LIGHT_TILES,
        tileSize: 256,
        attribution: BASEMAP_ATTRIBUTION,
      },
    },
    layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
  }
}

const DRAW_PREVIEW_SOURCE = 'draw-preview'
const BASINS_SOURCE = 'basins'
const RISK_SURFACE_SOURCE = 'risk-surface'

export default function MapView() {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const stateRef = useRef(null)
  const { state, dispatch } = useAppState()
  stateRef.current = state

  // --- map init (once) ---
  useEffect(() => {
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: basemapStyle(stateRef.current.theme),
      center: KATHMANDU_CENTER,
      zoom: DEFAULT_ZOOM,
    })
    mapRef.current = map
    map.addControl(new maplibregl.NavigationControl(), 'top-right')

    map.on('load', () => {
      map.addSource(DRAW_PREVIEW_SOURCE, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      map.addLayer({
        id: 'draw-preview-fill',
        type: 'fill',
        source: DRAW_PREVIEW_SOURCE,
        paint: { 'fill-color': '#2563eb', 'fill-opacity': 0.15 },
      })
      map.addLayer({
        id: 'draw-preview-line',
        type: 'line',
        source: DRAW_PREVIEW_SOURCE,
        paint: { 'line-color': '#2563eb', 'line-width': 2 },
      })

      setupDrawInteraction(map, stateRef, dispatch)
    })

    return () => {
      map.remove()
      mapRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- init once; handlers read stateRef for live state
  }, [])

  // --- night mode: swap basemap tiles live, no full style/map reload ---
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const apply = () => map.getSource('osm')?.setTiles(state.theme === 'dark' ? DARK_TILES : LIGHT_TILES)
    if (map.isStyleLoaded()) apply()
    else map.once('load', apply)
  }, [state.theme])

  // --- draw mode: disable/enable normal map dragging so drag = draw, not pan ---
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const apply = () => {
      if (state.aoiMode === 'draw') map.dragPan.disable()
      else map.dragPan.enable()
    }
    if (map.isStyleLoaded()) apply()
    else map.once('load', apply)
  }, [state.aoiMode])

  // --- basins layer ---
  useEffect(() => {
    const map = mapRef.current
    if (!map || !state.basins.data) return

    const render = () => {
      if (map.getSource(BASINS_SOURCE)) {
        map.getSource(BASINS_SOURCE).setData(state.basins.data)
      } else {
        map.addSource(BASINS_SOURCE, { type: 'geojson', data: state.basins.data })
        map.addLayer({
          id: 'basins-fill',
          type: 'fill',
          source: BASINS_SOURCE,
          paint: {
            'fill-color': [
              'match',
              ['get', 'support_status'],
              'fully_in_nepal',
              SUPPORT_STATUS_COLORS.fully_in_nepal,
              'partial_likely_adequate',
              SUPPORT_STATUS_COLORS.partial_likely_adequate,
              'likely_degraded_at_edges',
              SUPPORT_STATUS_COLORS.likely_degraded_at_edges,
              '#999999',
            ],
            'fill-opacity': 0.35,
          },
        })
        map.addLayer({
          id: 'basins-line',
          type: 'line',
          source: BASINS_SOURCE,
          paint: { 'line-color': '#333333', 'line-width': 0.5 },
        })
        map.addLayer({
          id: 'basins-selected',
          type: 'line',
          source: BASINS_SOURCE,
          paint: { 'line-color': '#111827', 'line-width': 3 },
          filter: ['==', ['get', 'hybas_id'], -1],
        })

        map.on('click', 'basins-fill', async (e) => {
          if (stateRef.current.aoiMode !== 'basin') return
          const hybasId = e.features[0].properties.hybas_id
          dispatch({ type: 'SET_SELECTED_BASIN_ID', hybasId })
          try {
            const aoi = await getBasinAOI(hybasId)
            dispatch({ type: 'SET_AOI', aoi: { bbox: aoi.bbox, polygon: aoi.polygon, source: 'basin', basinId: hybasId } })
          } catch (error) {
            dispatch({ type: 'SET_AREA_WARNING', message: error.message })
          }
        })
        map.on('mouseenter', 'basins-fill', () => {
          if (stateRef.current.aoiMode === 'basin') map.getCanvas().style.cursor = 'pointer'
        })
        map.on('mouseleave', 'basins-fill', () => {
          map.getCanvas().style.cursor = ''
        })
      }
    }

    if (map.isStyleLoaded()) render()
    else map.once('load', render)
  }, [state.basins.data, dispatch])

  // highlight the selected basin
  useEffect(() => {
    const map = mapRef.current
    if (!map || !map.getLayer('basins-selected')) return
    map.setFilter('basins-selected', ['==', ['get', 'hybas_id'], state.selectedBasinId ?? -1])
  }, [state.selectedBasinId])

  // --- fit view to the current AOI ---
  useEffect(() => {
    const map = mapRef.current
    if (!map || !state.aoi) return
    const [minLng, minLat, maxLng, maxLat] = state.aoi.bbox
    const fit = () => map.fitBounds([[minLng, minLat], [maxLng, maxLat]], { padding: 60, maxZoom: 14 })
    if (map.isStyleLoaded()) fit()
    else map.once('load', fit)
  }, [state.aoi])

  // --- risk surface raster overlay ---
  useEffect(() => {
    const map = mapRef.current
    const result = state.overlay.result
    if (!map || !result) return

    let cancelled = false

    async function render() {
      const bytes = await fetchRiskSurfaceBytes(result.data_url)
      if (cancelled) return
      const tiff = await fromArrayBuffer(bytes)
      const image = await tiff.getImage()
      const [raster] = await image.readRasters()
      if (cancelled) return

      const { width, height } = result.grid
      const canvas = document.createElement('canvas')
      canvas.width = width
      canvas.height = height
      const ctx = canvas.getContext('2d')
      const imageData = ctx.createImageData(width, height)
      const nodata = result.nodata_value

      for (let i = 0; i < raster.length; i++) {
        const v = raster[i]
        const o = i * 4
        if (nodata !== null && v === nodata) {
          imageData.data[o + 3] = 0
          continue
        }
        const [r, g, b] = riskValueToRgb(v)
        imageData.data[o] = r
        imageData.data[o + 1] = g
        imageData.data[o + 2] = b
        imageData.data[o + 3] = 255
      }
      ctx.putImageData(imageData, 0, 0)
      const dataUrl = canvas.toDataURL('image/png')
      const coordinates = gridCornersToWgs84(result.grid)

      const apply = () => {
        if (map.getLayer('risk-surface-layer')) map.removeLayer('risk-surface-layer')
        if (map.getSource(RISK_SURFACE_SOURCE)) map.removeSource(RISK_SURFACE_SOURCE)
        map.addSource(RISK_SURFACE_SOURCE, { type: 'image', url: dataUrl, coordinates })
        map.addLayer({ id: 'risk-surface-layer', type: 'raster', source: RISK_SURFACE_SOURCE, paint: { 'raster-opacity': 0.75 } })
      }
      if (map.isStyleLoaded()) apply()
      else map.once('load', apply)
    }

    render()
    return () => {
      cancelled = true
    }
  }, [state.overlay.result])

  return <div ref={containerRef} className="map-view" />
}

function setupDrawInteraction(map, stateRef, dispatch) {
  let startLngLat = null

  map.on('mousedown', (e) => {
    if (stateRef.current.aoiMode !== 'draw') return
    startLngLat = [e.lngLat.lng, e.lngLat.lat]
    e.preventDefault()
  })

  map.on('mousemove', (e) => {
    if (!startLngLat) return
    const bbox = cornersToBbox(startLngLat, [e.lngLat.lng, e.lngLat.lat])
    map.getSource(DRAW_PREVIEW_SOURCE)?.setData({
      type: 'FeatureCollection',
      features: [{ type: 'Feature', properties: {}, geometry: bboxToPolygon(bbox) }],
    })
  })

  map.on('mouseup', (e) => {
    if (!startLngLat) return
    const bbox = cornersToBbox(startLngLat, [e.lngLat.lng, e.lngLat.lat])
    startLngLat = null

    // A click without a real drag isn't a rectangle -- ignore it rather
    // than submitting a degenerate zero-area AOI.
    if (bbox[2] - bbox[0] < 1e-6 || bbox[3] - bbox[1] < 1e-6) {
      map.getSource(DRAW_PREVIEW_SOURCE)?.setData({ type: 'FeatureCollection', features: [] })
      return
    }

    const areaKm2 = approxBboxAreaKm2(bbox)
    if (areaKm2 > AREA_CAP_KM2) {
      dispatch({
        type: 'SET_AREA_WARNING',
        message: `Drawn area is approximately ${areaKm2.toFixed(1)} km², which exceeds the ${AREA_CAP_KM2} km² cap. Draw a smaller area.`,
      })
      map.getSource(DRAW_PREVIEW_SOURCE)?.setData({ type: 'FeatureCollection', features: [] })
      return
    }

    dispatch({ type: 'SET_AOI', aoi: { bbox, polygon: null, source: 'draw' } })
  })
}
