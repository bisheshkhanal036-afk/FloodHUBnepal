// One step in the sidebar's connected step-rail (Sidebar.jsx) -- a
// numbered marker + connecting line down to the next step, a clickable
// header, and a collapsible body. Purely presentational: Sidebar computes
// each step's status/open state and passes it in, so this component has
// no knowledge of AOI/criteria/overlay state itself and can't drift from
// the actual data flow.
export default function StepSection({ number, title, status, isLast, isOpen, onToggle, children }) {
  const collapsible = status !== 'locked'

  return (
    <div className={`step step--${status}`}>
      <div className="step__rail">
        <span className="step__marker" aria-hidden="true">
          {status === 'complete' ? '✓' : number}
        </span>
        {!isLast && <span className="step__connector" />}
      </div>
      <div className="step__body-wrap">
        <button
          type="button"
          className="step__header"
          onClick={collapsible ? onToggle : undefined}
          disabled={!collapsible}
          aria-expanded={collapsible ? isOpen : undefined}
        >
          <span className="step__title">{title}</span>
          {collapsible && <span className="step__chevron">{isOpen ? '−' : '+'}</span>}
        </button>
        {collapsible && isOpen && <div className="step__content">{children}</div>}
      </div>
    </div>
  )
}
