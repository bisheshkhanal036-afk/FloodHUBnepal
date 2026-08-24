"""Pydantic response models for the basins API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field
from shapely.geometry import mapping

from app.data.basins import basin_area_km2, get_basin_pct_in_nepal, get_basin_support_status


class BasinFeatureProperties(BaseModel):
    hybas_id: int
    level: int = Field(..., description="HydroBASINS level this basin was listed at (8 or 9).")
    support_status: str = Field(
        ..., description="One of: fully_in_nepal, partial_likely_adequate, likely_degraded_at_edges."
    )


class BasinFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict[str, Any]
    properties: BasinFeatureProperties

    @classmethod
    def from_basin_row(cls, row, level: int) -> "BasinFeature":
        hybas_id = int(row.HYBAS_ID)
        return cls(
            geometry=mapping(row.geometry),
            properties=BasinFeatureProperties(
                hybas_id=hybas_id, level=level, support_status=get_basin_support_status(hybas_id, level=level)
            ),
        )


class BasinFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[BasinFeature]


class BasinDetail(BaseModel):
    hybas_id: int
    level: int = Field(..., description="HydroBASINS level this basin was looked up at (8 or 9).")
    support_status: str
    area_km2: float = Field(..., description="The basin's own true area (not its bounding envelope).")
    pct_in_nepal: float = Field(..., description="Percent (0-100) of the basin's true area within NEPAL_BBOX_4326.")
    geometry: dict[str, Any]

    @classmethod
    def from_basin_row(cls, row, level: int) -> "BasinDetail":
        hybas_id = int(row.HYBAS_ID)
        return cls(
            hybas_id=hybas_id,
            level=level,
            support_status=get_basin_support_status(hybas_id, level=level),
            area_km2=basin_area_km2(row.geometry),
            pct_in_nepal=get_basin_pct_in_nepal(hybas_id, level=level) * 100.0,
            geometry=mapping(row.geometry),
        )


class BasinAOIResponse(BaseModel):
    """Same shape as app.common.aoi.AOIInput — paste this straight into
    POST /api/overlay/compute's (or POST /api/ahp/compute's, if it ever
    accepts an AOI) `aoi` field unchanged.
    """

    bbox: list[float]
    polygon: dict[str, Any]

    @classmethod
    def from_basin_row(cls, row) -> "BasinAOIResponse":
        return cls(bbox=list(row.geometry.bounds), polygon=mapping(row.geometry))
