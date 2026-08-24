// Legend for the METEOR flood hazard reference overlay (MapView.jsx's
// MeteorFloodControl) -- a plain React component, not a MapLibre
// IControl, since (unlike BasemapControl/MeteorFloodControl themselves)
// it has no interactive elements of its own, just an image + caption
// that needs to react to React state (meteorFloodVisible/Type/
// ReturnPeriod) -- exactly DataGapNotice's own shape (App.jsx's
// `.map-area` wraps MapView plus everything that floats on top of it as
// absolutely-positioned siblings, not children of MapView's own
// MapLibre-managed root div).
//
// The image itself is METEOR's own real GetLegendGraphic (WMS, MapProxy)
// output, not a hand-drawn recreation -- fetched live so it can never
// drift from whatever styling the live overlay tiles actually use.
// GetCapabilities' own advertised LegendURL (verified live during
// implementation, WMS GetCapabilities) points at an internal hostname
// ("https://gem/mapproxy/...") that isn't publicly resolvable -- the
// query string past the host is otherwise correct, so this module
// rebuilds the same request against the public host
// (maps.meteor-project.org) that MapView.jsx's WMTS tiles already use.
import { useAppState } from '../state/AppStateContext'

function meteorLegendUrl(floodType, returnPeriod) {
  const layer = `${floodType}-1in${returnPeriod}`
  return (
    'https://maps.meteor-project.org/mapproxy/npl-flood/ows' +
    `?format=${encodeURIComponent('image/png')}` +
    `&layer=${encodeURIComponent(layer)}` +
    '&sld_version=1.1.0&request=GetLegendGraphic&service=WMS&version=1.1.1&styles='
  )
}

const FLOOD_TYPE_LABELS = {
  fd: 'Fluvial (Defended)',
  fu: 'Fluvial (Undefended)',
  p: 'Pluvial',
}

export default function MeteorFloodLegend() {
  const { state } = useAppState()
  if (!state.meteorFloodVisible) return null

  const { meteorFloodType, meteorFloodReturnPeriod } = state
  const url = meteorLegendUrl(meteorFloodType, meteorFloodReturnPeriod)

  return (
    <div className="meteor-flood-legend">
      <p className="meteor-flood-legend__title">
        Flood depth (m) — {FLOOD_TYPE_LABELS[meteorFloodType]}, 1-in-{meteorFloodReturnPeriod}y
      </p>
      <img
        className="meteor-flood-legend__image"
        src={url}
        alt={`METEOR flood hazard legend: ${meteorFloodType}-1in${meteorFloodReturnPeriod}`}
        // If the live legend image ever fails to load (network hiccup,
        // upstream change), fall back to hiding the broken-image icon
        // rather than leaving it visible -- the title/attribution text
        // above and below still tell the user what the overlay shows.
        onError={(e) => {
          e.currentTarget.style.display = 'none'
        }}
      />
      <p className="meteor-flood-legend__attribution">METEOR Project / Fathom — ODbL</p>
    </div>
  )
}
