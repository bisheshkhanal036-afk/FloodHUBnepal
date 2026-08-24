"""REST endpoints for basin-based AOI selection — an alternative to
drawing a bbox by hand, not a replacement for it. GET .../aoi returns the
same shape app.common.aoi.AOIInput accepts, so a selected basin flows
into POST /api/overlay/compute through the exact same request field a
hand-drawn bbox does.

Every endpoint takes an optional `level` query param (8 or 9, default 8
— app.data.basins.DEFAULT_BASIN_LEVEL) selecting which HydroBASINS
resolution to look in: level 8 (~28,907 basins Asia-wide, coarser/larger
catchments) or level 9 (~77,849 basins, finer sub-catchments). Validated
by hand against SUPPORTED_BASIN_LEVELS below (a 422 for anything else) —
not typed as Literal[8, 9] directly, since query params arrive as
strings and this FastAPI/Pydantic version's Literal validation doesn't
coerce "9" -> 9 the way a plain `int` annotation does, which would
otherwise reject every real request (verified live during
implementation: literally every level=8/level=9 call 422'd until this
was caught).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.data.basins import (
    DEFAULT_BASIN_LEVEL,
    SUPPORTED_BASIN_LEVELS,
    get_basin,
    list_basins_overlapping_nepal,
)
from app.data.errors import BasinNotFoundError, DataSourceUnavailableError

from .models import BasinAOIResponse, BasinDetail, BasinFeature, BasinFeatureCollection

router = APIRouter(prefix="/api/basins", tags=["basins"])

_LEVEL_QUERY = Query(DEFAULT_BASIN_LEVEL, description="HydroBASINS level to look in: 8 (coarser) or 9 (finer).")


def _check_level(level: int) -> None:
    if level not in SUPPORTED_BASIN_LEVELS:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_basin_level",
                "message": f"level must be one of {SUPPORTED_BASIN_LEVELS}, got {level}",
            },
        )


@router.get("", response_model=BasinFeatureCollection)
def list_basins(level: int = _LEVEL_QUERY) -> BasinFeatureCollection:
    """GeoJSON basin polygons overlapping Nepal's rough extent (a
    generous screening filter — cross-border basins are kept in full,
    not clipped), each tagged with its support_status. Responds 503 if
    the HydroBASINS file for the requested level isn't available/valid —
    see app/data/basins.py's module docstring for the expected format.
    """
    _check_level(level)
    try:
        gdf = list_basins_overlapping_nepal(level=level)
    except DataSourceUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"error": "basins_unavailable", "message": str(exc)}) from exc

    return BasinFeatureCollection(features=[BasinFeature.from_basin_row(row, level=level) for _, row in gdf.iterrows()])


@router.get("/{hybas_id}", response_model=BasinDetail)
def get_basin_detail(hybas_id: int, level: int = _LEVEL_QUERY) -> BasinDetail:
    _check_level(level)
    try:
        row = get_basin(hybas_id, level=level)
    except DataSourceUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"error": "basins_unavailable", "message": str(exc)}) from exc
    except BasinNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"error": "basin_not_found", "message": str(exc)}) from exc

    return BasinDetail.from_basin_row(row, level=level)


@router.get("/{hybas_id}/aoi", response_model=BasinAOIResponse)
def get_basin_aoi(hybas_id: int, level: int = _LEVEL_QUERY) -> BasinAOIResponse:
    """The AOI for this basin — bbox_4326 (the polygon's bounding
    envelope) plus the true polygon — ready to paste directly into
    POST /api/overlay/compute's `aoi` field unchanged.
    """
    _check_level(level)
    try:
        row = get_basin(hybas_id, level=level)
    except DataSourceUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"error": "basins_unavailable", "message": str(exc)}) from exc
    except BasinNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"error": "basin_not_found", "message": str(exc)}) from exc

    return BasinAOIResponse.from_basin_row(row)
