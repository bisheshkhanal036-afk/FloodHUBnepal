"""Shelter-site identification, built on top of the vulnerability-
classification feature's own already-computed pieces (hazard_classes.py,
building_classification.py's majority-overlap machinery) plus
app/data/distance_raster.py and app/data/population.py.

Given a risk surface (the same aoi/criteria/final_weights/complete
inputs POST /compute and POST /report already take), ranks real OSM
building footprints in the AOI as candidate emergency-shelter SITES by
multi-criteria suitability:

  - safety     -- the building's own hazard class (1-5, majority-overlap
                  sampled exactly like building_classification.py); any
                  candidate in HIGH_RISK_CLASSES (4-5) is excluded
                  outright, never merely down-ranked, since a site that
                  is itself in the high/very-high hazard zone cannot be
                  a safe shelter regardless of how it scores otherwise.
  - accessibility -- distance to the nearest road (app/data/
                  distance_raster.py's dist_to_road machinery, reused
                  directly rather than re-rasterizing the road network a
                  second time), closer is better: an inaccessible
                  building is a poor shelter even if it sits on
                  perfectly safe ground.
  - service value -- local population density at the site (people/km^2,
                  app/data/population.py), higher is better: a shelter
                  should be reachable by the people it's meant to serve.

Scope, deliberately: this identifies SUITABLE SITES from the AOI's
existing building stock, not existing tagged emergency shelters or
shelter-TYPE buildings (schools, hospitals, etc.) specifically. The
buildings dataset this project already has (app/data/osm.py's
get_osm_features) is geometry-only -- no amenity/building=school|
hospital|community_centre tag survives through the FlatGeobuf extract
pipeline this project's OSM tier already uses (see osm.py's own
docstring on why buildings.fgb is geometry-only) -- adding amenity-
based shelter-type filtering would need a new data-engineering pass
over the raw .pbf/shapefile export, not something this pass could
verify live against real data. Instead, SHELTER_MIN_FOOTPRINT_AREA_M2
(config.py) is used as a size proxy: a real building large enough to
plausibly be an institutional structure (school, community hall) is a
legitimate site-suitability signal on its own, standard practice for
GIS shelter-siting when building-type attribution isn't available --
but this is a site-suitability ranking, not a shelter-type
classification, and is documented as such so it's never mistaken for
"these ARE existing shelters."

Suitability score: each of the three factors is min-max normalized
across THIS AOI's own surviving candidates (0=worst, 1=best) and
combined via a simple, deliberately transparent weighted mean (equal
thirds by default, all three weights caller-overridable) -- NOT the
fixed-range [1,5]-scale normalization RiskSurface.value_range uses
(SPEC.md §3.4). That fixed-range convention exists specifically so a
stored, cacheable, cross-AOI-comparable hazard SCORE means the same
thing everywhere; a shelter ranking is inherently a within-AOI
comparison (which of THESE buildings, in THIS area, is the better
choice) with no cross-AOI comparability claim to protect, so ordinary
min-max normalization is the right tool here, not a violation of that
convention.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from rasterio.transform import rowcol

from app.data import config
from app.data.aoi import AOI
from app.data.distance_raster import compute_distance_raster
from app.data.osm import get_osm_features
from app.data.population import get_population

from .building_classification import classify_buildings
from .hazard_classes import HAZARD_CLASS_LABELS, HIGH_RISK_CLASSES, risk_surface_to_hazard_classes
from .service import OverlayCriterionRequest, compute_overlay


@dataclass(frozen=True)
class ShelterCandidate:
    geometry: object  # shapely geometry, in the buildings source's own original CRS (EPSG:4326 in production)
    footprint_area_m2: float
    hazard_class: int
    hazard_label: str
    distance_to_road_m: float | None  # None only if the AOI has zero roads at all (DISTANCE_RASTER_NODATA)
    population_density: float | None  # people/km^2 at the site; None if population has no data there
    suitability_score: float  # 0-1, min-max normalized within this AOI's own surviving candidates -- see module docstring
    rank: int  # 1 = best, contiguous, no gaps


@dataclass(frozen=True)
class ShelterIdentificationResult:
    cache_key: str
    candidates: list[ShelterCandidate]
    total_buildings_in_aoi: int
    excluded_too_small: int
    excluded_high_hazard: int
    excluded_no_data: int
    attribution: list[str]


def _sample_at_point(array: np.ndarray, transform, nodata: float | None, x: float, y: float) -> float | None:
    height, width = array.shape
    row, col = rowcol(transform, x, y)
    if not (0 <= row < height and 0 <= col < width):
        return None
    value = float(array[row, col])
    if nodata is not None and value == nodata:
        return None
    return value


def _min_max_normalize(values: list[float | None], *, higher_is_better: bool) -> list[float]:
    """0-1 min-max normalization over only the non-None values; a None
    (missing data at that candidate's own location) is scored at the
    midpoint (0.5) rather than excluded from ranking entirely or
    silently treated as the worst/best case -- a candidate shouldn't be
    penalized or favored just because, say, the population raster has a
    coverage gap at its exact centroid (SPEC.md §3.6 already documents
    real coverage gaps for several sources this project uses).
    """
    present = [v for v in values if v is not None]
    if not present or max(present) == min(present):
        # No discriminating signal either way (nothing present, or every
        # present value is identical) -- 0.5 for everyone, same as the
        # missing-data case, not 1.0: there's nothing here that actually
        # makes one candidate better than another on this factor.
        return [0.5 for _ in values]
    lo, hi = min(present), max(present)
    span = hi - lo

    def _score(v: float) -> float:
        normalized = (v - lo) / span
        return normalized if higher_is_better else 1.0 - normalized

    return [0.5 if v is None else _score(v) for v in values]


def identify_shelter_sites(
    aoi: AOI,
    criteria: list[OverlayCriterionRequest],
    final_weights: dict[str, float],
    complete: bool,
    *,
    min_footprint_area_m2: float | None = None,
    top_n: int | None = None,
    safety_weight: float = 1.0,
    accessibility_weight: float = 1.0,
    service_weight: float = 1.0,
) -> ShelterIdentificationResult:
    """Reuses compute_overlay's own risk-surface cache untouched (same
    role report.py's compute_vulnerability_report already plays: a call
    here for already-computed aoi/criteria/final_weights/complete is a
    cache HIT there, not a recompute) -- so a caller that already ran
    POST /compute or POST /report for this exact combination pays no
    extra risk-surface cost calling this too.
    """
    min_footprint_area_m2 = (
        min_footprint_area_m2 if min_footprint_area_m2 is not None else config.SHELTER_MIN_FOOTPRINT_AREA_M2
    )
    top_n = top_n if top_n is not None else config.SHELTER_DEFAULT_TOP_N

    overlay_result = compute_overlay(aoi, criteria, final_weights, complete)
    grid = overlay_result.risk_surface.grid
    hazard_class_raster = risk_surface_to_hazard_classes(
        overlay_result.risk_surface.risk_surface, overlay_result.risk_surface.nodata
    )

    buildings_gdf = get_osm_features(aoi).buildings
    total_buildings_in_aoi = len(buildings_gdf)

    if total_buildings_in_aoi == 0:
        return ShelterIdentificationResult(
            cache_key=overlay_result.cache_key,
            candidates=[],
            total_buildings_in_aoi=0,
            excluded_too_small=0,
            excluded_high_hazard=0,
            excluded_no_data=0,
            attribution=overlay_result.attribution,
        )

    # Footprint area is computed on the UTM-projected geometry, never
    # raw EPSG:4326 degrees -- SPEC.md §2.1's CRS convention applies to
    # this area computation exactly as much as it does to AOI.area_km2.
    buildings_utm = buildings_gdf.to_crs(grid.crs) if str(buildings_gdf.crs) != grid.crs else buildings_gdf
    footprint_area_m2 = buildings_utm.geometry.area.to_numpy()
    large_enough = footprint_area_m2 >= min_footprint_area_m2
    excluded_too_small = int((~large_enough).sum())

    candidate_gdf = buildings_gdf.loc[large_enough].reset_index(drop=True)
    candidate_areas = footprint_area_m2[large_enough]
    candidate_utm = buildings_utm.loc[large_enough].reset_index(drop=True)

    if len(candidate_gdf) == 0:
        return ShelterIdentificationResult(
            cache_key=overlay_result.cache_key,
            candidates=[],
            total_buildings_in_aoi=total_buildings_in_aoi,
            excluded_too_small=excluded_too_small,
            excluded_high_hazard=0,
            excluded_no_data=0,
            attribution=overlay_result.attribution,
        )

    # Majority-overlap hazard-class sampling -- the exact same rule/
    # implementation building_classification.py's report-facing
    # classify_buildings already uses, reused rather than reimplemented
    # so the two features can never disagree about a building's own
    # hazard class.
    classified = classify_buildings(candidate_gdf, grid, hazard_class_raster)

    road_distance = compute_distance_raster(get_osm_features(aoi).roads, grid)
    population_result = get_population(aoi)

    kept_indices: list[int] = []
    excluded_high_hazard = 0
    excluded_no_data = 0
    distances: list[float | None] = []
    densities: list[float | None] = []

    for i, classified_building in enumerate(classified):
        hazard_class = classified_building.hazard_class
        if hazard_class is None:
            excluded_no_data += 1
            continue
        if hazard_class in HIGH_RISK_CLASSES:
            excluded_high_hazard += 1
            continue

        centroid = candidate_utm.geometry.iloc[i].centroid
        distance_m = _sample_at_point(road_distance, grid.transform, None, centroid.x, centroid.y)
        # DISTANCE_RASTER_NODATA (-1.0, see distance_raster.py) means
        # "this AOI has zero road features at all" -- treated as unknown
        # accessibility (None), not as "distance 0" or excluded outright.
        if distance_m is not None and distance_m < 0:
            distance_m = None
        density = _sample_at_point(
            population_result.density, grid.transform, population_result.nodata, centroid.x, centroid.y
        )

        kept_indices.append(i)
        distances.append(distance_m)
        densities.append(density)

    if not kept_indices:
        return ShelterIdentificationResult(
            cache_key=overlay_result.cache_key,
            candidates=[],
            total_buildings_in_aoi=total_buildings_in_aoi,
            excluded_too_small=excluded_too_small,
            excluded_high_hazard=excluded_high_hazard,
            excluded_no_data=excluded_no_data,
            attribution=overlay_result.attribution,
        )

    safety_scores = [1.0 - (classified[i].hazard_class - 1) / 4.0 for i in kept_indices]  # class 1 -> 1.0, class 3 -> ~0.5
    accessibility_scores = _min_max_normalize(distances, higher_is_better=False)
    service_scores = _min_max_normalize(densities, higher_is_better=True)

    total_weight = safety_weight + accessibility_weight + service_weight
    if total_weight <= 0:
        raise ValueError("At least one of safety_weight/accessibility_weight/service_weight must be positive")

    scored: list[tuple[float, int, int]] = []  # (score, position in kept_indices, original candidate index)
    for pos, i in enumerate(kept_indices):
        score = (
            safety_weight * safety_scores[pos]
            + accessibility_weight * accessibility_scores[pos]
            + service_weight * service_scores[pos]
        ) / total_weight
        scored.append((score, pos, i))

    scored.sort(key=lambda t: t[0], reverse=True)

    candidates: list[ShelterCandidate] = []
    for rank, (score, pos, i) in enumerate(scored[:top_n], start=1):
        hazard_class = classified[i].hazard_class
        candidates.append(
            ShelterCandidate(
                geometry=classified[i].geometry,
                footprint_area_m2=float(candidate_areas[i]),
                hazard_class=hazard_class,
                hazard_label=HAZARD_CLASS_LABELS[hazard_class],
                distance_to_road_m=distances[pos],
                population_density=densities[pos],
                suitability_score=score,
                rank=rank,
            )
        )

    return ShelterIdentificationResult(
        cache_key=overlay_result.cache_key,
        candidates=candidates,
        total_buildings_in_aoi=total_buildings_in_aoi,
        excluded_too_small=excluded_too_small,
        excluded_high_hazard=excluded_high_hazard,
        excluded_no_data=excluded_no_data,
        attribution=overlay_result.attribution,
    )


__all__ = ["ShelterCandidate", "ShelterIdentificationResult", "identify_shelter_sites"]
