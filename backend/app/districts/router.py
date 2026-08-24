"""REST endpoints for district-based AOI selection — a second alternative
to drawing a bbox by hand, alongside basin selection (app/basins/), not a
replacement for either. GET .../aoi returns the same shape
app.common.aoi.AOIInput accepts, so a selected district flows into
POST /api/overlay/compute through the exact same request field a
hand-drawn bbox or a selected basin does.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.data.districts import get_district, list_districts
from app.data.errors import DataSourceUnavailableError, DistrictNotFoundError

from .models import DistrictAOIResponse, DistrictDetail, DistrictFeature, DistrictFeatureCollection

router = APIRouter(prefix="/api/districts", tags=["districts"])


@router.get("", response_model=DistrictFeatureCollection)
def list_all_districts() -> DistrictFeatureCollection:
    """GeoJSON polygons for all 77 of Nepal's districts. Responds 503 if
    the admin-boundaries file isn't available/valid — see
    app/data/districts.py's module docstring for the expected format.
    """
    try:
        gdf = list_districts()
    except DataSourceUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"error": "districts_unavailable", "message": str(exc)}) from exc

    return DistrictFeatureCollection(features=[DistrictFeature.from_district_row(row) for _, row in gdf.iterrows()])


@router.get("/{pcode}", response_model=DistrictDetail)
def get_district_detail(pcode: str) -> DistrictDetail:
    try:
        row = get_district(pcode)
    except DataSourceUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"error": "districts_unavailable", "message": str(exc)}) from exc
    except DistrictNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"error": "district_not_found", "message": str(exc)}) from exc

    return DistrictDetail.from_district_row(row)


@router.get("/{pcode}/aoi", response_model=DistrictAOIResponse)
def get_district_aoi(pcode: str) -> DistrictAOIResponse:
    """The AOI for this district — bbox_4326 (the polygon's bounding
    envelope) plus the true polygon — ready to paste directly into
    POST /api/overlay/compute's `aoi` field unchanged.
    """
    try:
        row = get_district(pcode)
    except DataSourceUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"error": "districts_unavailable", "message": str(exc)}) from exc
    except DistrictNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"error": "district_not_found", "message": str(exc)}) from exc

    return DistrictAOIResponse.from_district_row(row)
