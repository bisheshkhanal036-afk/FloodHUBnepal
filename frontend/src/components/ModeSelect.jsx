// The fork between Citizen Mode and the researcher tool.
//
// Task-framed, not identity-framed: "Check my area" / "Build a model",
// not "normal people" / "researchers". Nobody self-identifies as a
// normal person, and the labels should describe what you get, not who
// the software thinks you are.
//
// Citizen Mode is listed first and marked experimental. The researcher
// tool is unchanged and unlabelled -- it is the mature path.
export default function ModeSelect({ onCitizen, onResearcher, onBack }) {
  return (
    <div className="mode-select">
      <button type="button" className="mode-select__back" onClick={onBack}>
        ← Back
      </button>

      <div className="mode-select__grid">
        <button type="button" className="mode-card mode-card--citizen" onClick={onCitizen}>
          <span className="mode-card__badge">Experimental</span>
          <h2>Check my area</h2>
          <p className="mode-card__lead">
            Tap a location and find out whether it has tended to flood in the past.
          </p>
          <p className="mode-card__meta">
            One tap · English &amp; नेपाली · Kathmandu Valley only
          </p>
        </button>

        <button type="button" className="mode-card mode-card--research" onClick={onResearcher}>
          <h2>Build a model</h2>
          <p className="mode-card__lead">
            Choose your own area, criteria and weights, and compute a full flood-susceptibility
            surface.
          </p>
          <p className="mode-card__meta">
            AHP weighting · 15 criteria · anywhere in Nepal
          </p>
        </button>
      </div>
    </div>
  )
}
