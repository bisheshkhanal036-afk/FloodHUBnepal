// Citizen Mode: tap a location, get one plain-language answer about
// whether that place has historically tended to flood.
//
// Built for someone deciding where to live or what land to buy -- not
// for someone in an emergency. That framing is why every string here
// says "has historically tended to" rather than "is", and why the
// disclaimer is rendered as a first-class part of the answer rather
// than a footnote.
//
// Deliberately self-contained: its own MapLibre instance, its own state,
// no AppStateContext. The researcher tool's state shape (AOI, criteria,
// AHP matrices, classification, overlay) has nothing this view needs,
// and coupling them would mean every future change to one risks the
// other. The two modes share the backend, not the frontend.
//
// All user-facing text for the ANSWER comes from the backend
// (backend/app/citizen/models.py) in the requested language, so a client
// can never render a risk level without the caveat that qualifies it.
// Only this view's own chrome (buttons, headings) is translated here.
import { useCallback, useEffect, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import { assessLocation } from '../api/client'

// Kathmandu Valley pilot area -- must match
// backend/app/citizen/service.py's PILOT_BBOX.
const PILOT_BBOX = [85.22, 27.6, 85.52, 27.82]
const PILOT_CENTER = [85.324, 27.7172]

const UI = {
  en: {
    title: 'Check your area',
    subtitle: 'Has this place tended to flood in the past?',
    instruction: 'Tap anywhere on the map to check a location.',
    useMyLocation: 'Use my location',
    locating: 'Finding you…',
    locationDenied: 'Location permission was declined. Tap the map instead.',
    locationUnavailable: 'Could not get your location. Tap the map instead.',
    checking: 'Checking…',
    checkingLong: 'Preparing the valley map — this can take up to a minute the first time.',
    back: 'Back',
    whyThis: 'Why this result',
    accuracy: 'How accurate is this?',
    accuracyBody: (v) =>
      `Tested against ${v.n_flood_points} real flood records from ${v.inventory_years} ` +
      `(${v.inventory_source}). Score: ${v.auc.toFixed(2)} out of 1.0, where 0.5 would be ` +
      `no better than guessing. ${v.note}`,
    langToggle: 'नेपाली',
    tapped: 'Selected location',
    history: 'Flood records near here',
    riverHeading: 'Nearest river',
    howHeading: 'How this is worked out',
    weightsIntro: 'What the score is based on',
    showDetail: 'Show the full breakdown',
    hideDetail: 'Hide the breakdown',
  },
  ne: {
    title: 'आफ्नो क्षेत्र हेर्नुहोस्',
    subtitle: 'के यो ठाउँमा विगतमा बाढी आउने गरेको छ?',
    instruction: 'कुनै स्थान जाँच्न नक्सामा थिच्नुहोस्।',
    useMyLocation: 'मेरो स्थान प्रयोग गर्नुहोस्',
    locating: 'स्थान खोज्दै…',
    locationDenied: 'स्थानको अनुमति अस्वीकृत भयो। नक्सामा थिच्नुहोस्।',
    locationUnavailable: 'तपाईंको स्थान पाउन सकिएन। नक्सामा थिच्नुहोस्।',
    checking: 'जाँच गर्दै…',
    checkingLong: 'उपत्यकाको नक्सा तयार गर्दै — पहिलो पटक एक मिनेटसम्म लाग्न सक्छ।',
    back: 'पछाडि',
    whyThis: 'किन यस्तो नतिजा',
    accuracy: 'यो कति सही छ?',
    accuracyBody: (v) =>
      `${v.inventory_years} का ${v.n_flood_points} वास्तविक बाढीका अभिलेखसँग परीक्षण गरिएको ` +
      `(${v.inventory_source})। अंक: १.० मध्ये ${v.auc.toFixed(2)}, जहाँ ०.५ भनेको अनुमान ` +
      `भन्दा राम्रो होइन। ${v.note}`,
    langToggle: 'English',
    tapped: 'छानिएको स्थान',
    history: 'यस वरपरका बाढी अभिलेख',
    riverHeading: 'नजिकको नदी',
    howHeading: 'यो कसरी निकालिएको हो',
    weightsIntro: 'अंक केमा आधारित छ',
    showDetail: 'पूरा विवरण हेर्नुहोस्',
    hideDetail: 'विवरण लुकाउनुहोस्',
  },
}

const RISK_CLASS = { low: 'citizen-risk--low', moderate: 'citizen-risk--moderate', high: 'citizen-risk--high' }

export default function CitizenView({ onBack }) {
  const [lang, setLang] = useState('en')
  const [result, setResult] = useState(null)
  const [status, setStatus] = useState('idle') // idle | loading | error
  const [error, setError] = useState(null)
  const [slowHint, setSlowHint] = useState(false)
  const [picked, setPicked] = useState(null)
  const [showDetail, setShowDetail] = useState(false)

  const mapContainer = useRef(null)
  const mapRef = useRef(null)
  const markerRef = useRef(null)
  const t = UI[lang]

  // --- map -----------------------------------------------------------
  useEffect(() => {
    if (mapRef.current || !mapContainer.current) return

    const map = new maplibregl.Map({
      container: mapContainer.current,
      // Raster OSM rather than a vector style: no API key, and this view
      // only needs a recognisable backdrop to confirm "yes, that's my
      // neighbourhood" -- not a styled analytical basemap.
      style: {
        version: 8,
        sources: {
          osm: {
            type: 'raster',
            tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
            tileSize: 256,
            attribution: '© OpenStreetMap contributors',
          },
        },
        layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
      },
      center: PILOT_CENTER,
      zoom: 11,
      maxBounds: [
        [PILOT_BBOX[0] - 0.25, PILOT_BBOX[1] - 0.25],
        [PILOT_BBOX[2] + 0.25, PILOT_BBOX[3] + 0.25],
      ],
    })
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')

    map.on('load', () => {
      // Show the pilot boundary, so it is obvious what is and isn't covered.
      map.addSource('pilot', {
        type: 'geojson',
        data: {
          type: 'Feature',
          geometry: {
            type: 'Polygon',
            coordinates: [[
              [PILOT_BBOX[0], PILOT_BBOX[1]], [PILOT_BBOX[2], PILOT_BBOX[1]],
              [PILOT_BBOX[2], PILOT_BBOX[3]], [PILOT_BBOX[0], PILOT_BBOX[3]],
              [PILOT_BBOX[0], PILOT_BBOX[1]],
            ]],
          },
        },
      })
      map.addLayer({
        id: 'pilot-fill', type: 'fill', source: 'pilot',
        paint: { 'fill-color': '#0e7c86', 'fill-opacity': 0.06 },
      })
      map.addLayer({
        id: 'pilot-line', type: 'line', source: 'pilot',
        paint: { 'line-color': '#0e7c86', 'line-width': 1.5, 'line-dasharray': [3, 2] },
      })
    })

    map.on('click', (e) => check(e.lngLat.lng, e.lngLat.lat))
    mapRef.current = map
    return () => { map.remove(); mapRef.current = null }
    // check is stable enough for this one-time init; re-running would
    // tear down and rebuild the map on every language change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Re-check the same point when the language changes, so the answer
  // text switches language rather than going stale or disappearing.
  useEffect(() => {
    if (picked) check(picked.lon, picked.lat, { silent: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lang])

  const check = useCallback(
    async (lon, lat, { silent = false } = {}) => {
      setPicked({ lon, lat })
      if (!silent) { setStatus('loading'); setError(null) }
      setSlowHint(false)
      const slowTimer = setTimeout(() => setSlowHint(true), 4000)

      const map = mapRef.current
      if (map) {
        if (markerRef.current) markerRef.current.remove()
        markerRef.current = new maplibregl.Marker({ color: '#a63a2e' }).setLngLat([lon, lat]).addTo(map)
      }

      try {
        const data = await assessLocation({ lat, lon, lang })
        setResult(data)
        setStatus('idle')
      } catch (err) {
        setError(err.message || String(err))
        setStatus('error')
      } finally {
        clearTimeout(slowTimer)
        setSlowHint(false)
      }
    },
    [lang]
  )

  const useMyLocation = useCallback(() => {
    if (!navigator.geolocation) { setError(t.locationUnavailable); setStatus('error'); return }
    setStatus('loading')
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const { longitude, latitude } = pos.coords
        mapRef.current?.flyTo({ center: [longitude, latitude], zoom: 14 })
        check(longitude, latitude)
      },
      (err) => {
        setError(err.code === err.PERMISSION_DENIED ? t.locationDenied : t.locationUnavailable)
        setStatus('error')
      },
      { enableHighAccuracy: true, timeout: 10000 }
    )
  }, [check, t])

  return (
    <div className="citizen">
      <header className="citizen__bar">
        <button type="button" className="citizen__back" onClick={onBack}>← {t.back}</button>
        <div className="citizen__titles">
          <h1>{t.title}</h1>
          <p>{t.subtitle}</p>
        </div>
        <button
          type="button"
          className="citizen__lang"
          onClick={() => setLang((l) => (l === 'en' ? 'ne' : 'en'))}
        >
          {t.langToggle}
        </button>
      </header>

      <div className="citizen__body">
        <div className="citizen__map" ref={mapContainer} />

        <aside className="citizen__panel">
          <div className="citizen__actions">
            <button type="button" className="citizen__locate" onClick={useMyLocation}>
              {status === 'loading' && !result ? t.locating : t.useMyLocation}
            </button>
            <p className="citizen__hint">{t.instruction}</p>
          </div>

          {status === 'loading' && (
            <p className="citizen__loading">{slowHint ? t.checkingLong : t.checking}</p>
          )}

          {status === 'error' && <p className="citizen__error">{error}</p>}

          {result && status !== 'loading' && (
            <>
              {result.covered ? (
                <>
                  <div className={`citizen-risk ${RISK_CLASS[result.risk_level]}`}>
                    <span className="citizen-risk__label">{result.risk_level_text}</span>
                    <p className="citizen-risk__summary">{result.summary}</p>
                  </div>

                  {result.percentile_text && (
                    <p className="citizen__percentile">{result.percentile_text}</p>
                  )}

                  {result.reasons?.length > 0 && (
                    <section className="citizen__reasons">
                      <h2>{t.whyThis}</h2>
                      <ul>
                        {result.reasons.map((r) => (
                          <li key={r.code} className={`citizen__reason citizen__reason--${r.severity}`}>
                            <span className="citizen__reason-text">{r.text}</span>
                            {showDetail && r.percentile_text && (
                              <span className="citizen__reason-detail">
                                {r.criterion_label} · {r.percentile_text} · weight {Math.round(r.weight * 100)}%
                              </span>
                            )}
                          </li>
                        ))}
                      </ul>
                      <button
                        type="button"
                        className="citizen__detail-toggle"
                        onClick={() => setShowDetail((v) => !v)}
                      >
                        {showDetail ? t.hideDetail : t.showDetail}
                      </button>
                    </section>
                  )}

                  {/* Real recorded floods nearby. The strongest evidence we
                      can offer, because the reader can check it against
                      their own memory of the place. */}
                  {result.flood_history && (
                    <section className="citizen__history">
                      <h2>{t.history}</h2>
                      <p className="citizen__history-summary">{result.flood_history.summary}</p>
                      {result.flood_history.records?.length > 0 && (
                        <ul>
                          {result.flood_history.records.map((h, i) => (
                            <li key={`${h.date}-${h.distance_m}-${i}`}>
                              <span className="citizen__history-date">{h.date}</span>
                              <span className="citizen__history-dist">{h.distance_m} m</span>
                              <span className="citizen__history-place">{h.place}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                      <p className="citizen__history-caveat">{result.flood_history.caveat}</p>
                    </section>
                  )}

                  {/* Context only -- never a reason. See the backend's
                      context.py on why river distance is deliberately not
                      part of the score in this valley. */}
                  {result.nearest_river && (
                    <section className="citizen__river">
                      <h2>{t.riverHeading}</h2>
                      <p>{result.nearest_river.text}</p>
                      <p className="citizen__river-note">{result.nearest_river.not_a_reason_text}</p>
                    </section>
                  )}

                  {result.how_it_works && (
                    <details className="citizen__how">
                      <summary>{t.howHeading}</summary>
                      <p>{result.how_it_works.text}</p>
                      <ul className="citizen__weights">
                        {result.how_it_works.criteria.map((c) => (
                          <li key={c.id}>
                            <span className="citizen__weight-bar" style={{ width: `${c.weight_pct * 2}%` }} />
                            <span className="citizen__weight-label">{c.label}</span>
                            <span className="citizen__weight-pct">{c.weight_pct}%</span>
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}

                  {result.validation && (
                    <details className="citizen__accuracy">
                      <summary>{t.accuracy}</summary>
                      <p>{t.accuracyBody(result.validation)}</p>
                    </details>
                  )}
                </>
              ) : (
                <p className="citizen__uncovered">{result.message}</p>
              )}

              <p className="citizen__disclaimer">{result.disclaimer}</p>
              <p className="citizen__experimental">{result.experimental_notice}</p>
            </>
          )}
        </aside>
      </div>
    </div>
  )
}
