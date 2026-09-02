// A small colored thumbnail of one criterion's own already-reclassified
// raster (1-5 classes), fetched from the vulnerability report's own
// per-criterion data_url -- these only exist once a report has been
// generated (backend/app/overlay/report.py materializes them as a side
// effect of POST /report, never POST /compute), so this component is
// only ever rendered from ReportPanel.jsx.
//
// Mounted lazily by its caller (only while its containing <details> is
// open) rather than fetching eagerly for every criterion up front -- a
// report with many criteria shouldn't decode rasters nobody looks at.
import { useEffect, useState } from 'react'
import { absoluteDataUrl } from '../api/client'
import { riskValueToCssColor, riskValueToRgb } from '../lib/colorRamp'
import { decodeGeoTiffToDataUrl } from '../lib/rasterPreview'
import ErrorNotice from './ErrorNotice'

// Reclassified rasters are always 1-5 (RECLASSIFIED_NODATA=0,
// backend/app/data/reclassify.py) -- the same class-to-color convention
// ReportPanel's own zonal-stats-table swatches already use
// ((class - 1) / 4 through the same colorRamp.js functions), reused
// here rather than a new palette invented for this one preview.
const RECLASSIFIED_NODATA = 0
const RISK_CLASSES = [1, 2, 3, 4, 5]
const THUMBNAIL_MAX_SIZE = 220

function classToRgb(riskClass) {
  return riskValueToRgb((riskClass - 1) / 4)
}

export default function CriterionSnapshot({ dataUrl }) {
  const [state, setState] = useState({ status: 'loading', imageUrl: null, error: null })
  // Bumped by the Retry button to re-run the effect below without
  // changing `dataUrl` itself -- a plain dependency-array trigger, the
  // same shape a key-change would give, without actually remounting
  // the component (which would also lose whatever else is rendered
  // around it).
  const [retryToken, setRetryToken] = useState(0)

  useEffect(() => {
    let cancelled = false
    setState({ status: 'loading', imageUrl: null, error: null })

    async function load() {
      const response = await fetch(absoluteDataUrl(dataUrl))
      if (!response.ok) throw new Error(`Could not load snapshot (${response.status})`)
      const bytes = await response.arrayBuffer()
      if (cancelled) return
      const { dataUrl: imageUrl } = await decodeGeoTiffToDataUrl(bytes, {
        nodata: RECLASSIFIED_NODATA,
        colorFn: classToRgb,
        maxSize: THUMBNAIL_MAX_SIZE,
      })
      if (cancelled) return
      setState({ status: 'loaded', imageUrl, error: null })
    }

    load().catch((error) => {
      if (!cancelled) setState({ status: 'error', imageUrl: null, error })
    })

    return () => {
      cancelled = true
    }
  }, [dataUrl, retryToken])

  return (
    <div className="criterion-snapshot">
      {state.status === 'loading' && <p className="panel__hint">Loading snapshot…</p>}
      {state.status === 'error' && (
        <ErrorNotice
          error={state.error}
          fallback="Could not load this criterion's snapshot."
          onRetry={() => setRetryToken((t) => t + 1)}
        />
      )}
      {state.status === 'loaded' && (
        <>
          <img className="criterion-snapshot__image" src={state.imageUrl} alt="" />
          <ul className="legend legend--inline criterion-snapshot__legend">
            {RISK_CLASSES.map((riskClass) => (
              <li key={riskClass}>
                <span className="legend__swatch" style={{ background: riskValueToCssColor((riskClass - 1) / 4) }} />
                {riskClass}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
