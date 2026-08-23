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

// 5 free, no-API-key raster basemaps -- every one of these was verified
// live during implementation (a real tile fetch returning a genuine
// 256x256 image, not an error page with a 200 status) before being added
// here, the same diligence this project already applied to the original
// OSM/CARTO-dark pair. Each has its own required attribution text (they
// differ -- Esri's and OpenTopoMap's licenses require different credit
// lines than OSM/CARTO's), shown via the source's own `attribution`
// field, which MapLibre's AttributionControl picks up automatically from
// whichever raster source is actually part of the map at the time --
// see the basemap-switching effect below for why the source is fully
// replaced (not just re-pointed via setTiles) when the style changes,
// specifically so that attribution swap actually happens.
const BASEMAPS = {
  street: {
    label: 'Street',
    tiles: [
      'https://a.tile.openstreetmap.org/{z}/{x}/{y}.png',
      'https://b.tile.openstreetmap.org/{z}/{x}/{y}.png',
      'https://c.tile.openstreetmap.org/{z}/{x}/{y}.png',
    ],
    attribution: '© OpenStreetMap contributors',
  },
  light: {
    label: 'Light',
    tiles: [
      'https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png',
      'https://b.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png',
      'https://c.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png',
      'https://d.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png',
    ],
    attribution: '© OpenStreetMap contributors © CARTO',
  },
  dark: {
    label: 'Dark',
    tiles: [
      'https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
      'https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
      'https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
      'https://d.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
    ],
    attribution: '© OpenStreetMap contributors © CARTO',
  },
  satellite: {
    label: 'Satellite',
    // Esri's own tile path order is z/row/col (i.e. {z}/{y}/{x} in
    // MapLibre's placeholder convention, not the usual {z}/{x}/{y}) --
    // verified live; using the standard order 404s.
    tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
    attribution: 'Esri, Maxar, Earthstar Geographics, and the GIS User Community',
  },
  topo: {
    label: 'Topographic',
    tiles: [
      'https://a.tile.opentopomap.org/{z}/{x}/{y}.png',
      'https://b.tile.opentopomap.org/{z}/{x}/{y}.png',
      'https://c.tile.opentopomap.org/{z}/{x}/{y}.png',
    ],
    attribution: 'Map data: © OpenStreetMap contributors, SRTM | Map style: © OpenTopoMap (CC-BY-SA)',
  },
}
const BASEMAP_SOURCE = 'basemap'
const BASEMAP_LAYER = 'basemap'

function basemapMapStyle(styleKey) {
  const basemap = BASEMAPS[styleKey]
  return {
    version: 8,
    sources: {
      [BASEMAP_SOURCE]: { type: 'raster', tiles: basemap.tiles, tileSize: 256, attribution: basemap.attribution },
    },
    layers: [{ id: BASEMAP_LAYER, type: 'raster', source: BASEMAP_SOURCE }],
  }
}

// A plain MapLibre IControl (framework-agnostic DOM, per MapLibre's own
// control API -- there's no React-component control type), not a React
// component: it's added once in the map-init effect below, same as the
// native NavigationControl beside it, and drives state purely one-way
// (dispatching actions) since nothing else in the app can change
// basemapStyle/basemapVisible for it to need to sync back FROM.
class BasemapControl {
  constructor(dispatch, getState) {
    this._dispatch = dispatch
    this._getState = getState
  }

  onAdd() {
    const container = document.createElement('div')
    container.className = 'maplibregl-ctrl maplibregl-ctrl-group basemap-control'

    const select = document.createElement('select')
    select.className = 'basemap-control__select'
    for (const [key, basemap] of Object.entries(BASEMAPS)) {
      const option = document.createElement('option')
      option.value = key
      option.textContent = basemap.label
      select.appendChild(option)
    }
    select.value = this._getState().basemapStyle
    select.addEventListener('change', () => this._dispatch({ type: 'SET_BASEMAP_STYLE', style: select.value }))

    const toggleButton = document.createElement('button')
    toggleButton.type = 'button'
    toggleButton.className = 'basemap-control__toggle'
    toggleButton.title = 'Show/hide basemap'
    const syncToggleLabel = () => {
      toggleButton.textContent = this._getState().basemapVisible ? '🗺️' : '⬜'
    }
    syncToggleLabel()
    toggleButton.addEventListener('click', () => {
      this._dispatch({ type: 'TOGGLE_BASEMAP_VISIBLE' })
      // No state to read synchronously right after dispatch (React
      // state updates aren't immediate) -- flip the label optimistically
      // to match what the dispatch is about to produce.
      toggleButton.textContent = toggleButton.textContent === '🗺️' ? '⬜' : '🗺️'
    })

    container.appendChild(select)
    container.appendChild(toggleButton)
    this._container = container
    return container
  }

  onRemove() {
    this._container?.parentNode?.removeChild(this._container)
  }
}

// A small live lng/lat/zoom readout, bottom-left next to MapLibre's own
// ScaleControl -- the kind of chrome a serious cartography tool (Mapbox
// Studio, QGIS) shows as a matter of course, and this app had none of
// before. Purely a readout (no interaction, nothing to dispatch) so it's
// a plain IControl that just re-renders its own text node on 'move' --
// no need to route through React state for something this cheap and
// map-internal.
class CoordinateReadoutControl {
  onAdd(map) {
    this._map = map
    const container = document.createElement('div')
    container.className = 'maplibregl-ctrl coord-readout'
    this._container = container
    this._update = () => {
      const c = map.getCenter()
      const lat = c.lat.toFixed(4)
      const lng = c.lng.toFixed(4)
      const zoom = map.getZoom().toFixed(2)
      container.textContent = `${lat}, ${lng}  ·  z${zoom}`
    }
    map.on('move', this._update)
    this._update()
    return container
  }

  onRemove() {
    this._map.off('move', this._update)
    this._container?.parentNode?.removeChild(this._container)
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
      style: basemapMapStyle(stateRef.current.basemapStyle),
      center: KATHMANDU_CENTER,
      zoom: DEFAULT_ZOOM,
    })
    mapRef.current = map
    map.addControl(new maplibregl.NavigationControl(), 'top-right')
    map.addControl(new BasemapControl(dispatch, () => stateRef.current), 'top-left')
    // Cartographic-instrument chrome Mapbox Studio/QGIS treat as table
    // stakes and this app previously had none of: a real scale bar
    // (MapLibre's own control, zero new deps) and a live coordinate/zoom
    // readout, both bottom-left so they read together as one status strip.
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: 'metric' }), 'bottom-left')
    map.addControl(new CoordinateReadoutControl(), 'bottom-left')

    // Cursor feedback: 'grab' when idle in pan mode, 'grabbing' while
    // dragging the map, 'crosshair' in draw mode (set by the aoiMode
    // effect). dragstart/dragend only fire when dragPan is enabled, i.e.
    // never in draw mode, so no need to re-check the mode here.
    map.getCanvas().style.cursor = stateRef.current.aoiMode === 'draw' ? 'crosshair' : 'grab'
    map.on('dragstart', () => {
      map.getCanvas().style.cursor = 'grabbing'
    })
    map.on('dragend', () => {
      map.getCanvas().style.cursor = stateRef.current.aoiMode === 'draw' ? 'crosshair' : 'grab'
    })

    // --- Right-mouse-button drag pans the map. Works in every mode,
    // including 'draw' (where the LEFT button is reserved for drawing the
    // AOI rectangle) -- so the map can always be repositioned with the
    // right button. MapLibre's default right-drag (rotate/pitch) is
    // disabled so it doesn't fight this; the browser context menu is
    // suppressed over the map so a right-drag isn't interrupted. ---
    map.dragRotate.disable()
    const canvasContainer = map.getCanvasContainer()
    let rightPanLast = null
    const onContextMenu = (e) => e.preventDefault()
    const onRightDown = (e) => {
      if (e.button !== 2) return
      rightPanLast = [e.clientX, e.clientY]
      map.getCanvas().style.cursor = 'grabbing'
      e.preventDefault()
    }
    const onRightMove = (e) => {
      if (!rightPanLast) return
      const dx = e.clientX - rightPanLast[0]
      const dy = e.clientY - rightPanLast[1]
      rightPanLast = [e.clientX, e.clientY]
      // Move the view opposite the cursor delta -- same feel as grabbing
      // the map and dragging it. duration:0 keeps it 1:1 with the mouse.
      map.panBy([-dx, -dy], { duration: 0 })
    }
    const onRightUp = (e) => {
      if (e.button !== 2 || !rightPanLast) return
      rightPanLast = null
      map.getCanvas().style.cursor = stateRef.current.aoiMode === 'draw' ? 'crosshair' : 'grab'
    }
    canvasContainer.addEventListener('contextmenu', onContextMenu)
    canvasContainer.addEventListener('mousedown', onRightDown)
    window.addEventListener('mousemove', onRightMove)
    window.addEventListener('mouseup', onRightUp)

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
      canvasContainer.removeEventListener('contextmenu', onContextMenu)
      canvasContainer.removeEventListener('mousedown', onRightDown)
      window.removeEventListener('mousemove', onRightMove)
      window.removeEventListener('mouseup', onRightUp)
      map.remove()
      mapRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- init once; handlers read stateRef for live state
  }, [])

  // --- basemap style: fully remove + re-add the source/layer, not just
  // re-point the same source's tiles -- MapLibre's AttributionControl
  // tracks attribution per the sources actually present on the map, so
  // switching providers (each with its own required credit line) needs
  // a real source swap, not a setTiles() on a source whose `attribution`
  // metadata would otherwise stay pinned to whichever provider was first
  // loaded. ---
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const apply = () => {
      if (map.getLayer(BASEMAP_LAYER)) map.removeLayer(BASEMAP_LAYER)
      if (map.getSource(BASEMAP_SOURCE)) map.removeSource(BASEMAP_SOURCE)
      const basemap = BASEMAPS[state.basemapStyle]
      map.addSource(BASEMAP_SOURCE, {
        type: 'raster', tiles: basemap.tiles, tileSize: 256, attribution: basemap.attribution,
      })
      // Re-inserted as the bottom-most layer (before the first existing
      // layer, if any) so it never ends up drawn on top of the AOI/
      // basins/risk-surface layers that were added after the map's
      // initial load.
      const firstLayerId = map.getStyle().layers.find((l) => l.id !== BASEMAP_LAYER)?.id
      map.addLayer({ id: BASEMAP_LAYER, type: 'raster', source: BASEMAP_SOURCE }, firstLayerId)
      map.setLayoutProperty(BASEMAP_LAYER, 'visibility', state.basemapVisible ? 'visible' : 'none')
    }
    if (map.isStyleLoaded()) apply()
    else map.once('load', apply)
  }, [state.basemapStyle])

  // --- basemap visibility toggle -- a separate, cheap layout-property
  // flip, no source/layer churn (unlike the style-switch effect above). ---
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const apply = () => map.setLayoutProperty(BASEMAP_LAYER, 'visibility', state.basemapVisible ? 'visible' : 'none')
    if (map.isStyleLoaded() && map.getLayer(BASEMAP_LAYER)) apply()
    else map.once('load', apply)
  }, [state.basemapVisible])

  // --- draw mode: disable/enable normal map dragging so drag = draw, not pan ---
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    // The cursor is a plain DOM style on the canvas (which exists as soon
    // as the map does), so set it unconditionally — NOT inside the
    // isStyleLoaded()-guarded apply() below. isStyleLoaded() returns false
    // whenever raster basemap tiles are mid-load, so a guarded set would
    // often defer to a 'load' event that already fired and never run,
    // leaving the cursor stuck. '+' crosshair while selecting an area;
    // open-hand 'grab' while panning ('grabbing' during a drag comes from
    // the dragstart/dragend handlers in the init effect).
    map.getCanvas().style.cursor = state.aoiMode === 'draw' ? 'crosshair' : 'grab'
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
          map.getCanvas().style.cursor = stateRef.current.aoiMode === 'draw' ? 'crosshair' : 'grab'
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
    // Left button only: the right button is reserved for panning the map
    // (see the right-drag handler in the init effect), so it must never
    // start drawing an AOI rectangle.
    if (e.originalEvent.button !== 0) return
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
