"""REST endpoints for basin-based AOI selection — an alternative to
drawing a bbox by hand, not a replacement for it. GET .../aoi returns the
same shape app.common.aoi.AOIInput accepts, so a selected basin flows
into POST /api/overlay/compute through the exact same request field a
hand-drawn bbox does.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.data.basins import get_basin, list_basins_overlapping_nepal
from app.data.errors import BasinNotFoundError, DataSourceUnavailableError

from .models import BasinAOIResponse, BasinDetail, BasinFeature, BasinFeatureCollection

router = APIRouter(prefix="/api/basins", tags=["basins"])


@router.get("", response_model=BasinFeatureCollection)
def list_basins() -> BasinFeatureCollection:
    """GeoJSON basin polygons overlapping Nepal's rough extent (a
    generous screening filter — cross-border basins are kept in full,
    not clipped), each tagged with its support_status. Responds 503 if
    the HydroBASINS file isn't available/valid — see
    app/data/basins.py's module docstring for the expected format.
    """
    try:
        gdf = list_basins_overlapping_nepal()
    except DataSourceUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"error": "basins_unavailable", "message": str(exc)}) from exc

    return BasinFeatureCollection(features=[BasinFeature.from_basin_row(row) for _, row in gdf.iterrows()])


@router.get("/{hybas_id}", response_model=BasinDetail)
def get_basin_detail(hybas_id: int) -> BasinDetail:
    try:
        row = get_basin(hybas_id)
    except DataSourceUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"error": "basins_unavailable", "message": str(exc)}) from exc
    except BasinNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"error": "basin_not_found", "message": str(exc)}) from exc

    return BasinDetail.from_basin_row(row)


@router.get("/{hybas_id}/aoi", response_model=BasinAOIResponse)
def get_basin_aoi(hybas_id: int) -> BasinAOIResponse:
    """The AOI for this basin — bbox_4326 (the polygon's bounding
    envelope) plus the true polygon — ready to paste directly into
    POST /api/overlay/compute's `aoi` field unchanged.
    """
    try:
        row = get_basin(hybas_id)
    except DataSourceUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"error": "basins_unavailable", "message": str(exc)}) from exc
    except BasinNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"error": "basin_not_found", "message": str(exc)}) from exc

    return BasinAOIResponse.from_basin_row(row)
