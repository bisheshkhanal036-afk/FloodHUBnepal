// The map: basemap, draw-rectangle AOI interaction, basin polygon layer
// (color-coded by support_status, clickable), district polygon layer
// (flat-colored, clickable), and the computed risk surface rendered as a
// colorized raster overlay. All MapLibre-specific code lives here, kept
// separate from the panels so a future phase (shelter markers,
// vulnerability classes) can add its own layers here without touching
// the state/panel logic.
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useRef } from 'react'
import {
  API_BASE_URL,
  fetchRiskSurfaceBytes,
  getBasinAOI,
  getDistrictAOI,
  getValidationExtentGeoJSON,
  listValidationEvents,
} from '../api/client'
import { riskValueToRgb, riskValueToCssColor, SUPPORT_STATUS_COLORS, DISTRICT_FILL_COLOR } from '../lib/colorRamp'
import { AREA_CAP_KM2, approxBboxAreaKm2, bboxToPolygon, cornersToBbox, polygonCentroid } from '../lib/geo'
import { gridCornersToWgs84 } from '../lib/proj'
import { decodeGeoTiffToDataUrl } from '../lib/rasterPreview'
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
    // Was CARTO's basemaps.cartocdn.com/light_all -- CARTO discontinued
    // free/anonymous access to that endpoint (it now returns a 200 OK
    // "API KEY REQUIRED" watermark image instead of real tiles, verified
    // live -- not a network/config issue on this app's side). Esri's
    // Canvas World_Light_Gray_Base is the same style of muted gray
    // basemap, free, no key required (verified live: real street-level
    // tiles over Kathmandu, not a placeholder).
    tiles: [
      'https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}',
    ],
    attribution: 'Esri, HERE, Garmin, FAO, NOAA, USGS',
  },
  dark: {
    label: 'Dark',
    // Same CARTO deprecation as 'light' above -- swapped to Esri's
    // Canvas World_Dark_Gray_Base for the same reason.
    tiles: [
      'https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
    ],
    attribution: 'Esri, HERE, Garmin, FAO, NOAA, USGS',
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

// METEOR Project's live Nepal flood hazard map, as an optional reference
// overlay -- NOT the same thing as the flood_hazard_meteor *criterion*
// (backend/app/overlay/sources.py), which reads the same organization's
// downloadable numeric GeoTIFFs instead. This overlay talks directly to
// METEOR's own public WMTS tile service (pre-styled RGB PNG, verified
// live during implementation: a real tile fetch at z=12/x=3018/y=1719
// returned a genuine flood-extent image tracing real river geometry
// near Kathmandu) -- fine for a visual reference layer, but not usable
// as numeric criterion input, which is exactly why the criterion source
// reads METEOR's separate downloadable GeoTIFF package instead (see
// backend/app/data/meteor_flood.py's module docstring).
//
// License verified directly against the flood map's own page HTML
// during implementation (not a summarized secondhand read, at explicit
// request to be completely sure): ODbL (Open Data Commons Open Database
// License) -- the same license OpenStreetMap itself uses, NOT the
// CC BY-NC-SA 4.0 that covers METEOR's separate Exposure Data product
// (an easy conflation this project's own first-pass research initially
// fell into, then corrected against the raw page source).
//
// Layer id convention verified live via WMTS GetCapabilities: 3 flood
// types x 10 return periods = 30 layers, named "{type}-{years}" (e.g.
// "fd-100"). Fixed to Fluvial (Defended), 1-in-100y -- not user-
// selectable -- at explicit request: this is the one combination that
// matches backend/app/data/config.py's own METEOR_FLOOD_TYPE/
// METEOR_FLOOD_RETURN_PERIOD defaults for the criterion (the only
// combination the criterion has local raw data for at all), so the map's
// own reference overlay always shows the same METEOR flavor the
// criterion itself would use, rather than letting the two silently
// diverge across 30 possible combinations.
const METEOR_FLOOD_TYPE = 'fd'
const METEOR_FLOOD_TYPE_LABEL = 'Fluvial (Defended)'
const METEOR_FLOOD_RETURN_PERIOD = 100
const METEOR_FLOOD_ATTRIBUTION =
  'METEOR Project flood hazard maps (Fathom global flood hazard framework) — Open Data Commons Open Database License (ODbL)'

function meteorFloodTiles(floodType, returnPeriod) {
  // Routed through this app's OWN backend (app/overlay/
  // meteor_tile_proxy.py), not fetched directly from
  // maps.meteor-project.org -- a second real bug caught live during
  // implementation, after fixing the layer-id bug below still didn't
  // make tiles appear: METEOR's tile server sends no
  // Access-Control-Allow-Origin header at all (confirmed live via `curl
  // -I`), and MapLibre GL sets `crossOrigin` on its raster tile
  // requests (it needs the actual pixel bytes for a WebGL texture,
  // unlike this file's own MeteorFloodLegend image, which is a plain
  // `<img src>` with no crossOrigin and was never affected) -- so every
  // tile request failed as a browser-enforced CORS error, confirmed via
  // a headless-Chrome CDP session showing "TypeError: Failed to fetch"
  // from inside maplibre-gl's own tile-loading code even though the
  // exact same URL succeeded via a server-side curl. Browsers don't
  // enforce CORS on server-to-server requests, so the backend fetches
  // the real tile itself and hands the bytes back from an origin this
  // frontend already trusts (see meteor_tile_proxy.py's own docstring).
  //
  // The proxy's own path still encodes "{type}-1in{years}" (e.g.
  // "fd-1in100"), the layer-id convention confirmed against the live
  // WMTS GetCapabilities document's `ows:Identifier` entries -- the
  // first bug caught here, separate from the CORS one above ("fd-100"
  // 400s upstream, "fd-1in100" 200s).
  return [`${API_BASE_URL}/api/overlay/meteor_flood_tile/${floodType}/${returnPeriod}/{z}/{x}/{y}.png`]
}

const METEOR_FLOOD_SOURCE = 'meteor-flood'
const METEOR_FLOOD_LAYER = 'meteor-flood'

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

// Same shape as BasemapControl above (a toggle button, plain DOM, one-
// way dispatch), for the METEOR flood hazard reference overlay -- see
// this file's METEOR_FLOOD_TYPE/meteorFloodTiles comment for what the
// overlay itself is and why it's a separate thing from the
// flood_hazard_meteor criterion.
// Always visible, regardless of whether "Flood Hazard (METEOR)" is
// checked as a criterion -- at explicit request: this is a reference
// overlay useful to look at on its own, not gated on whatever's
// currently selected as input. No type/return-period picker -- fixed to
// METEOR_FLOOD_TYPE/METEOR_FLOOD_RETURN_PERIOD above, a plain toggle for
// that one specific overlay.
class MeteorFloodControl {
  constructor(dispatch, getState) {
    this._dispatch = dispatch
    this._getState = getState
  }

  onAdd() {
    const container = document.createElement('div')
    container.className = 'maplibregl-ctrl maplibregl-ctrl-group basemap-control meteor-flood-control'

    // A visible label, not just a hover title -- with the type/return-
    // period dropdowns gone (fixed now, see this class's own docstring
    // above), the control had shrunk to a single icon-only button with
    // no on-screen text at all, unlike every other control in this
    // group (BasemapControl/ValidationExtentControl both show their own
    // current selection as real visible text, not just a tooltip).
    const label = document.createElement('span')
    label.className = 'basemap-control__label'
    label.textContent = `${METEOR_FLOOD_TYPE_LABEL}, 1-in-${METEOR_FLOOD_RETURN_PERIOD}y`

    const toggleButton = document.createElement('button')
    toggleButton.type = 'button'
    toggleButton.className = 'basemap-control__toggle'
    toggleButton.title = `Show/hide METEOR flood hazard reference overlay (${METEOR_FLOOD_TYPE_LABEL}, 1-in-${METEOR_FLOOD_RETURN_PERIOD}y)`
    const syncToggleLabel = () => {
      toggleButton.textContent = this._getState().meteorFloodVisible ? '🌊' : '〰️'
    }
    syncToggleLabel()
    toggleButton.addEventListener('click', () => {
      this._dispatch({ type: 'TOGGLE_METEOR_FLOOD_VISIBLE' })
      // Same optimistic-flip reasoning as BasemapControl's own toggle
      // button above -- no state to read synchronously right after
      // dispatch.
      toggleButton.textContent = toggleButton.textContent === '🌊' ? '〰️' : '🌊'
    })

    container.appendChild(label)
    container.appendChild(toggleButton)
    this._container = container
    return container
  }

  onRemove() {
    this._container?.parentNode?.removeChild(this._container)
  }
}

// Same top-left control-group slot as MeteorFloodControl, for the same
// kind of reason: a real, satellite-observed flood extent
// (app/data/validation_extent.py) shown as a toggleable map reference
// overlay, the visual counterpart to ValidationPanel's own AUC number
// (sidebar step 6) -- "the validation events should be able to be
// overlaid, in the same place as the meteor flood overlay," at explicit
// request. Unlike METEOR_FLOOD_TYPE/METEOR_FLOOD_RETURN_PERIOD (fixed
// constants known at import time), the event list is fetched from the backend
// asynchronously and can still be empty the moment this control is
// constructed -- `updateEvents()` lets the owning MapView component
// repopulate the select once GET /api/overlay/validation-events
// actually resolves, called from its own effect keyed on
// state.validationEvents.list (see the exposed `_instance` field below
// used to reach this control instance from outside the class).
class ValidationExtentControl {
  constructor(dispatch, getState) {
    this._dispatch = dispatch
    this._getState = getState
  }

  onAdd() {
    const container = document.createElement('div')
    container.className = 'maplibregl-ctrl maplibregl-ctrl-group basemap-control meteor-flood-control'

    const eventSelect = document.createElement('select')
    eventSelect.className = 'basemap-control__select'
    eventSelect.title = 'Real observed flood event to overlay'
    eventSelect.addEventListener('change', () => {
      this._dispatch({ type: 'SET_VALIDATION_EVENT', event: eventSelect.value })
    })
    this._eventSelect = eventSelect

    const toggleButton = document.createElement('button')
    toggleButton.type = 'button'
    toggleButton.className = 'basemap-control__toggle'
    toggleButton.title = 'Show/hide real observed flood extent overlay'
    const syncToggleLabel = () => {
      toggleButton.textContent = this._getState().validationExtentVisible ? '🛰️' : '〰️'
    }
    syncToggleLabel()
    toggleButton.addEventListener('click', () => {
      this._dispatch({ type: 'TOGGLE_VALIDATION_EXTENT_VISIBLE' })
      // Same optimistic-flip reasoning as every other toggle button in
      // this file -- no state to read synchronously right after dispatch.
      toggleButton.textContent = toggleButton.textContent === '🛰️' ? '〰️' : '🛰️'
    })

    container.appendChild(eventSelect)
    container.appendChild(toggleButton)
    this._container = container
    this.updateEvents(this._getState().validationEvents.list, this._getState().selectedValidationEvent)
    return container
  }

  /** Rebuilds the <select>'s own options from the current events list -- called once up front (possibly with an empty list, if GET /api/overlay/validation-events hasn't resolved yet) and again by MapView's own effect whenever state.validationEvents.list actually changes. */
  updateEvents(events, selectedEvent) {
    if (!this._eventSelect) return
    this._eventSelect.replaceChildren()
    for (const { key, label } of events) {
      const option = document.createElement('option')
      option.value = key
      option.textContent = label
      this._eventSelect.appendChild(option)
    }
    if (selectedEvent) this._eventSelect.value = selectedEvent
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
const DISTRICTS_SOURCE = 'districts'
const RISK_SURFACE_SOURCE = 'risk-surface'
const BUILDINGS_SOURCE = 'buildings'
const BUILDINGS_LAYER = 'buildings-fill'
// Individual footprints are only legible once zoomed in enough to tell
// them apart -- at a city-wide view, tens of thousands of them (87,402
// in one already-verified real test case) is visual noise, not
// information, on top of which the hazard-class raster/zonal table
// already cover the zoomed-out picture. ~13 is roughly "individual
// buildings distinguishable" for this basemap set.
const BUILDINGS_MIN_ZOOM = 13
const SHELTERS_SOURCE = 'shelter-candidates'
const SHELTERS_FILL_LAYER = 'shelter-candidates-fill'
const SHELTERS_LABEL_LAYER = 'shelter-candidates-label'
// A gold/amber fill -- deliberately distinct from riskValueToRgb's own
// green-yellow-red hazard ramp (used by BUILDINGS_FILL_COLOR below and
// the risk-surface raster itself), so a shelter candidate reads as its
// own category of thing, never mistaken for one more hazard-class swatch.
const SHELTERS_FILL_COLOR = '#f5b301'
// A separate point source/layer, one feature per candidate at its own
// footprint's approximate centroid (lib/geo.js's polygonCentroid) --
// SHELTERS_FILL_LAYER alone (a real building's own small footprint
// polygon) can be genuinely hard to spot at anything but a close zoom,
// especially against a busy basemap; this animated "highlight" halo
// underneath it is what actually draws the eye to each candidate
// regardless of zoom level, the literal ask behind "make the shelters
// highlighted." Radius/opacity are animated by a small requestAnimationFrame
// loop (SHELTERS_HIGHLIGHT_ANIMATION_MS below) -- MapLibre's own paint
// properties have no CSS-keyframe equivalent for a canvas-rendered
// layer, so this is the one other place in this file (alongside
// useHeroScrollScale.js's own documented exception on the landing page)
// that ticks a paint property directly rather than relying on a CSS
// transition/animation.
const SHELTERS_HIGHLIGHT_SOURCE = 'shelter-candidates-highlight'
const SHELTERS_HIGHLIGHT_LAYER = 'shelter-candidates-highlight-pulse'
const SHELTERS_HIGHLIGHT_ANIMATION_MS = 1800
// Always the 'risk' scheme's own 5 class colors (matching classColor
// below), same as every other hazard-class swatch in this app
// (ReportOverlay's zonal table/chart, CriterionSnapshot) -- deliberately
// NOT tied to state.riskColorScheme, which only ever re-colors the
// continuous risk-surface raster + its own legend, per that state
// field's own established scope.
function classColor(hazardClass) {
  return riskValueToCssColor((hazardClass - 1) / 4)
}
const BUILDINGS_FILL_COLOR = [
  'match',
  ['coalesce', ['get', 'hazard_class'], 0],
  1, classColor(1),
  2, classColor(2),
  3, classColor(3),
  4, classColor(4),
  5, classColor(5),
  'rgba(140, 140, 140, 0.35)', // hazard_class null -- outside the AOI/grid, not a 6th real class
]
const VALIDATION_EXTENT_SOURCE = 'validation-extent'
const VALIDATION_EXTENT_LAYER = 'validation-extent'
// A real, live-caught bug: nepal_bipad_flood_points (backend/app/data/
// config.py) is a POINT inventory, not a polygon extent like
// nepal_2024_terai -- a 'fill' layer renders literally nothing for
// Point/MultiPoint geometries in MapLibre (fill only applies to
// polygons), so that event's own toggle silently did nothing visible on
// the map. Fixed with a SECOND layer on the same source, 'circle' type.
//
// A second real, live-reported bug, caught after the fix above shipped:
// unlike 'fill' (genuinely restricted to Polygon/MultiPolygon) and
// 'line', MapLibre's 'circle' layer type is NOT restricted to Point/
// MultiPoint -- it draws a circle at every VERTEX of whatever geometry
// is in the source, including every ring vertex of a Polygon/
// MultiPolygon. The original comment here assumed a circle layer was "a
// safe no-op over polygon geometries the exact same way fill is a no-op
// over points" -- that assumption was wrong, and every polygon-type
// event (nepal_2024_terai, nepal_2024_west_eosrs, nepal_2024_west_mbrsc,
// rasuwa_2026, the EMSR927 events, ...) was rendering a magenta
// point-marker circle at every one of its polygon's own vertices.
// Fixed with an explicit `filter` on each layer keyed on MapLibre's
// `geometry-type` expression (returns 'Point'/'LineString'/'Polygon'
// only -- geojson-vt flattens Multi* geometries into repeated single-
// part features before tiling, so there's no separate 'MultiPolygon'/
// 'MultiPoint' value to match), so each layer only ever draws its own
// intended geometry type regardless of what else the shared source
// holds -- correct now for the actual reason both layers can safely
// coexist on one source, not the previous (incorrect) reasoning.
const VALIDATION_EXTENT_POINTS_LAYER = 'validation-extent-points'

export default function MapView() {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const stateRef = useRef(null)
  // The ValidationExtentControl instance itself (not just its container
  // div) -- kept so the event-list-sync effect below can call its own
  // updateEvents() method directly, the same reason a plain IControl
  // (no React lifecycle of its own) needs an escape hatch to be updated
  // from outside after construction.
  const validationExtentControlRef = useRef(null)
  // The shelter-candidates highlight's own requestAnimationFrame handle
  // (SHELTERS_HIGHLIGHT_LAYER below) -- stopped and restarted whenever
  // the candidate set changes, and always cancelled on unmount, so it
  // can never keep ticking a paint property on a layer that no longer
  // exists.
  const shelterHighlightAnimRef = useRef(null)
  // Caches the risk-surface GeoTIFF's raw bytes, keyed by data_url --
  // switching color schemes (state.riskColorScheme) needs to re-decode
  // with a different colorFn, but not re-fetch bytes that haven't
  // changed; only a genuinely new compute result (a new data_url)
  // re-fetches.
  const riskBytesRef = useRef({ url: null, bytes: null })
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
    map.addControl(new MeteorFloodControl(dispatch, () => stateRef.current), 'top-left')
    const validationExtentControl = new ValidationExtentControl(dispatch, () => stateRef.current)
    validationExtentControlRef.current = validationExtentControl
    map.addControl(validationExtentControl, 'top-left')
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

  // --- METEOR flood hazard reference overlay: source/layer created once
  // on mount, fixed to METEOR_FLOOD_TYPE/METEOR_FLOOD_RETURN_PERIOD
  // (no longer user-selectable, so nothing left that would need this to
  // re-run and swap the source/layer later). ---
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const apply = () => {
      if (map.getLayer(METEOR_FLOOD_LAYER)) map.removeLayer(METEOR_FLOOD_LAYER)
      if (map.getSource(METEOR_FLOOD_SOURCE)) map.removeSource(METEOR_FLOOD_SOURCE)
      map.addSource(METEOR_FLOOD_SOURCE, {
        type: 'raster',
        tiles: meteorFloodTiles(METEOR_FLOOD_TYPE, METEOR_FLOOD_RETURN_PERIOD),
        tileSize: 256,
        attribution: METEOR_FLOOD_ATTRIBUTION,
      })
      // Drawn above the basemap but below AOI/basins/risk-surface layers
      // added later, mirroring the basemap layer's own bottom-insertion
      // reasoning -- a reference overlay should sit under the app's own
      // interactive layers, not on top of them.
      const firstLayerId = map.getStyle().layers.find((l) => l.id !== BASEMAP_LAYER)?.id
      map.addLayer({ id: METEOR_FLOOD_LAYER, type: 'raster', source: METEOR_FLOOD_SOURCE, paint: { 'raster-opacity': 0.7 } }, firstLayerId)
      // stateRef, not the closure's own `state` -- this effect now only
      // ever runs once (empty deps below), so `state` here would freeze
      // at whatever meteorFloodVisible was on the very first render.
      map.setLayoutProperty(METEOR_FLOOD_LAYER, 'visibility', stateRef.current.meteorFloodVisible ? 'visible' : 'none')
    }
    if (map.isStyleLoaded()) apply()
    else map.once('load', apply)
  }, [])

  // --- METEOR flood hazard overlay visibility toggle -- cheap layout-
  // property flip, same shape as the basemap visibility effect above. ---
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const apply = () => map.setLayoutProperty(METEOR_FLOOD_LAYER, 'visibility', state.meteorFloodVisible ? 'visible' : 'none')
    if (map.isStyleLoaded() && map.getLayer(METEOR_FLOOD_LAYER)) apply()
    else map.once('load', apply)
  }, [state.meteorFloodVisible])

  // --- real observed flood-extent overlay: fetch the events list once,
  // independent of whether the sidebar's own "Validate" step has ever
  // been reached (StepSection doesn't mount a locked step's content, so
  // ValidationPanel's own identical fetch-trigger effect wouldn't run
  // until a risk surface is already computed -- this overlay control, by
  // design, works standalone, the same way MeteorFloodControl doesn't
  // wait on any other step either). Both effects share the same
  // idle-status guard, so whichever mounts first "wins" and the other is
  // a safe no-op, never a duplicate fetch. ---
  useEffect(() => {
    if (stateRef.current.validationEvents.status !== 'idle') return
    dispatch({ type: 'VALIDATION_EVENTS_LOADING' })
    listValidationEvents()
      .then((events) => dispatch({ type: 'VALIDATION_EVENTS_LOADED', events }))
      .catch((error) => dispatch({ type: 'VALIDATION_EVENTS_ERROR', error }))
    // Runs once on mount only (stateRef.current read fresh above, not a
    // dependency) -- re-fetching every time some unrelated bit of state
    // changes would be wasteful for a list that's static per session.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Keeps ValidationExtentControl's own <select> in sync with the
  // fetched events list/current selection -- a plain IControl has no
  // React re-render of its own, so this is the same "push updates in via
  // an escape-hatch method" pattern CoordinateReadoutControl's map
  // event listener already uses, just driven by React state instead of
  // a MapLibre event.
  useEffect(() => {
    validationExtentControlRef.current?.updateEvents(state.validationEvents.list, state.selectedValidationEvent)
  }, [state.validationEvents.list, state.selectedValidationEvent])

  // Real flood-extent GeoJSON: (re)fetched whenever the selected event
  // changes, added as a fill layer the same way basins/districts already
  // are. A distinct magenta from every other layer on this map (basins'
  // gray outline, districts' own fill, the risk surface's own ramp, and
  // METEOR's raster) so it never reads as any of those by accident.
  useEffect(() => {
    const map = mapRef.current
    const event = state.selectedValidationEvent
    if (!map || !event) return

    let cancelled = false
    getValidationExtentGeoJSON(event)
      .then((geojson) => {
        if (cancelled) return
        const apply = () => {
          if (map.getSource(VALIDATION_EXTENT_SOURCE)) {
            map.getSource(VALIDATION_EXTENT_SOURCE).setData(geojson)
          } else {
            map.addSource(VALIDATION_EXTENT_SOURCE, { type: 'geojson', data: geojson })
            const firstLayerId = map.getStyle().layers.find((l) => l.id !== BASEMAP_LAYER)?.id
            // stateRef, not the closure's own `state`, for both layers'
            // own initial visibility below -- this async fetch can
            // resolve well after the render that started it, so a
            // toggle click in between must still be reflected rather
            // than reverting to whatever it was when the fetch began.
            const initialVisibility = stateRef.current.validationExtentVisible ? 'visible' : 'none'
            map.addLayer(
              {
                id: VALIDATION_EXTENT_LAYER,
                type: 'fill',
                source: VALIDATION_EXTENT_SOURCE,
                // MapLibre's `geometry-type` expression only ever returns
                // 'Point'/'LineString'/'Polygon' -- GeoJSON sources are
                // tiled via geojson-vt, which flattens Multi* geometries
                // into repeated single-part features before this
                // expression ever sees them, so there's no 'MultiPolygon'/
                // 'MultiPoint' value to also match here.
                filter: ['==', ['geometry-type'], 'Polygon'],
                paint: { 'fill-color': '#e930c8', 'fill-opacity': 0.55 },
                layout: { visibility: initialVisibility },
              },
              firstLayerId
            )
            // Sized deliberately large (not MapLibre's own default ~5px)
            // and given a white stroke for contrast against whatever
            // basemap color happens to sit underneath -- a real, live-
            // reported problem: at the default size the BIPAD point
            // inventory's own markers were easy to miss entirely,
            // especially at a zoomed-out view where a full AOI's worth
            // of points are sparse.
            map.addLayer(
              {
                id: VALIDATION_EXTENT_POINTS_LAYER,
                type: 'circle',
                source: VALIDATION_EXTENT_SOURCE,
                filter: ['==', ['geometry-type'], 'Point'],
                paint: {
                  'circle-radius': 7,
                  'circle-color': '#e930c8',
                  'circle-opacity': 0.9,
                  'circle-stroke-width': 1.5,
                  'circle-stroke-color': '#ffffff',
                },
                layout: { visibility: initialVisibility },
              },
              firstLayerId
            )
          }
        }
        if (map.isStyleLoaded()) apply()
        else map.once('load', apply)
      })
      .catch(() => {
        // A failed fetch (e.g. the event's own local file missing
        // server-side) just leaves no overlay to show -- ValidationPanel
        // surfaces the equivalent failure for POST /validate itself
        // already; this reference layer degrading silently, rather than
        // erroring the whole map, matches how a missing basemap tile
        // doesn't crash the app either.
      })

    return () => {
      cancelled = true
    }
  }, [state.selectedValidationEvent])

  // --- real observed flood-extent overlay visibility toggle -- cheap
  // layout-property flip, but WITHOUT the `map.once('load', apply)`
  // fallback every other toggle effect above uses: those are all safe
  // to defer to the map's own 'load' event because their layer is
  // created synchronously in a same-tick effect gated on that same
  // event. This layer's own creation (the effect above) is instead
  // gated behind an independent async GeoJSON fetch, so 'load' can fire
  // (and only fires once) well before the layer actually exists --
  // confirmed live during implementation: deferring to it here threw
  // "Cannot style non-existing layer" every time. A missing layer here
  // just means its own creation effect hasn't finished fetching yet, in
  // which case it already bakes today's state.validationExtentVisible
  // into the layer's own initial `layout.visibility` when it's created
  // — nothing for this effect to do until then.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !map.getLayer(VALIDATION_EXTENT_LAYER)) return
    const visibility = state.validationExtentVisible ? 'visible' : 'none'
    map.setLayoutProperty(VALIDATION_EXTENT_LAYER, 'visibility', visibility)
    // Both layers are always created together (the effect above), so
    // the fill layer's own existence check just above already
    // guarantees the points layer exists too.
    map.setLayoutProperty(VALIDATION_EXTENT_POINTS_LAYER, 'visibility', visibility)
  }, [state.validationExtentVisible])

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
        // Initial visibility matches whatever mode is active right now
        // (not always 'basin' -- this effect can run after the user has
        // already switched away, if the style's own 'load' event was
        // still pending when the data arrived). The visibility-sync
        // effect further below keeps it correct on every later mode
        // switch; this is just the correct value at creation time.
        const initialVisibility = stateRef.current.aoiMode === 'basin' ? 'visible' : 'none'
        map.addLayer({
          id: 'basins-fill',
          type: 'fill',
          source: BASINS_SOURCE,
          layout: { visibility: initialVisibility },
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
          layout: { visibility: initialVisibility },
          paint: { 'line-color': '#333333', 'line-width': 0.5 },
        })
        map.addLayer({
          id: 'basins-selected',
          type: 'line',
          source: BASINS_SOURCE,
          layout: { visibility: initialVisibility },
          paint: { 'line-color': '#111827', 'line-width': 3 },
          filter: ['==', ['get', 'hybas_id'], -1],
        })

        map.on('click', 'basins-fill', async (e) => {
          if (stateRef.current.aoiMode !== 'basin') return
          const hybasId = e.features[0].properties.hybas_id
          // The clicked feature's own `level` property (baked into it by
          // the GeoJSON the FeatureCollection was fetched at, per
          // BasinFeatureProperties.level), not stateRef.current.basinLevel
          // -- a level switch resets basins.data to null (SET_BASIN_LEVEL)
          // before a new fetch lands, so by the time this layer's own
          // data could be stale enough to matter, the feature's own level
          // is always the ground truth for what was actually clicked.
          const level = e.features[0].properties.level
          dispatch({ type: 'SET_SELECTED_BASIN_ID', hybasId })
          try {
            const aoi = await getBasinAOI(hybasId, level)
            dispatch({
              type: 'SET_AOI',
              aoi: { bbox: aoi.bbox, polygon: aoi.polygon, source: 'basin', basinId: hybasId, basinLevel: level },
            })
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

  // --- districts layer --- (mirrors the basins layer above, minus the
  // support_status color-coding -- a district has no such concept, see
  // lib/colorRamp.js's DISTRICT_FILL_COLOR comment)
  useEffect(() => {
    const map = mapRef.current
    if (!map || !state.districts.data) return

    const render = () => {
      if (map.getSource(DISTRICTS_SOURCE)) {
        map.getSource(DISTRICTS_SOURCE).setData(state.districts.data)
      } else {
        map.addSource(DISTRICTS_SOURCE, { type: 'geojson', data: state.districts.data })
        // See the matching comment on the basins layer above -- same
        // "correct value at creation time" reasoning.
        const initialVisibility = stateRef.current.aoiMode === 'district' ? 'visible' : 'none'
        map.addLayer({
          id: 'districts-fill',
          type: 'fill',
          source: DISTRICTS_SOURCE,
          layout: { visibility: initialVisibility },
          paint: { 'fill-color': DISTRICT_FILL_COLOR, 'fill-opacity': 0.35 },
        })
        map.addLayer({
          id: 'districts-line',
          type: 'line',
          source: DISTRICTS_SOURCE,
          layout: { visibility: initialVisibility },
          paint: { 'line-color': '#333333', 'line-width': 0.5 },
        })
        map.addLayer({
          id: 'districts-selected',
          type: 'line',
          source: DISTRICTS_SOURCE,
          layout: { visibility: initialVisibility },
          paint: { 'line-color': '#111827', 'line-width': 3 },
          filter: ['==', ['get', 'pcode'], ''],
        })

        map.on('click', 'districts-fill', async (e) => {
          if (stateRef.current.aoiMode !== 'district') return
          const pcode = e.features[0].properties.pcode
          dispatch({ type: 'SET_SELECTED_DISTRICT', pcode })
          try {
            const aoi = await getDistrictAOI(pcode)
            dispatch({
              type: 'SET_AOI',
              aoi: { bbox: aoi.bbox, polygon: aoi.polygon, source: 'district', districtPcode: pcode },
            })
          } catch (error) {
            dispatch({ type: 'SET_AREA_WARNING', message: error.message })
          }
        })
        map.on('mouseenter', 'districts-fill', () => {
          if (stateRef.current.aoiMode === 'district') map.getCanvas().style.cursor = 'pointer'
        })
        map.on('mouseleave', 'districts-fill', () => {
          map.getCanvas().style.cursor = stateRef.current.aoiMode === 'draw' ? 'crosshair' : 'grab'
        })
      }
    }

    if (map.isStyleLoaded()) render()
    else map.once('load', render)
  }, [state.districts.data, dispatch])

  // highlight the selected district
  useEffect(() => {
    const map = mapRef.current
    if (!map || !map.getLayer('districts-selected')) return
    map.setFilter('districts-selected', ['==', ['get', 'pcode'], state.selectedDistrictPcode ?? ''])
  }, [state.selectedDistrictPcode])

  // --- show only the layer set matching the current AOI mode ---
  // Layer creation above happens once, the first time each tab's data
  // arrives, and is otherwise a no-op on every later visit (the
  // `if (map.getSource(...))` branch just calls setData) -- so switching
  // aoiMode alone was never enough to hide a layer that's already been
  // created: a basin selection stayed rendered after switching back to
  // "Draw area", and switching from "Select basin" straight to "Select
  // district" showed both layers overlaid at once. This effect is the
  // single place that reconciles visibility with the active mode,
  // independent of *when* each layer happened to be created; it re-runs
  // on every mode switch, and also whenever basins/districts data first
  // arrives (covering a layer created after the mode had already
  // changed, e.g. a deferred map 'load' -- see the "initial visibility"
  // comments on each addLayer call above).
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    const setVisible = (layerId, visible) => {
      if (!map.getLayer(layerId)) return
      map.setLayoutProperty(layerId, 'visibility', visible ? 'visible' : 'none')
    }

    const basinsVisible = state.aoiMode === 'basin'
    const districtsVisible = state.aoiMode === 'district'
    for (const id of ['basins-fill', 'basins-line', 'basins-selected']) setVisible(id, basinsVisible)
    for (const id of ['districts-fill', 'districts-line', 'districts-selected']) setVisible(id, districtsVisible)
  }, [state.aoiMode, state.basins.data, state.districts.data])

  // --- fit view to the current AOI ---
  useEffect(() => {
    const map = mapRef.current
    if (!map || !state.aoi) return
    const [minLng, minLat, maxLng, maxLat] = state.aoi.bbox
    const fit = () => map.fitBounds([[minLng, minLat], [maxLng, maxLat]], { padding: 60, maxZoom: 14 })
    if (map.isStyleLoaded()) fit()
    else map.once('load', fit)
  }, [state.aoi])

  // --- restore a drawn AOI's own outline on load ---
  // setupDrawInteraction's own mouseup handler is the only other place
  // DRAW_PREVIEW_SOURCE ever gets real data -- it's left populated after
  // a successful drag rather than cleared, which is what makes the
  // drawn rectangle stay visible afterward. That path never runs for an
  // AOI restored from localStorage (AppStateContext's persisted-flow-
  // state feature) on a fresh page load: state.aoi is already set the
  // instant this component mounts, with no drag interaction to have
  // populated the source. Without this, a restored draw-mode AOI would
  // fit the map to the right area (the effect above) but show no visible
  // boundary at all -- confusing next to the sidebar's own "AOI set"
  // summary. Basin/district selections don't need the equivalent here:
  // their own selected-highlight layers (basins-selected/districts-
  // selected) are already driven by state.aoi.basinId/districtPcode
  // directly, not a one-shot interaction result like this source is.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !state.aoi || state.aoi.source !== 'draw') return
    const draw = () => {
      map.getSource(DRAW_PREVIEW_SOURCE)?.setData({
        type: 'FeatureCollection',
        features: [{ type: 'Feature', properties: {}, geometry: bboxToPolygon(state.aoi.bbox) }],
      })
    }
    if (map.isStyleLoaded()) draw()
    else map.once('load', draw)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only needs to run once per mount for a restored AOI; a live draw interaction already keeps this source in sync itself
  }, [])

  // --- risk surface raster overlay ---
  // Re-runs on a new compute result (state.overlay.result) or a changed
  // color scheme (state.riskColorScheme) -- either needs a fresh decode
  // with the current colorFn. Bytes are only re-fetched when data_url
  // itself changes (riskBytesRef), so switching schemes on an
  // already-loaded result just re-colors the same already-downloaded
  // GeoTIFF, not a network round trip.
  useEffect(() => {
    const map = mapRef.current
    const result = state.overlay.result
    if (!map || !result) return

    let cancelled = false

    async function render() {
      let { bytes } = riskBytesRef.current
      if (riskBytesRef.current.url !== result.data_url) {
        bytes = await fetchRiskSurfaceBytes(result.data_url)
        if (cancelled) return
        riskBytesRef.current = { url: result.data_url, bytes }
      }
      // No maxSize -- full-resolution decode, unlike CriterionSnapshot's
      // thumbnails: every pixel needs to be geographically accurate here.
      const { dataUrl } = await decodeGeoTiffToDataUrl(bytes, {
        nodata: result.nodata_value,
        colorFn: (v) => riskValueToRgb(v, state.riskColorScheme),
      })
      if (cancelled) return
      const coordinates = gridCornersToWgs84(result.grid)

      const apply = () => {
        if (map.getLayer('risk-surface-layer')) map.removeLayer('risk-surface-layer')
        if (map.getSource(RISK_SURFACE_SOURCE)) map.removeSource(RISK_SURFACE_SOURCE)
        map.addSource(RISK_SURFACE_SOURCE, { type: 'image', url: dataUrl, coordinates })
        map.addLayer({
          id: 'risk-surface-layer',
          type: 'raster',
          source: RISK_SURFACE_SOURCE,
          layout: { visibility: stateRef.current.riskSurfaceVisible ? 'visible' : 'none' },
          paint: { 'raster-opacity': 0.75 },
        })
      }
      if (map.isStyleLoaded()) apply()
      else map.once('load', apply)
    }

    render()
    return () => {
      cancelled = true
    }
  }, [state.overlay.result, state.riskColorScheme])

  // --- risk surface visibility toggle --- (doesn't need a re-decode,
  // just flips the already-rendered layer's MapLibre visibility)
  useEffect(() => {
    const map = mapRef.current
    if (!map || !map.getLayer('risk-surface-layer')) return
    map.setLayoutProperty('risk-surface-layer', 'visibility', state.riskSurfaceVisible ? 'visible' : 'none')
  }, [state.riskSurfaceVisible])

  // --- classified buildings overlay (state.report.result.buildings) ---
  // Unlike the risk-surface layer above, this data is already in memory
  // -- it's part of the POST /api/overlay/report response ReportOverlay
  // already reads, no separate fetch here. Removes+re-adds the source/
  // layer (not just setData) the same way the risk-surface layer does,
  // since a genuinely new report (different AOI/criteria) can arrive,
  // not just an update to the same one. Rendered above the risk-surface
  // raster (added with no beforeId, same as that layer) so individual
  // footprints stay visible on top of the colored raster rather than
  // being painted under it.
  useEffect(() => {
    const map = mapRef.current
    const buildings = state.report.result?.buildings
    if (!map || !buildings) return

    const apply = () => {
      if (map.getLayer(BUILDINGS_LAYER)) map.removeLayer(BUILDINGS_LAYER)
      if (map.getSource(BUILDINGS_SOURCE)) map.removeSource(BUILDINGS_SOURCE)
      map.addSource(BUILDINGS_SOURCE, { type: 'geojson', data: buildings })
      map.addLayer({
        id: BUILDINGS_LAYER,
        type: 'fill',
        source: BUILDINGS_SOURCE,
        minzoom: BUILDINGS_MIN_ZOOM,
        paint: {
          'fill-color': BUILDINGS_FILL_COLOR,
          'fill-opacity': 0.8,
          'fill-outline-color': 'rgba(0, 0, 0, 0.45)',
        },
        // stateRef, not the closure's own `state.buildingsLayerVisible`
        // -- same reasoning the risk-surface layer's own initial
        // visibility above already follows.
        layout: { visibility: stateRef.current.buildingsLayerVisible ? 'visible' : 'none' },
      })
    }
    if (map.isStyleLoaded()) apply()
    else map.once('load', apply)
  }, [state.report.result])

  // --- classified buildings visibility toggle ---
  useEffect(() => {
    const map = mapRef.current
    if (!map || !map.getLayer(BUILDINGS_LAYER)) return
    map.setLayoutProperty(BUILDINGS_LAYER, 'visibility', state.buildingsLayerVisible ? 'visible' : 'none')
  }, [state.buildingsLayerVisible])

  // --- shelter-site candidates (state.shelters.result.candidates) ---
  // Same remove+re-add shape as the classified-buildings layer above:
  // the response's `candidates` are a flat list of {geometry, ...
  // properties}, not already a GeoJSON FeatureCollection like /report's
  // `buildings` is, so this effect builds one client-side before handing
  // it to MapLibre. Rendered above the buildings layer (added with no
  // beforeId, same as every other overlay layer here) so candidates
  // stay visible even when the classified-buildings layer is also on.
  useEffect(() => {
    const map = mapRef.current
    const candidates = state.shelters.result?.candidates
    if (!map || !candidates) return

    // Shared by both the fill-layer features below AND the highlight-
    // layer features -- a real bug, found live, is exactly what this
    // sharing prevents: the highlight halo's own features originally
    // carried only {rank}, not the rest, so clicking the halo (larger
    // and easier to hit than a real building's own small footprint --
    // the whole point of adding it) showed undefined hazard/distance/
    // score instead of that candidate's real data. One shared function
    // means the two layers' popups can never drift apart like that again.
    const candidateProperties = (c) => ({
      rank: c.rank,
      hazard_label: c.hazard_label,
      suitability_score: c.suitability_score,
      distance_to_road_m: c.distance_to_road_m,
      population_density: c.population_density,
      footprint_area_m2: c.footprint_area_m2,
    })

    const featureCollection = {
      type: 'FeatureCollection',
      features: candidates.map((c) => ({
        type: 'Feature',
        geometry: c.geometry,
        properties: candidateProperties(c),
      })),
    }

    // A separate point FeatureCollection (one centroid per candidate,
    // lib/geo.js's polygonCentroid) for the animated highlight halo --
    // see SHELTERS_HIGHLIGHT_SOURCE's own comment for why this needs a
    // point geometry rather than reusing the fill layer's own polygons.
    const highlightFeatureCollection = {
      type: 'FeatureCollection',
      features: candidates.map((c) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: polygonCentroid(c.geometry) },
        properties: candidateProperties(c),
      })),
    }

    const apply = () => {
      if (shelterHighlightAnimRef.current) cancelAnimationFrame(shelterHighlightAnimRef.current)
      if (map.getLayer(SHELTERS_LABEL_LAYER)) map.removeLayer(SHELTERS_LABEL_LAYER)
      if (map.getLayer(SHELTERS_FILL_LAYER)) map.removeLayer(SHELTERS_FILL_LAYER)
      if (map.getLayer(SHELTERS_HIGHLIGHT_LAYER)) map.removeLayer(SHELTERS_HIGHLIGHT_LAYER)
      if (map.getSource(SHELTERS_SOURCE)) map.removeSource(SHELTERS_SOURCE)
      if (map.getSource(SHELTERS_HIGHLIGHT_SOURCE)) map.removeSource(SHELTERS_HIGHLIGHT_SOURCE)

      map.addSource(SHELTERS_HIGHLIGHT_SOURCE, { type: 'geojson', data: highlightFeatureCollection })
      // Added FIRST (beneath the fill/label layers added below) so the
      // pulsing halo reads as radiating out from behind each building
      // footprint, not painted over top of it.
      map.addLayer({
        id: SHELTERS_HIGHLIGHT_LAYER,
        type: 'circle',
        source: SHELTERS_HIGHLIGHT_SOURCE,
        paint: {
          'circle-color': SHELTERS_FILL_COLOR,
          'circle-radius': 14,
          'circle-opacity': 0.5,
          'circle-blur': 0.6,
        },
        layout: { visibility: stateRef.current.sheltersLayerVisible ? 'visible' : 'none' },
      })

      map.addSource(SHELTERS_SOURCE, { type: 'geojson', data: featureCollection })
      map.addLayer({
        id: SHELTERS_FILL_LAYER,
        type: 'fill',
        source: SHELTERS_SOURCE,
        paint: { 'fill-color': SHELTERS_FILL_COLOR, 'fill-opacity': 0.85, 'fill-outline-color': 'rgba(0, 0, 0, 0.6)' },
        layout: { visibility: stateRef.current.sheltersLayerVisible ? 'visible' : 'none' },
      })
      map.addLayer({
        id: SHELTERS_LABEL_LAYER,
        type: 'symbol',
        source: SHELTERS_SOURCE,
        layout: {
          'text-field': ['concat', '#', ['to-string', ['get', 'rank']]],
          'text-size': 12,
          'text-offset': [0, -1.2],
          visibility: stateRef.current.sheltersLayerVisible ? 'visible' : 'none',
        },
        paint: { 'text-color': '#7a4e00', 'text-halo-color': '#ffffff', 'text-halo-width': 1.5 },
      })

      // Runs regardless of current visibility -- ticking a hidden
      // layer's paint property is cheap, and this avoids a race between
      // this effect and the separate visibility-toggle effect below
      // over exactly when the layer first exists to animate.
      startShelterHighlightPulse(map, shelterHighlightAnimRef)
    }
    if (map.isStyleLoaded()) apply()
    else map.once('load', apply)

    return () => {
      if (shelterHighlightAnimRef.current) {
        cancelAnimationFrame(shelterHighlightAnimRef.current)
        shelterHighlightAnimRef.current = null
      }
    }
  }, [state.shelters.result])

  // --- shelter candidates visibility toggle ---
  useEffect(() => {
    const map = mapRef.current
    if (!map || !map.getLayer(SHELTERS_FILL_LAYER)) return
    const visibility = state.sheltersLayerVisible ? 'visible' : 'none'
    map.setLayoutProperty(SHELTERS_FILL_LAYER, 'visibility', visibility)
    map.setLayoutProperty(SHELTERS_LABEL_LAYER, 'visibility', visibility)
    map.setLayoutProperty(SHELTERS_HIGHLIGHT_LAYER, 'visibility', visibility)
  }, [state.sheltersLayerVisible])

  // --- shelter candidate click-to-inspect popup --- same delegated-by-
  // layer-id, bound-once shape as the classified-buildings popup below.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    const onClick = (e) => {
      const feature = e.features?.[0]
      if (!feature) return
      const {
        rank,
        hazard_label: hazardLabel,
        suitability_score: score,
        distance_to_road_m: distance,
        footprint_area_m2: area,
      } = feature.properties
      const distanceText = distance != null ? `${Math.round(distance)} m to nearest road` : 'road distance unknown'
      const areaText = area != null ? `${Math.round(area)} m² footprint` : 'footprint area unknown'
      new maplibregl.Popup({ closeButton: true, closeOnClick: true, maxWidth: '220px' })
        .setLngLat(e.lngLat)
        .setHTML(
          `<div style="font-size:13px"><strong>Shelter candidate #${rank}</strong><br/>Hazard: ${hazardLabel}<br/>` +
            `${areaText}<br/>${distanceText}<br/>Suitability: ${Math.round(score * 100)}%</div>`
        )
        .addTo(map)
    }
    const onEnter = () => {
      map.getCanvas().style.cursor = 'pointer'
    }
    const onLeave = () => {
      map.getCanvas().style.cursor = stateRef.current.aoiMode === 'draw' ? 'crosshair' : 'grab'
    }

    // Bound to both the fill layer AND the (larger, easier-to-hit)
    // highlight halo -- both carry the same feature properties (built
    // from the same candidates list), so either one produces an
    // identical popup; this just makes the whole highlighted area
    // clickable, not only a real building's own small footprint.
    for (const layerId of [SHELTERS_FILL_LAYER, SHELTERS_HIGHLIGHT_LAYER]) {
      map.on('click', layerId, onClick)
      map.on('mouseenter', layerId, onEnter)
      map.on('mouseleave', layerId, onLeave)
    }
    return () => {
      for (const layerId of [SHELTERS_FILL_LAYER, SHELTERS_HIGHLIGHT_LAYER]) {
        map.off('click', layerId, onClick)
        map.off('mouseenter', layerId, onEnter)
        map.off('mouseleave', layerId, onLeave)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- bind once; handlers read stateRef for live state
  }, [])

  // --- classified buildings click-to-inspect popup --- bound once
  // (delegated by layer id, MapLibre's own pattern for basins-fill/
  // districts-fill above), not re-bound every time the layer above is
  // removed/re-added -- a click landing in the brief window where the
  // layer doesn't exist just matches nothing, never a stale popup or a
  // second stacked listener from a naive re-bind.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    const onClick = (e) => {
      const feature = e.features?.[0]
      if (!feature) return
      const { hazard_class: hazardClass, hazard_label: hazardLabel } = feature.properties
      const label = hazardLabel || (hazardClass == null ? 'No data at this location' : `Class ${hazardClass}`)
      new maplibregl.Popup({ closeButton: true, closeOnClick: true, maxWidth: '220px' })
        .setLngLat(e.lngLat)
        .setHTML(`<div style="font-size:13px"><strong>Building</strong><br/>Hazard class: ${label}</div>`)
        .addTo(map)
    }
    const onEnter = () => {
      map.getCanvas().style.cursor = 'pointer'
    }
    const onLeave = () => {
      map.getCanvas().style.cursor = stateRef.current.aoiMode === 'draw' ? 'crosshair' : 'grab'
    }

    map.on('click', BUILDINGS_LAYER, onClick)
    map.on('mouseenter', BUILDINGS_LAYER, onEnter)
    map.on('mouseleave', BUILDINGS_LAYER, onLeave)
    return () => {
      map.off('click', BUILDINGS_LAYER, onClick)
      map.off('mouseenter', BUILDINGS_LAYER, onEnter)
      map.off('mouseleave', BUILDINGS_LAYER, onLeave)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- bind once; handlers read stateRef for live state
  }, [])

  return <div ref={containerRef} className="map-view" />
}

/**
 * Pulses SHELTERS_HIGHLIGHT_LAYER's own circle-radius/circle-opacity via
 * requestAnimationFrame, since MapLibre's canvas-rendered paint
 * properties have no CSS-keyframe equivalent -- see that layer's own
 * comment for why this is one of only two places in this file
 * (alongside useHeroScrollScale.js's own documented landing-page
 * exception) that ticks a paint property directly rather than a CSS
 * transition. `animRef` is the calling component's own ref, so its
 * effect can cancel this loop on cleanup/unmount without needing this
 * function to be a hook itself.
 *
 * Respects prefers-reduced-motion the same way useHeroScrollScale.js/
 * useScrollZoom.js already do on the landing page: no animation loop at
 * all, just a fixed, still-visible (not suppressed) radius/opacity.
 */
function startShelterHighlightPulse(map, animRef) {
  let reducedMotion = false
  try {
    reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    // matchMedia unavailable in some test/embed environments -- fall through to the animated path
  }
  if (reducedMotion) {
    if (map.getLayer(SHELTERS_HIGHLIGHT_LAYER)) {
      map.setPaintProperty(SHELTERS_HIGHLIGHT_LAYER, 'circle-radius', 12)
      map.setPaintProperty(SHELTERS_HIGHLIGHT_LAYER, 'circle-opacity', 0.4)
    }
    return
  }

  const tick = (timestamp) => {
    // The layer is removed (and this same rAF handle cancelled) the
    // instant a new shelters result replaces this one -- this check is
    // a defensive second line, not the primary stop mechanism, in case
    // a frame was already queued the instant that happened.
    if (!map.getLayer(SHELTERS_HIGHLIGHT_LAYER)) return
    const phase = (timestamp % SHELTERS_HIGHLIGHT_ANIMATION_MS) / SHELTERS_HIGHLIGHT_ANIMATION_MS
    const wave = (Math.sin(phase * Math.PI * 2) + 1) / 2 // 0..1, smooth breathing rather than a linear sawtooth
    map.setPaintProperty(SHELTERS_HIGHLIGHT_LAYER, 'circle-radius', 10 + wave * 8)
    map.setPaintProperty(SHELTERS_HIGHLIGHT_LAYER, 'circle-opacity', 0.25 + wave * 0.35)
    animRef.current = requestAnimationFrame(tick)
  }
  animRef.current = requestAnimationFrame(tick)
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
