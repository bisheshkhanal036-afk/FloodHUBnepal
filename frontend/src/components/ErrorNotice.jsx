// A shared error display: a plain-language headline (lib/friendlyError.js,
// keyed off the backend's own error code) with the raw backend message
// still available underneath (collapsed, never hidden entirely — this
// project's own "document the real cause" convention applied to
// end-user-facing text too), plus an optional one-click Retry button so
// a transient failure (the documented DEM/WorldCover CURL blips, a slow
// OSM parse, etc.) doesn't force a user back through the sidebar to
// re-trigger the same request.
import { friendlyErrorMessage } from '../lib/friendlyError'

export default function ErrorNotice({ error, fallback, onRetry, retryLabel = 'Retry' }) {
  const { headline, detail } = friendlyErrorMessage(error, fallback)

  return (
    <div className="field-error error-notice">
      <p className="error-notice__headline">{headline}</p>
      {detail && (
        <details className="error-notice__detail">
          <summary>Details</summary>
          <p>{detail}</p>
        </details>
      )}
      {onRetry && (
        <button type="button" className="link-button error-notice__retry" onClick={onRetry}>
          {retryLabel}
        </button>
      )}
    </div>
  )
}
