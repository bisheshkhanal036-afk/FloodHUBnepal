"""Generic local coverage-density raster on the common per-AOI grid, plus
the building_density criterion source built on it
(app/overlay/sources.py's `building_density` registration) — Exposure
cluster's first criterion (§3.6/SPEC.md; previously empty, since none of
the other 7 sources represents what's *at risk*, only the hazard's own
physical behavior).

compute_density_raster() itself is not building-specific — it takes an
arbitrary GeoDataFrame of polygon (or line/point) features and an
AOIGrid, so a future "density of X" criterion (e.g. road density) can
reuse it directly, the same way distance_raster.py's
compute_distance_raster() is already shared by dist_to_river/dist_to_road.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
from rasterio.features import rasterize

from . import config
from .aoi import AOI
from .attribution import OSM_ATTRIBUTION
from .cache import cached_or_compute
from .grid import AOIGrid, compute_aoi_grid
from .osm import get_osm_features


def compute_density_raster(features: gpd.GeoDataFrame, grid: AOIGrid, window_radius_m: float) -> np.ndarray:
    """For each grid cell, the fraction (0-1) of a circular window of
    `window_radius_m` around it that `features` covers — a local
    coverage-density surface, not a single AOI-wide scalar, so it can
    serve as a per-pixel AHP criterion like every other source here.

    Implementation: rasterizes `features` onto `grid` into a binary
    coverage mask, `all_touched=False` (deliberately different from
    distance_raster.py's `all_touched=True`: that's needed there so a
    thin *line* feature is never missed entirely by a distance
    transform; here, for *area* coverage, all_touched=True would
    systematically overstate density by counting a pixel as "covered"
    just because a polygon edge clips its corner) — then runs a
    circular-kernel moving-window mean of that mask via convolution
    (moving_window.py, shared with hydrology.py's drainage-density
    line-density transform -- this is that same construction,
    generalized from line length to area coverage).

    The window's own cell count (the density's denominator) is the
    kernel's full size, not however many of its cells actually landed
    inside the AOI — so, like every other edge-dependent raster in this
    layer (dem.py's Horn's-method slope, hydrology.py's drainage
    density), density is systematically *underestimated* within
    `window_radius_m` of the AOI's own edge, since there's no way to
    know what's just outside it. A known, documented limitation, not a
    bug.

    Unlike compute_distance_raster, there is no "undefined" case here to
    flag with a nodata sentinel: an AOI with zero matching features is
    legitimately all-zero density, not missing data (get_osm_features
    itself is what raises if the underlying source is unavailable).
    """
    from .moving_window import circular_kernel, circular_window_sum, radius_in_pixels

    if features.crs is not None and str(features.crs) != grid.crs:
        features = features.to_crs(grid.crs)

    geoms = [geom for geom in features.geometry if geom is not None and not geom.is_empty]
    if not geoms:
        return np.zeros((grid.height, grid.width), dtype=np.float32)

    coverage_mask = rasterize(
        ((geom, 1) for geom in geoms),
        out_shape=(grid.height, grid.width),
        transform=grid.transform,
        fill=0,
        all_touched=False,
        dtype=np.uint8,
    )

    kernel = circular_kernel(radius_in_pixels(window_radius_m, grid.resolution_m))

    covered_cell_count = circular_window_sum(coverage_mask, kernel)
    density = covered_cell_count / kernel.sum()
    return density.astype(np.float32)


class BuildingDensityResult:
    def __init__(self, density: np.ndarray, grid: AOIGrid, nodata: None, attribution: str):
        self.density = density
        self.grid = grid
        self.nodata = nodata
        self.attribution = attribution


def get_building_density(aoi: AOI) -> BuildingDensityResult:
    """Local building-footprint coverage density (0-1) for `aoi`, reusing
    get_osm_features(aoi).buildings — the same buildings dist_to_road's
    sibling criteria already fetch nothing extra for, per the same "no
    separate OSM query" principle dist_to_road follows for roads.

    `nodata` is always None: density is defined everywhere in the grid
    (0 where no buildings fall within the window, never "unknown") — see
    reclassify.apply_reclassification, which already treats
    `input_nodata is None` as "every pixel is valid data".
    """

    def _compute() -> BuildingDensityResult:
        buildings = get_osm_features(aoi).buildings
        grid = compute_aoi_grid(aoi.bounds_utm)
        density = compute_density_raster(buildings, grid, config.BUILDING_DENSITY_WINDOW_RADIUS_M)
        return BuildingDensityResult(density=density, grid=grid, nodata=None, attribution=OSM_ATTRIBUTION)

    version = f"r{config.BUILDING_DENSITY_WINDOW_RADIUS_M}"
    return cached_or_compute("building_density", aoi, _compute, version=version)
