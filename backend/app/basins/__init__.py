"""Basin-based AOI selection API: GET /api/basins, /api/basins/{hybas_id},
and /api/basins/{hybas_id}/aoi. Logic lives in app/data/basins.py; this
package is HTTP-only (request/response models + routing), mirroring how
app/overlay/ wraps app/data/ rather than putting endpoints inside it.
"""

from .router import router

__all__ = ["router"]
