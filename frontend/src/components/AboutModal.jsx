// Lightweight modal wrapper around CreditsSection, opened from a
// persistent "About" button in Sidebar's header -- so credits (team,
// data sources, methodology) stay reachable from inside the working
// tool, not only on the landing page. Local open/close state only, no
// app state, no API calls.
import { useEffect } from 'react'
import CreditsSection from './CreditsSection'

export default function AboutModal({ onClose }) {
  useEffect(() => {
    const onKeyDown = (e) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="About this tool" onClick={(e) => e.stopPropagation()}>
        <div className="modal__header">
          <h2 className="modal__title">About this project</h2>
          <button type="button" className="modal__close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="modal__body">
          <CreditsSection variant="modal" />
        </div>
      </div>
    </div>
  )
}
