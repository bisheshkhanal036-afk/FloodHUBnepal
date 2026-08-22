// Team / data credits -- shared between the landing page's dedicated
// Credits section and the in-tool About modal (AboutModal.jsx, opened
// from Sidebar) so the content only has to be maintained in one place.
// Purely presentational: reads static content from config/attribution.js,
// no app state, no API calls.
import { ADDITIONAL_SOURCE_CREDITS, SOURCE_ATTRIBUTIONS, TEAM_CREDITS } from '../config/attribution'

export default function CreditsSection({ variant = 'page' }) {
  return (
    <div className={`credits credits--${variant}`}>
      <div className="credits__group">
        <h3 className="credits__heading">Team</h3>
        <div className="credits__grid credits__grid--team">
          {TEAM_CREDITS.map((person) => (
            <div className="credit-card credit-card--person" key={person.id}>
              {person.photo ? (
                <img className="credit-card__photo" src={person.photo} alt={person.name} />
              ) : (
                <div className="credit-card__avatar" aria-hidden="true">
                  {person.name.charAt(0)}
                </div>
              )}
              <div className="credit-card__name">{person.name}</div>
              <a className="credit-card__email" href={`mailto:${person.email}`}>
                {person.email}
              </a>
              {person.linkedin && (
                <a className="credit-card__linkedin" href={person.linkedin} target="_blank" rel="noreferrer">
                  LinkedIn ↗
                </a>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="credits__group">
        <h3 className="credits__heading">Data sources</h3>
        <div className="credits__grid">
          {SOURCE_ATTRIBUTIONS.map((s) => (
            <div className="credit-card credit-card--text" key={s.id}>
              <div className="credit-card__name">{s.name}</div>
              <p className="credit-card__text">{s.text}</p>
            </div>
          ))}
          {ADDITIONAL_SOURCE_CREDITS.map((s) => (
            <div className="credit-card credit-card--text" key={s.id}>
              <div className="credit-card__name">{s.name}</div>
              <p className="credit-card__text">{s.text}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
