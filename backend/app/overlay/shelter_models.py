"""Pydantic request/response models for POST /api/overlay/shelters --
kept in its own module rather than folded into models.py (which already
covers /compute and /report) since shelters.py's own domain types
(ShelterCandidate/ShelterIdentificationResult) are unrelated to either
of those two features' own dataclasses; this mirrors the same
one-feature-per-module split models.py/report.py themselves already
use for /report.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from shapely.geometry import mapping

from app.common.aoi import AOIInput

from .models import OverlayCriterionInput
from .shelters import ShelterIdentificationResult
from .urls import hazard_classes_url, risk_surface_url


class ShelterIdentificationRequest(BaseModel):
    aoi: AOIInput = Field(..., description="Same AOI a POST /compute request for this result would use.")
    criteria: list[OverlayCriterionInput] = Field(..., min_length=1)
    final_weights: dict[str, float] = Field(..., description="Same as POST /compute's final_weights.")
    complete: bool = Field(..., description="Same as POST /compute's complete.")
    min_footprint_area_m2: float | None = Field(
        None,
        gt=0,
        description=(
            "A building's own footprint area (computed on the UTM grid) must be at least this large "
            "to be considered a shelter-site candidate. Defaults to "
            "config.SHELTER_MIN_FOOTPRINT_AREA_M2 when omitted."
        ),
    )
    top_n: int | None = Field(
        None, gt=0, le=200, description="How many ranked candidates to return. Defaults to config.SHELTER_DEFAULT_TOP_N."
    )
    safety_weight: float = Field(1.0, ge=0, description="Relative weight of the hazard-class (safety) factor.")
    accessibility_weight: float = Field(1.0, ge=0, description="Relative weight of the distance-to-road factor.")
    service_weight: float = Field(1.0, ge=0, description="Relative weight of the local-population-density factor.")


class ShelterCandidateOut(BaseModel):
    geometry: dict
    footprint_area_m2: float
    hazard_class: int = Field(..., ge=1, le=5, description="Never 4 or 5 (HIGH_RISK_CLASSES) -- excluded outright, not just down-ranked.")
    hazard_label: str
    distance_to_road_m: float | None = Field(None, description="Null only if the AOI has zero road features at all.")
    population_density: float | None = Field(None, description="People/km² at the site; null if population has no data there.")
    suitability_score: float = Field(..., ge=0, le=1, description="0-1, min-max normalized within this AOI's own surviving candidates -- not comparable across AOIs.")
    rank: int = Field(..., ge=1)


class ShelterIdentificationResponse(BaseModel):
    cache_key: str = Field(..., description="Same cache_key POST /compute would return for these same inputs.")
    risk_surface_data_url: str
    hazard_classes_data_url: str
    candidates: list[ShelterCandidateOut]
    total_buildings_in_aoi: int
    excluded_too_small: int = Field(..., description="Real buildings below min_footprint_area_m2 -- not shelter-site candidates at all.")
    excluded_high_hazard: int = Field(..., description="Otherwise-eligible buildings sitting in hazard class 4 or 5 -- excluded, never down-ranked.")
    excluded_no_data: int = Field(..., description="Otherwise-eligible buildings whose location has no hazard-class data (outside the AOI/grid).")
    attribution: list[str]

    @classmethod
    def from_result(cls, result: ShelterIdentificationResult) -> "ShelterIdentificationResponse":
        return cls(
            cache_key=result.cache_key,
            risk_surface_data_url=risk_surface_url(result.cache_key),
            hazard_classes_data_url=hazard_classes_url(result.cache_key),
            candidates=[
                ShelterCandidateOut(
                    geometry=mapping(c.geometry),
                    footprint_area_m2=c.footprint_area_m2,
                    hazard_class=c.hazard_class,
                    hazard_label=c.hazard_label,
                    distance_to_road_m=c.distance_to_road_m,
                    population_density=c.population_density,
                    suitability_score=c.suitability_score,
                    rank=c.rank,
                )
                for c in result.candidates
            ],
            total_buildings_in_aoi=result.total_buildings_in_aoi,
            excluded_too_small=result.excluded_too_small,
            excluded_high_hazard=result.excluded_high_hazard,
            excluded_no_data=result.excluded_no_data,
            attribution=result.attribution,
        )
