"""District-based AOI selection API: GET /api/districts,
/api/districts/{pcode}, and /api/districts/{pcode}/aoi. Logic lives in
app/data/districts.py; this package is HTTP-only (request/response
models + routing), mirroring app/basins/'s own split.
"""

from .router import router

__all__ = ["router"]
