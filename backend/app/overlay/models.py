"""Pydantic request/response models for POST /api/overlay/compute and
POST /api/overlay/report.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator
from shapely.geometry import mapping

from app.ahp.models import PairwiseMatrixInput, PairwiseResultOut
from app.common.aoi import AOIInput

from .report import VulnerabilityReport
from .service import OverlayCriterionRequest, OverlayResult
from .sources import SUPPORTED_SOURCES
from .urls import hazard_classes_url, risk_surface_url


class ReclassificationRuleInput(BaseModel):
    min: float | None = None
    max: float | None = None
    min_inclusive: bool = True
    max_inclusive: bool = False
    risk_class: int = Field(..., ge=1, le=5)


class OverlayCriterionInput(BaseModel):
    # Constrained to a safe filename charset: `id` is used to build a
    # per-criterion GeoTIFF filename (report.py's
    # _criterion_raster_tif_path, added alongside per-criterion raster
    # snapshots) -- the first place `id` (previously an arbitrary
    # caller-chosen string) ever lands in a filesystem path, so this
    # closes a real path-traversal surface rather than trusting every
    # caller to send something safe. Doesn't change any real existing
    # behavior: the frontend has only ever sent id == source (a fixed
    # registry name, e.g. "drainage_density"), which already matches.
    id: str = Field(
        ..., pattern=r"^[A-Za-z0-9_-]+$", max_length=64,
        description="Criterion id — must match a key in final_weights. Safe-filename charset only.",
    )
    source: str = Field(
        ..., description=f"Which Phase 2 raster this criterion reclassifies. One of {SUPPORTED_SOURCES!r}."
    )
    reclassification_rules: list[ReclassificationRuleInput] = Field(..., min_length=1)
    stream_threshold_cells: int | None = Field(
        None,
        ge=1,
        description=(
            "Only meaningful for source in {'drainage_density', 'hand'} -- both are measured "
            "against the SAME synthetic stream network (flow_accumulation >= this many upstream "
            "cells), so this is one shared override, not a per-source one. Ignored by every other "
            "source. None (default) falls back to config.DRAINAGE_DENSITY_THRESHOLD_CELLS."
        ),
    )

    def to_domain(self) -> OverlayCriterionRequest:
        return OverlayCriterionRequest(
            id=self.id,
            source=self.source,
            reclassification_rules=[r.model_dump() for r in self.reclassification_rules],
            stream_threshold_cells=self.stream_threshold_cells,
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
    stream_threshold_cells: int | None = Field(
        None,
        ge=1,
        description=(
            "Same meaning as OverlayCriterionInput.stream_threshold_cells -- pass the value a "
            "POST /compute request would use for source in {'drainage_density', 'hand'} so the "
            "returned candidate breaks reflect the actual value distribution that threshold "
            "produces, not always the default's."
        ),
    )


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
    hazard_classes_data_url: str = Field(
        ...,
        description=(
            "GET this path to fetch the discrete 1-5 hazard-class raster as a GeoTIFF (integer GIS "
            "classes, not the continuous [0,1] surface `data_url` serves) — materialized lazily on "
            "first request, straight from the already-cached risk surface; no separate compute step."
        ),
    )
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
            hazard_classes_data_url=hazard_classes_url(result.cache_key),
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


# --- POST /api/overlay/report ---


class ReportCriterionInput(OverlayCriterionInput):
    """Same as OverlayCriterionInput, plus an optional display `name` —
    the backend has no criterion-id -> display-name registry of its own
    (that lives entirely in frontend/src/config/criteria.js today; see
    report.py's own docstring), so the report echoes back whatever the
    caller supplies here rather than inventing one. Defaults to `id`
    itself when omitted, so the report is still complete either way.
    """

    name: str | None = Field(None, description="Display name for the report, e.g. 'Elevation'. Defaults to `id`.")


class ReportWeightingInput(BaseModel):
    method: Literal["equal", "ahp", "manual"] = Field(
        ...,
        description=(
            "How final_weights was derived — purely for the report's display section, never validated "
            "against final_weights itself except when method='ahp' (see consistency_warning). 'manual' "
            "(the frontend's typed-weights mode) is accepted alongside the 'equal'/'ahp' the brief named "
            "explicitly — mislabeling it as 'equal' would misrepresent how the weights were actually "
            "produced, undermining exactly the credibility this feature exists to provide."
        ),
    )
    cluster_comparison: PairwiseMatrixInput | None = Field(
        None, description="Required (and only meaningful) when method='ahp'. Same shape as POST /api/ahp/compute's."
    )
    within_cluster_comparisons: dict[str, PairwiseMatrixInput] | None = Field(
        None, description="Required (and only meaningful) when method='ahp'. Same shape as POST /api/ahp/compute's."
    )

    @model_validator(mode="after")
    def _ahp_requires_matrices(self) -> "ReportWeightingInput":
        if self.method == "ahp" and (self.cluster_comparison is None or self.within_cluster_comparisons is None):
            raise ValueError("weighting.method='ahp' requires both cluster_comparison and within_cluster_comparisons")
        return self


class VulnerabilityReportRequest(BaseModel):
    aoi: AOIInput = Field(..., description="Same AOI a POST /compute request for this result would use.")
    criteria: list[ReportCriterionInput] = Field(..., min_length=1)
    final_weights: dict[str, float] = Field(..., description="Same as POST /compute's final_weights.")
    complete: bool = Field(..., description="Same as POST /compute's complete.")
    weighting: ReportWeightingInput = Field(
        ..., description="How final_weights was derived — display-only, not re-validated against final_weights."
    )
    hybas_id: int | None = Field(
        None, description="HydroBASINS id, if this AOI came from a basin selection (GET /api/basins/{hybas_id})."
    )
    support_status: str | None = Field(
        None, description="That basin's support_status (GET /api/basins/{hybas_id}), if hybas_id is set."
    )


class AOIReportOut(BaseModel):
    bbox: list[float]
    polygon: dict | None = None
    area_km2: float
    hybas_id: int | None = None
    support_status: str | None = None


class CriterionReportOut(BaseModel):
    id: str
    name: str
    source: str
    cluster: str | None = Field(
        None,
        description=(
            "Derived from the AHP breakdown's within_cluster_comparisons when weighting.method='ahp' "
            "(the only place the backend can know a criterion's cluster at all — see report.py's own "
            "docstring). Always null under equal weighting."
        ),
    )
    reclassification_rules: list[dict] = Field(..., description="The actual breaks submitted in THIS request.")
    data_url: str = Field(
        ...,
        description=(
            "GET this path to fetch this criterion's own already-reclassified raster (1-5 GIS "
            "classes, same convention as hazard_classes_data_url) as a standalone GeoTIFF -- "
            "materialized as a side effect of generating THIS report, never by POST /compute alone."
        ),
    )


class ZonalClassStatsOut(BaseModel):
    hazard_class: int = Field(..., ge=1, le=5)
    hazard_label: str
    area_km2: float
    population: float = Field(..., description="Σ(population_density × pixel_area_km²) over this class's pixels.")
    building_count: int


class BuildingFeaturePropertiesOut(BaseModel):
    hazard_class: int | None = Field(
        None, description="1-5, or null if this building's location has no data (outside the AOI/grid)."
    )
    hazard_label: str | None = None


class BuildingFeatureOut(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict
    properties: BuildingFeaturePropertiesOut


class BuildingFeatureCollectionOut(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[BuildingFeatureOut]


class WeightingReportOut(BaseModel):
    method: str
    final_weights: dict[str, float]
    ahp_cluster_comparison: PairwiseResultOut | None = None
    ahp_within_cluster_comparisons: dict[str, PairwiseResultOut] | None = None
    consistency_warning: str | None = Field(
        None,
        description=(
            "Non-null iff weighting.method='ahp' and final_weights doesn't match the weights "
            "recomputed from the submitted pairwise matrices (beyond a small floating-point "
            "tolerance) — a visible flag that the displayed AHP breakdown may not be what actually "
            "produced this risk surface, never a rejection: the surface itself is always computed "
            "from final_weights as submitted, regardless of this check. See report.py's "
            "_weighting_consistency_warning."
        ),
    )


class VulnerabilityReportResponse(BaseModel):
    cache_key: str = Field(..., description="Same cache_key POST /compute would return for these same inputs.")
    generated_at: str = Field(..., description="ISO-8601 UTC timestamp of when this report was assembled.")
    risk_surface_data_url: str
    hazard_classes_data_url: str
    aoi: AOIReportOut
    criteria: list[CriterionReportOut] = Field(
        ...,
        description=(
            "One entry per submitted criterion, whatever that count happens to be — this report is "
            "fully generic over the registered criterion sources, never a fixed/assumed set."
        ),
    )
    weighting: WeightingReportOut
    zonal_stats: list[ZonalClassStatsOut] = Field(
        ..., min_length=5, max_length=5, description="Always all 5 hazard classes, zero-filled if empty in this AOI."
    )
    buildings: BuildingFeatureCollectionOut
    total_buildings: int
    total_population: float
    total_area_km2: float
    high_risk_building_count: int = Field(..., description="Buildings in hazard classes 4 (High) + 5 (Very High).")
    high_risk_building_pct: float
    high_risk_population: float = Field(..., description="Population in hazard classes 4 (High) + 5 (Very High).")
    high_risk_population_pct: float
    attribution: list[str]

    @classmethod
    def from_report(cls, report: VulnerabilityReport) -> "VulnerabilityReportResponse":
        ahp = report.weighting.ahp
        return cls(
            cache_key=report.cache_key,
            generated_at=report.generated_at,
            risk_surface_data_url=risk_surface_url(report.cache_key),
            hazard_classes_data_url=hazard_classes_url(report.cache_key),
            aoi=AOIReportOut(
                bbox=list(report.aoi.bbox_4326),
                polygon=report.aoi.polygon_geojson,
                area_km2=report.aoi.area_km2,
                hybas_id=report.aoi.hybas_id,
                support_status=report.aoi.support_status,
            ),
            criteria=[
                CriterionReportOut(
                    id=c.id, name=c.name, source=c.source, cluster=c.cluster,
                    reclassification_rules=c.reclassification_rules, data_url=c.data_url,
                )
                for c in report.criteria
            ],
            weighting=WeightingReportOut(
                method=report.weighting.method,
                final_weights=report.weighting.final_weights,
                ahp_cluster_comparison=PairwiseResultOut.from_result(ahp.cluster_comparison) if ahp else None,
                ahp_within_cluster_comparisons=(
                    {name: PairwiseResultOut.from_result(r) for name, r in ahp.within_cluster_comparisons.items()}
                    if ahp else None
                ),
                consistency_warning=report.weighting.consistency_warning,
            ),
            zonal_stats=[
                ZonalClassStatsOut(
                    hazard_class=s.hazard_class, hazard_label=s.hazard_label,
                    area_km2=s.area_km2, population=s.population, building_count=s.building_count,
                )
                for s in report.zonal_stats
            ],
            buildings=BuildingFeatureCollectionOut(
                features=[
                    BuildingFeatureOut(
                        geometry=mapping(b.geometry),
                        properties=BuildingFeaturePropertiesOut(hazard_class=b.hazard_class, hazard_label=b.hazard_label),
                    )
                    for b in report.buildings
                ]
            ),
            total_buildings=report.total_buildings,
            total_population=report.total_population,
            total_area_km2=report.total_area_km2,
            high_risk_building_count=report.high_risk_building_count,
            high_risk_building_pct=report.high_risk_building_pct,
            high_risk_population=report.high_risk_population,
            high_risk_population_pct=report.high_risk_population_pct,
            attribution=report.attribution,
        )
