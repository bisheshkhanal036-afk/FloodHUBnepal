"""Pydantic response models for the districts API — mirrors
app/basins/models.py's shape exactly, minus the support_status concept
(a district is, by definition, entirely within Nepal — see
app/data/districts.py's module docstring)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field
from shapely.geometry import mapping

from app.data.districts import district_area_km2


class DistrictFeatureProperties(BaseModel):
    pcode: str = Field(..., description="Admin-2 P-code, e.g. 'NP0101'.")
    name: str
    province: str = Field(..., description="The district's parent province (admin-1) name.")


class DistrictFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict[str, Any]
    properties: DistrictFeatureProperties

    @classmethod
    def from_district_row(cls, row) -> "DistrictFeature":
        return cls(
            geometry=mapping(row.geometry),
            properties=DistrictFeatureProperties(
                pcode=str(row.adm2_pcode), name=str(row.adm2_name), province=str(row.adm1_name)
            ),
        )


class DistrictFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[DistrictFeature]


class DistrictDetail(BaseModel):
    pcode: str
    name: str
    province: str
    area_km2: float = Field(..., description="The district's own true area (not its bounding envelope).")
    geometry: dict[str, Any]

    @classmethod
    def from_district_row(cls, row) -> "DistrictDetail":
        return cls(
            pcode=str(row.adm2_pcode),
            name=str(row.adm2_name),
            province=str(row.adm1_name),
            area_km2=district_area_km2(row.geometry),
            geometry=mapping(row.geometry),
        )


class DistrictAOIResponse(BaseModel):
    """Same shape as app.common.aoi.AOIInput — paste this straight into
    POST /api/overlay/compute's `aoi` field unchanged, mirroring
    app/basins/models.py's BasinAOIResponse.
    """

    bbox: list[float]
    polygon: dict[str, Any]

    @classmethod
    def from_district_row(cls, row) -> "DistrictAOIResponse":
        return cls(bbox=list(row.geometry.bounds), polygon=mapping(row.geometry))
