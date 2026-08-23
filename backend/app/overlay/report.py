"""Part 4 of the vulnerability-classification feature: assembles the full
computation report on top of Parts 1-3 (hazard_classes.py,
building_classification.py, zonal_stats.py) plus the AOI/criteria/
weighting context a report needs but the base overlay engine doesn't
carry at all.

Orchestration layer, same role for this feature that service.py plays
for the base risk surface -- plain dataclasses in/out, no Pydantic here
(that's models.py's job at the API boundary), no I/O beyond what the
functions it calls already do.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.ahp.hierarchy import HierarchyResult, compute_hierarchy
from app.data import config
from app.data.aoi import AOI
from app.data.cache import cached_or_compute
from app.data.osm import get_osm_features
from app.data.population import get_population
from app.data.reclassify import RECLASSIFIED_NODATA

from .building_classification import ClassifiedBuilding, classify_buildings
from .compute import _mask_array_to_polygon
from .errors import OverlayValidationError
from .geotiff import write_hazard_class_geotiff
from .hazard_classes import risk_surface_to_hazard_classes
from .service import OverlayCriterionRequest, OverlayResult, compute_overlay
from .urls import criterion_raster_url
from .zonal_stats import ZonalClassStats, compute_zonal_stats

# Hazard classes 4 (High) and 5 (Very High) -- the Siraha-style paper's
# own headline figure ("buildings/population in high + very-high zones").
HIGH_RISK_CLASSES = (4, 5)


@dataclass(frozen=True)
class AOIReportInfo:
    bbox_4326: tuple[float, float, float, float]
    polygon_geojson: dict | None
    area_km2: float
    hybas_id: int | None
    support_status: str | None


@dataclass(frozen=True)
class CriterionReportInfo:
    id: str
    name: str
    source: str
    cluster: str | None
    reclassification_rules: list[dict]
    # Per-criterion raster snapshot -- see _materialize_criterion_rasters.
    # Deliberately only ever populated here, never on POST /compute's own
    # response: "see the individual layers" is gated behind actually
    # asking for the vulnerability report, by explicit user request, not
    # just a UI-layer convention -- the file itself doesn't exist on disk
    # until this function writes it.
    data_url: str


# Tolerance for the final_weights-vs-recomputed-AHP-breakdown consistency
# check below -- matches this codebase's existing convention for a
# floating-point weight-equality tolerance (compute.py's own
# _WEIGHT_SUM_TOLERANCE, ahp/constants.py's VALIDATION_TOLERANCE), not a
# new number invented for this check alone.
WEIGHT_CONSISTENCY_TOLERANCE = 1e-6


@dataclass(frozen=True)
class WeightingReportInfo:
    method: str  # "equal" | "ahp"
    final_weights: dict[str, float]
    ahp: HierarchyResult | None  # None unless method == "ahp"
    consistency_warning: str | None  # see _weighting_consistency_warning


@dataclass(frozen=True)
class VulnerabilityReportCore:
    """The expensive, AOI/criteria/weight-derived part of the report --
    cached under the SAME cache_key compute_overlay's own risk_surface
    cache uses (see report()'s own docstring for why that's correct: the
    hazard classes / classified buildings / zonal stats depend on
    exactly what determines that cache_key already, nothing else).
    """

    hazard_class_raster_shape: tuple[int, int]
    zonal_stats: list[ZonalClassStats]
    buildings: list[ClassifiedBuilding]


@dataclass(frozen=True)
class VulnerabilityReport:
    cache_key: str
    generated_at: str
    aoi: AOIReportInfo
    criteria: list[CriterionReportInfo]
    weighting: WeightingReportInfo
    zonal_stats: list[ZonalClassStats]
    buildings: list[ClassifiedBuilding]
    total_buildings: int
    total_population: float
    total_area_km2: float
    high_risk_building_count: int
    high_risk_building_pct: float
    high_risk_population: float
    high_risk_population_pct: float
    attribution: list[str]


def _cluster_for_criterion(criterion_id: str, ahp: HierarchyResult | None) -> str | None:
    """Derived from the AHP breakdown's own within_cluster_comparisons
    (each cluster's `items` list names the criterion ids it compares) --
    the only place a criterion's cluster is knowable at all on the
    backend when weighting.method == "ahp" (app/ahp/constants.py only
    has the 5 canonical cluster NAMES, no criterion_id -> cluster
    mapping; that mapping lives entirely in frontend/src/config/
    criteria.js today). None for "equal" weighting (no AHP breakdown to
    derive it from) or a criterion this AHP breakdown never mentions.
    """
    if ahp is None:
        return None
    for cluster_name, result in ahp.within_cluster_comparisons.items():
        if criterion_id in result.items:
            return cluster_name
    return None


def _weighting_consistency_warning(final_weights: dict[str, float], ahp: HierarchyResult | None) -> str | None:
    """The report displays BOTH the weights that actually produced the
    risk surface (final_weights, trusted as-is for the computation
    itself, exactly like POST /compute already trusts it) AND a freshly
    recomputed AHP breakdown (eigenvector weights, consistency ratios,
    worst pairs) derived independently from the submitted pairwise
    matrices. Nothing forces these two to agree — a caller could submit
    final_weights left over from an earlier AHP run alongside newly
    edited pairwise matrices, or a bug/version-mismatch on the caller's
    own side. A SILENT mismatch there would undermine exactly the
    credibility this feature exists to provide (a report whose weighting
    section quietly doesn't explain its own risk surface), so this is a
    cheap, deliberate cross-check -- not required to match (never raises;
    the risk surface computation itself is unaffected either way), but
    surfaced as a visible warning if it doesn't. None for "equal"
    weighting (nothing to cross-check against) or a clean match within
    WEIGHT_CONSISTENCY_TOLERANCE.
    """
    if ahp is None:
        return None
    recomputed = ahp.final_weights

    if set(recomputed) != set(final_weights):
        missing = sorted(set(final_weights) - set(recomputed))
        extra = sorted(set(recomputed) - set(final_weights))
        return (
            "final_weights and the AHP breakdown recomputed from the submitted pairwise matrices "
            f"cover different criteria (in final_weights but not the AHP breakdown: {missing}; "
            f"in the AHP breakdown but not final_weights: {extra}) -- the weighting section shown "
            "may not fully explain the risk surface actually computed."
        )

    # Renormalize `recomputed` over its own total before comparing --
    # mirrors the frontend's own AHP-mode final_weights derivation
    # (frontend/src/state/AppStateContext.jsx's useFinalWeights): when
    # not every canonical cluster has a selected criterion (a normal,
    # explicitly-supported case -- see config/criteria.js's note on
    # Exposure sometimes being empty), the top-level cluster comparison
    # "spends" some weight mass on a cluster with nothing to receive it,
    # so raw cluster_weight * within_weight restricted to only the
    # selected criteria doesn't sum to 1 on its own. The frontend
    # renormalizes over just those criteria to recover a valid, complete
    # weight set before ever submitting to POST /compute (compute_
    # risk_surface requires an exact sum of 1), preserving the AHP-
    # computed relative PROPORTIONS among what's selected. Comparing
    # raw, unnormalized `recomputed` values here would flag that
    # everyday case as a false "mismatch" every time. When every cluster
    # IS covered, raw `recomputed` already sums to ~1 and this is a
    # no-op (dividing by ~1 changes nothing) -- one formula, correct
    # either way.
    total = sum(recomputed.values())
    if total <= 0:
        return None  # degenerate (all-zero) AHP result -- nothing meaningful to compare
    normalized_recomputed = {cid: w / total for cid, w in recomputed.items()}

    diffs = {cid: abs(final_weights[cid] - normalized_recomputed[cid]) for cid in final_weights}
    max_diff = max(diffs.values(), default=0.0)
    if max_diff > WEIGHT_CONSISTENCY_TOLERANCE:
        worst = max(diffs, key=diffs.get)
        return (
            f"final_weights does not match the weights recomputed from the submitted AHP pairwise "
            f"matrices (largest discrepancy: criterion {worst!r}, submitted={final_weights[worst]:.6f} "
            f"vs recomputed={normalized_recomputed[worst]:.6f}) -- the risk surface was computed with "
            "final_weights as submitted, but the AHP breakdown shown may not be what actually "
            "produced it."
        )
    return None


def _criterion_raster_tif_path(cache_key: str, criterion_id: str) -> Path:
    # config.PROCESSED_CACHE_DIR read dynamically at call time (not
    # imported by value), same convention every other module in this
    # feature already follows, so tests can monkeypatch it.
    return config.PROCESSED_CACHE_DIR / "criterion_rasters" / f"{cache_key}_{criterion_id}.tif"


def _materialize_criterion_rasters(overlay_result: OverlayResult, cache_key: str, aoi: AOI) -> dict[str, str]:
    """Writes each of `overlay_result.criterion_rasters` to its own
    GeoTIFF, if not already on disk, and returns {criterion_id:
    data_url}. This is the ONLY place these files ever get written --
    POST /compute never calls this -- which is what actually enforces
    "snapshots only after the report", not a UI-layer convention: the
    bytes simply don't exist until a report is generated for this
    cache_key.

    Reuses write_hazard_class_geotiff (overlay/geotiff.py) as-is rather
    than a new writer: a reclassified criterion raster (uint8, values
    1-5, RECLASSIFIED_NODATA=0) is byte-for-byte the same shape/dtype/
    nodata convention as a hazard-class raster.

    Masks to the AOI's true polygon shape when set (a basin selection),
    via the same _mask_array_to_polygon core
    mask_risk_surface_to_polygon already uses for the combined surface
    -- otherwise a basin AOI's per-criterion snapshot would show the
    full rectangular bounding envelope while the combined result (which
    IS already masked) shows the real basin shape, an inconsistency a
    user comparing the two side by side would notice immediately.

    Same `if not path.exists(): write(...)` short-circuit service.py's
    own risk-surface materialization already uses -- a second report
    request for the same cache_key is a no-op here, not a rewrite.
    """
    urls: dict[str, str] = {}
    for criterion_raster in overlay_result.criterion_rasters:
        path = _criterion_raster_tif_path(cache_key, criterion_raster.criterion_id)
        if not path.exists():
            array = criterion_raster.reclassified
            if aoi.polygon is not None:
                array = _mask_array_to_polygon(array, criterion_raster.grid, RECLASSIFIED_NODATA, aoi.polygon_utm)
            write_hazard_class_geotiff(path, array, criterion_raster.grid, RECLASSIFIED_NODATA)
        urls[criterion_raster.criterion_id] = criterion_raster_url(cache_key, criterion_raster.criterion_id)
    return urls


def compute_vulnerability_report(
    aoi: AOI,
    criteria: list[OverlayCriterionRequest],
    final_weights: dict[str, float],
    complete: bool,
    *,
    criterion_names: dict[str, str] | None = None,
    weighting_method: str = "equal",
    ahp_cluster_comparison: dict | None = None,
    ahp_within_cluster_comparisons: dict[str, dict] | None = None,
    hybas_id: int | None = None,
    support_status: str | None = None,
) -> VulnerabilityReport:
    """The full pipeline: resolve/cache the risk surface (reusing
    compute_overlay's own cache untouched -- a report request for
    already-computed params is a cache HIT there, not a recompute),
    derive discrete hazard classes, classify buildings, compute zonal
    stats, and assemble everything alongside the AOI/criteria/weighting
    context into one report.

    `weighting_method` "ahp" requires both `ahp_cluster_comparison` and
    `ahp_within_cluster_comparisons` (same raw-matrix shape
    app.ahp.hierarchy.compute_hierarchy already takes) -- recomputed
    fresh here via that same trusted function, not re-derived from
    `final_weights` alone, so the report's AHP section (eigenvector
    weights, consistency ratios, worst pairs) is never a guess. Raises
    AHPValidationError/AHPConsistencyError exactly as
    POST /api/ahp/compute would for a bad/inconsistent matrix -- the
    caller's responsibility to submit the SAME matrices that produced
    `final_weights` in the first place; this function does not cross-
    check the two against each other (the same trust model
    POST /overlay/compute already has for final_weights vs criteria).
    """
    overlay_result = compute_overlay(aoi, criteria, final_weights, complete)
    cache_key = overlay_result.cache_key
    criterion_raster_urls = _materialize_criterion_rasters(overlay_result, cache_key, aoi)

    ahp_result: HierarchyResult | None = None
    if weighting_method == "ahp":
        if ahp_cluster_comparison is None or ahp_within_cluster_comparisons is None:
            raise OverlayValidationError(
                "weighting_method='ahp' requires both ahp_cluster_comparison and "
                "ahp_within_cluster_comparisons"
            )
        ahp_result = compute_hierarchy(ahp_cluster_comparison, ahp_within_cluster_comparisons)

    def _compute_core() -> VulnerabilityReportCore:
        grid = overlay_result.risk_surface.grid
        hazard_class_raster = risk_surface_to_hazard_classes(
            overlay_result.risk_surface.risk_surface, overlay_result.risk_surface.nodata
        )
        buildings_gdf = get_osm_features(aoi).buildings
        classified = classify_buildings(buildings_gdf, grid, hazard_class_raster)

        population_result = get_population(aoi)
        zonal = compute_zonal_stats(
            hazard_class_raster, grid, population_result.density, population_result.nodata, classified
        )
        return VulnerabilityReportCore(
            hazard_class_raster_shape=hazard_class_raster.shape, zonal_stats=zonal, buildings=classified
        )

    core = cached_or_compute("vulnerability_report_core", aoi, _compute_core, version=cache_key)

    criterion_names = criterion_names or {}
    criteria_info = [
        CriterionReportInfo(
            id=c.id,
            name=criterion_names.get(c.id, c.id),
            source=c.source,
            cluster=_cluster_for_criterion(c.id, ahp_result),
            reclassification_rules=c.reclassification_rules,
            data_url=criterion_raster_urls[c.id],
        )
        for c in criteria
    ]

    total_buildings = sum(1 for b in core.buildings if b.hazard_class is not None)
    total_population = sum(s.population for s in core.zonal_stats)
    total_area_km2 = sum(s.area_km2 for s in core.zonal_stats)
    high_risk_buildings = sum(s.building_count for s in core.zonal_stats if s.hazard_class in HIGH_RISK_CLASSES)
    high_risk_population = sum(s.population for s in core.zonal_stats if s.hazard_class in HIGH_RISK_CLASSES)

    return VulnerabilityReport(
        cache_key=cache_key,
        generated_at=datetime.now(timezone.utc).isoformat(),
        aoi=AOIReportInfo(
            bbox_4326=aoi.bbox_4326,
            polygon_geojson=_polygon_geojson(aoi),
            area_km2=aoi.area_km2,
            hybas_id=hybas_id,
            support_status=support_status,
        ),
        criteria=criteria_info,
        weighting=WeightingReportInfo(
            method=weighting_method,
            final_weights=final_weights,
            ahp=ahp_result,
            consistency_warning=_weighting_consistency_warning(final_weights, ahp_result),
        ),
        zonal_stats=core.zonal_stats,
        buildings=core.buildings,
        total_buildings=total_buildings,
        total_population=total_population,
        total_area_km2=total_area_km2,
        high_risk_building_count=high_risk_buildings,
        high_risk_building_pct=(100.0 * high_risk_buildings / total_buildings) if total_buildings else 0.0,
        high_risk_population=high_risk_population,
        high_risk_population_pct=(100.0 * high_risk_population / total_population) if total_population else 0.0,
        attribution=overlay_result.attribution,
    )


def _polygon_geojson(aoi: AOI) -> dict | None:
    if aoi.polygon is None:
        return None
    from shapely.geometry import mapping

    return mapping(aoi.polygon)
