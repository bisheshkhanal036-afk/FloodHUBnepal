"""Pydantic request/response models for POST /api/overlay/compute."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.common.aoi import AOIInput

from .service import OverlayCriterionRequest, OverlayResult
from .sources import SUPPORTED_SOURCES
from .urls import risk_surface_url


class ReclassificationRuleInput(BaseModel):
    min: float | None = None
    max: float | None = None
    min_inclusive: bool = True
    max_inclusive: bool = False
    risk_class: int = Field(..., ge=1, le=5)


class OverlayCriterionInput(BaseModel):
    id: str = Field(..., description="Criterion id — must match a key in final_weights.")
    source: str = Field(
        ..., description=f"Which Phase 2 raster this criterion reclassifies. One of {SUPPORTED_SOURCES!r}."
    )
    reclassification_rules: list[ReclassificationRuleInput] = Field(..., min_length=1)

    def to_domain(self) -> OverlayCriterionRequest:
        return OverlayCriterionRequest(
            id=self.id,
            source=self.source,
            reclassification_rules=[r.model_dump() for r in self.reclassification_rules],
        )


class OverlayComputeRequest(BaseModel):
    aoi: AOIInput = Field(
        ...,
        description=(
            "Rejected with 422 if a plain bbox-only AOI's area exceeds the shared 1000 km² cap "
            "— an AOI with a true `polygon` (e.g. a basin selection) is exempt from that cap."
        ),
    )
    criteria: list[OverlayCriterionInput] = Field(..., min_length=1)
    final_weights: dict[str, float] = Field(
        ..., description="Phase 1's AHPComputeResponse.final_weights — criterion_id -> weight."
    )
    complete: bool = Field(
        ...,
        description=(
            "Phase 1's AHPComputeResponse.complete. Must be True — the overlay engine rejects "
            "an incomplete weight set rather than computing on non-normalized weights."
        ),
    )


class CriterionBreaksRequest(BaseModel):
    aoi: AOIInput = Field(..., description="Same AOI a POST /compute request for this criterion would use.")
    source: str = Field(..., description=f"Which criterion source to classify. One of {SUPPORTED_SOURCES!r}.")


class CriterionBreaksResponse(BaseModel):
    min: float = Field(..., description="Smallest valid (non-nodata) raw value found for this source over this AOI.")
    max: float = Field(..., description="Largest valid (non-nodata) raw value found for this source over this AOI.")
    valid_pixel_count: int
    equal_interval: list[float] = Field(..., min_length=4, max_length=4, description="4 interior breaks (5 equal-width classes).")
    quantile: list[float] = Field(..., min_length=4, max_length=4, description="4 interior breaks (5 equal-count classes).")
    jenks: list[float] = Field(
        ..., min_length=4, max_length=4, description="4 interior breaks (Fisher-Jenks natural breaks, 5 classes)."
    )


class GridOut(BaseModel):
    crs: str
    resolution_m: float
    origin_x: float
    origin_y: float
    width: int
    height: int


class SourceWarningOut(BaseModel):
    criterion_id: str = Field(..., description="Which criterion (by id) this warning applies to.")
    message: str = Field(..., description="Human-readable caveat about that criterion's result quality.")


class OverlayComputeResponse(BaseModel):
    cache_key: str = Field(..., description="Matches schemas/risk_surface.schema.json's cache_key.")
    data_url: str = Field(..., description="GET this path to fetch the risk surface as a GeoTIFF.")
    grid: GridOut
    nodata_value: float
    value_range: tuple[float, float] = (0.0, 1.0)
    attribution: list[str] = Field(..., description="Deduplicated attribution strings from every contributing source.")
    source_warnings: list[SourceWarningOut] = Field(
        default_factory=list,
        description=(
            "Per-criterion caveats about result quality, from sources that flag one (e.g. twi/"
            "drainage_density computed over a plain bbox AOI rather than a basin's true watershed "
            "boundary — see SPEC.md §3.6). Empty when no contributing source has anything to flag; "
            "distinct from `attribution`, which is always the plain, unmodified source citation."
        ),
    )

    @classmethod
    def from_overlay_result(cls, result: OverlayResult) -> "OverlayComputeResponse":
        grid = result.risk_surface.grid
        return cls(
            cache_key=result.cache_key,
            data_url=risk_surface_url(result.cache_key),
            grid=GridOut(
                crs=grid.crs,
                resolution_m=grid.resolution_m,
                origin_x=grid.origin_x,
                origin_y=grid.origin_y,
                width=grid.width,
                height=grid.height,
            ),
            nodata_value=result.risk_surface.nodata,
            attribution=result.attribution,
            source_warnings=[
                SourceWarningOut(criterion_id=w.criterion_id, message=w.message) for w in result.source_warnings
            ],
        )
