// Literature & methodology modal: a well-cited write-up of every
// criterion (what it is, why it conditions flood risk, how its 5-class
// reclassification ranges are set) plus a consolidated bibliography.
// Opened from the per-feature info (ⓘ) buttons in CriteriaPanel and
// scrolled to the clicked feature via `focusId`. Same modal shell and
// Escape/overlay-close behaviour as AboutModal.
import { useEffect, useMemo, useRef } from 'react'
import { CANONICAL_CLUSTERS, CRITERIA_BY_ID, criteriaByCluster } from '../config/criteria'
import { LITERATURE, METHOD_INTRO, REFERENCES } from '../config/literature'

export default function LiteratureModal({ focusId, onClose }) {
  const bodyRef = useRef(null)

  useEffect(() => {
    const onKeyDown = (e) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  // Scroll the clicked feature into view once the modal is mounted.
  useEffect(() => {
    if (!focusId) return
    const el = bodyRef.current?.querySelector(`#lit-${focusId}`)
    if (el) el.scrollIntoView({ block: 'start' })
  }, [focusId])

  const byCluster = useMemo(() => criteriaByCluster(), [])

  // Only the references actually cited anywhere, in a stable order, for the
  // bibliography at the end.
  const citedRefKeys = useMemo(() => {
    const used = new Set(METHOD_INTRO.refs)
    for (const entry of Object.values(LITERATURE)) entry.refs.forEach((k) => used.add(k))
    return Object.keys(REFERENCES).filter((k) => used.has(k))
  }, [])

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal modal--wide"
        role="dialog"
        aria-modal="true"
        aria-label="Methodology and literature"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal__header">
          <h2 className="modal__title">Methodology &amp; literature</h2>
          <button type="button" className="modal__close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        <div className="modal__body literature" ref={bodyRef}>
          <section className="literature__intro">
            <h3>{METHOD_INTRO.title}</h3>
            {METHOD_INTRO.body.map((p, i) => (
              <p key={i}>{p}</p>
            ))}
            <p className="literature__cited">
              See: {METHOD_INTRO.refs.map((k) => shortCite(k)).join('; ')}.
            </p>
          </section>

          {CANONICAL_CLUSTERS.map((cluster) => {
            const items = byCluster[cluster].filter((c) => LITERATURE[c.id])
            if (items.length === 0) return null
            return (
              <section key={cluster} className="literature__cluster">
                <h3 className="literature__cluster-title">{cluster}</h3>
                {items.map((criterion) => {
                  const lit = LITERATURE[criterion.id]
                  return (
                    <article key={criterion.id} id={`lit-${criterion.id}`} className="literature__feature">
                      <h4>
                        {criterion.label}
                        {criterion.unit ? <span className="literature__unit"> ({criterion.unit})</span> : null}
                      </h4>
                      <p>
                        <strong>What it is.</strong> {lit.whatItIs}
                      </p>
                      <p>
                        <strong>Why it matters for flood risk.</strong> {lit.floodRole}
                      </p>
                      <p>
                        <strong>How the ranges are set.</strong> {lit.rangeBasis}
                      </p>
                      <p className="literature__cited">
                        References: {lit.refs.map((k) => shortCite(k)).join('; ')}.
                      </p>
                    </article>
                  )
                })}
              </section>
            )
          })}

          <section className="literature__refs">
            <h3>References</h3>
            <ol>
              {citedRefKeys.map((k) => (
                <li key={k}>{REFERENCES[k]}</li>
              ))}
            </ol>
            <p className="literature__note">
              Citations are provided for methodological transparency. The exact numeric class breaks are
              expert-defined for the Kathmandu Valley study area and should be validated against an observed
              flood inventory (success-rate / AUC) before formal use.
            </p>
          </section>
        </div>
      </div>
    </div>
  )
}

// Compact in-text citation (author + year) derived from a reference key,
// e.g. "kazakis2015" -> "Kazakis (2015)".
function shortCite(key) {
  const full = REFERENCES[key] || key
  const author = full.split(',')[0].trim()
  const year = (full.match(/\((\d{4})\)/) || [])[1]
  return year ? `${author} (${year})` : author
}

export { LiteratureModal }
