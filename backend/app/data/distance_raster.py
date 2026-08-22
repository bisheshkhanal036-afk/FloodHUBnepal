"""Generic Euclidean distance-to-nearest-feature raster on the common
per-AOI grid, plus the two cached criterion-source wrappers that use it:
distance-from-river and distance-from-road (app/overlay/sources.py's
dist_to_river / dist_to_road registrations).

compute_distance_raster() itself is not river- or road-specific — it
takes an arbitrary GeoDataFrame of vector features and an AOIGrid, so a
future "distance from X" criterion (a hospital, a fault line, whatever)
can reuse it directly rather than reimplementing the transform.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
from rasterio.features import rasterize
from scipy.ndimage import distance_transform_edt

from .aoi import AOI
from .attribution import OSM_ATTRIBUTION
from .cache import cached_or_compute
from .grid import AOIGrid, compute_aoi_grid
from .osm import get_osm_features, get_waterways

# Distance in meters is always >= 0, so a negative sentinel is
# unambiguous. Used only for the "this AOI has zero features of this
# type at all" case (compute_distance_raster can't measure a distance to
# nothing) — an explicit, flagged case per SPEC.md's Nodata handling
# convention, never silently returned as 0 or an arbitrarily large number.
DISTANCE_RASTER_NODATA = -1.0


def compute_distance_raster(features: gpd.GeoDataFrame, grid: AOIGrid) -> np.ndarray:
    """Euclidean distance in meters from each grid cell to the nearest
    geometry in `features`, computed on `grid` (EPSG:32645, 10m per
    SPEC.md's Grid/resolution convention). `features` is reprojected to
    grid.crs first if it isn't already there; an empty GeoDataFrame
    returns an all-DISTANCE_RASTER_NODATA array.

    Implementation: rasterizes `features` onto `grid` (all_touched=True,
    so a line thinner than one pixel still marks every pixel it crosses,
    not just pixel centers it happens to fall on) into a binary feature/
    background mask, then runs a Euclidean distance transform
    (scipy.ndimage.distance_transform_edt, with `sampling=(resolution_m,
    resolution_m)` so the output is in real meters rather than pixel
    counts) from every non-feature pixel to the nearest feature pixel.

    This quantizes the true (vector) distance to the grid's own 10m
    resolution — accurate to within about one pixel diagonal (~14m) of
    the exact vector distance — which is the same precision every other
    raster in this layer already operates at, and standard practice for
    a Euclidean-distance GIS raster built at this scale. Confirmed.
    """
    if features.crs is not None and str(features.crs) != grid.crs:
        features = features.to_crs(grid.crs)

    geoms = [geom for geom in features.geometry if geom is not None and not geom.is_empty]
    if not geoms:
        return np.full((grid.height, grid.width), DISTANCE_RASTER_NODATA, dtype=np.float32)

    feature_mask = rasterize(
        ((geom, 1) for geom in geoms),
        out_shape=(grid.height, grid.width),
        transform=grid.transform,
        fill=0,
        all_touched=True,
        dtype=np.uint8,
    )

    distance_m = distance_transform_edt(feature_mask == 0, sampling=(grid.resolution_m, grid.resolution_m))
    return distance_m.astype(np.float32)


class DistanceRasterResult:
    def __init__(self, distance_m: np.ndarray, grid: AOIGrid, nodata: float, attribution: str):
        self.distance_m = distance_m
        self.grid = grid
        self.nodata = nodata
        self.attribution = attribution


def get_distance_to_river(aoi: AOI) -> DistanceRasterResult:
    def _compute() -> DistanceRasterResult:
        waterways = get_waterways(aoi).waterways
        grid = compute_aoi_grid(aoi.bounds_utm)
        distance_m = compute_distance_raster(waterways, grid)
        return DistanceRasterResult(
            distance_m=distance_m, grid=grid, nodata=DISTANCE_RASTER_NODATA, attribution=OSM_ATTRIBUTION
        )

    return cached_or_compute("dist_to_river", aoi, _compute)


def get_distance_to_road(aoi: AOI) -> DistanceRasterResult:
    """Reuses get_osm_features(aoi).roads — the same road/highway network
    get_osm_features already fetches for the buildings+roads source — no
    new OSM query, per the brief.
    """

    def _compute() -> DistanceRasterResult:
        roads = get_osm_features(aoi).roads
        grid = compute_aoi_grid(aoi.bounds_utm)
        distance_m = compute_distance_raster(roads, grid)
        return DistanceRasterResult(
            distance_m=distance_m, grid=grid, nodata=DISTANCE_RASTER_NODATA, attribution=OSM_ATTRIBUTION
        )

    return cached_or_compute("dist_to_road", aoi, _compute)
