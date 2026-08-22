// FastAPI error bodies come in two different shapes depending on where
// the error originated, and this app needs to show a real message for
// both rather than a generic "something went wrong":
//
// 1. This project's own HTTPException(detail={...}) calls (see e.g.
//    app/overlay/router.py, app/ahp/router.py) — detail is an object
//    with at least {error, message}, and the AHP consistency-check
//    failure additionally carries {failures: [...]}.
// 2. Plain Pydantic request-validation failures (a malformed request
//    body FastAPI itself rejects before any route code runs) — detail
//    is a list of {loc, msg, type} objects.
export class ApiError extends Error {
  constructor(message, { status, code = null, failures = null, raw = null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.failures = failures
    this.raw = raw
  }
}

export function parseErrorDetail(status, body) {
  const detail = body && typeof body === 'object' ? body.detail : undefined

  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    return new ApiError(detail.message || `Request failed (${status})`, {
      status,
      code: detail.error || null,
      failures: detail.failures || null,
      raw: body,
    })
  }

  if (Array.isArray(detail)) {
    const message = detail
      .map((d) => (d && d.loc ? `${d.loc.join('.')}: ${d.msg}` : d?.msg || JSON.stringify(d)))
      .join('; ')
    return new ApiError(message || `Request failed (${status})`, { status, raw: body })
  }

  return new ApiError(`Request failed (${status})`, { status, raw: body })
}
