"""REST endpoints for Citizen Mode.

Separate from app/overlay/ on purpose. The overlay endpoints expose the
full researcher pipeline — arbitrary AOIs, arbitrary criteria, three
weighting modes, editable class breaks. These expose exactly one
question ("what about this point?") answered with one validated,
non-negotiable configuration.

Keeping them apart means Citizen Mode cannot be accidentally
reconfigured through the API into something that has not been validated,
and the researcher tool stays completely untouched.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.data.errors import DataSourceUnavailableError

from .models import CitizenAssessRequest, CitizenAssessResponse
from .profile import CITIZEN_CRITERIA, VALIDATION, normalized_weights
from .service import PILOT_BBOX, PILOT_NAME_EN, PILOT_NAME_NE, assess

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/citizen", tags=["citizen"])


@router.post("/assess", response_model=CitizenAssessResponse)
def assess_point(payload: CitizenAssessRequest) -> CitizenAssessResponse:
    """Flood susceptibility at one point, in plain language.

    The first call after a restart computes the pilot surface (~60 s);
    every call after that is a cache hit and returns in well under a
    second. See service.get_pilot_surface for why one shared surface is
    used rather than a bounding box per request.
    """
    try:
        result = assess(payload.lon, payload.lat)
    except DataSourceUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "citizen_data_unavailable", "message": str(exc)},
        ) from exc

    return CitizenAssessResponse.from_assessment(result, payload.lang)


@router.get("/coverage")
def coverage() -> dict:
    """What Citizen Mode currently covers, and how good it is.

    Exposed so the UI can state the model's measured accuracy and the
    pilot boundary rather than the user having to take either on trust.
    """
    return {
        "pilot_area": {
            "name_en": PILOT_NAME_EN,
            "name_ne": PILOT_NAME_NE,
            "bbox_4326": list(PILOT_BBOX),
        },
        "criteria": list(CITIZEN_CRITERIA),
        "weights": normalized_weights(),
        "validation": VALIDATION,
        "status": "experimental",
    }
