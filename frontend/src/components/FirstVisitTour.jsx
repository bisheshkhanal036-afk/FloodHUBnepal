// A one-time walkthrough of the tool's own step-rail flow, shown the
// first time a real visitor (not returning, per TOUR_STORAGE_KEY in
// localStorage -- same persistence shape THEME_STORAGE_KEY/
// FLOW_STORAGE_KEY in AppStateContext.jsx already use) reaches the
// researcher tool view. Reuses AboutModal's own .modal-overlay/.modal
// markup/CSS rather than inventing a second modal treatment -- this is
// the same kind of lightweight informational overlay, just shown
// automatically once instead of via a persistent header button.
import { useEffect, useState } from 'react'

const TOUR_STORAGE_KEY = 'flood-risk-tour-seen'

const STEPS = [
  {
    title: 'Area of interest',
    body: 'Draw a rectangle on the map, or select a hydrological basin or district instead — all three flow into the same analysis.',
  },
  {
    title: 'Criteria & weighting',
    body: 'Check which physical and exposure factors to include (elevation, slope, drainage, land cover, and more), then weigh them — equal weights, structured pairwise comparison (AHP), or your own typed values.',
  },
  {
    title: 'Compute',
    body: 'Generates a per-pixel flood risk surface from your inputs, with live progress as each factor is fetched and combined.',
  },
  {
    title: 'Report, Validate, Compare, Shelters',
    body: 'Once computed, four follow-up steps unlock: a full vulnerability report, checking your result against a real observed flood, comparing it to METEOR’s own modeled hazard, and identifying candidate shelter sites.',
  },
]

function hasSeenTour() {
  try {
    return localStorage.getItem(TOUR_STORAGE_KEY) === '1'
  } catch {
    // localStorage unavailable -- default to showing the tour every
    // time rather than crashing; a repeat viewer just sees it again.
    return false
  }
}

function markTourSeen() {
  try {
    localStorage.setItem(TOUR_STORAGE_KEY, '1')
  } catch {
    // Non-fatal -- worst case the tour shows again next visit.
  }
}

export default function FirstVisitTour() {
  const [open, setOpen] = useState(() => !hasSeenTour())
  const [step, setStep] = useState(0)

  useEffect(() => {
    if (!open) return
    const onKeyDown = (e) => {
      if (e.key === 'Escape') dismiss()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- dismiss is stable enough for this one-shot listener
  }, [open])

  if (!open) return null

  function dismiss() {
    markTourSeen()
    setOpen(false)
  }

  const isLast = step === STEPS.length - 1
  const current = STEPS[step]

  return (
    <div className="modal-overlay" onClick={dismiss}>
      <div className="modal tour-modal" role="dialog" aria-modal="true" aria-label="Quick tour" onClick={(e) => e.stopPropagation()}>
        <div className="modal__header">
          <h2 className="modal__title">Welcome — a quick tour</h2>
          <button type="button" className="modal__close" onClick={dismiss} aria-label="Skip tour">
            ×
          </button>
        </div>
        <div className="modal__body">
          <p className="tour-modal__step-label">
            {step + 1} of {STEPS.length}
          </p>
          <h3 className="tour-modal__title">{current.title}</h3>
          <p className="tour-modal__body">{current.body}</p>
          <div className="tour-modal__dots">
            {STEPS.map((_, i) => (
              <span key={i} className={`tour-modal__dot ${i === step ? 'tour-modal__dot--active' : ''}`} />
            ))}
          </div>
          <div className="tour-modal__actions">
            <button type="button" className="link-button" onClick={dismiss}>
              Skip
            </button>
            <button
              type="button"
              className="button button--primary"
              onClick={() => (isLast ? dismiss() : setStep((s) => s + 1))}
            >
              {isLast ? "Let's start" : 'Next'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
