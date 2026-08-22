"""Geospatial data layer: DEM, WorldCover, OSM, basin, distance-raster,
density-raster, and hydrology sources, each following local-check-first /
cloud-fetch-fallback (basins.py excepted — it has only a local file, no
cloud fallback), reprojected/resampled onto the common per-AOI grid
described in SPEC.md. See dem.py, worldcover.py, osm.py, basins.py,
distance_raster.py, density_raster.py, and hydrology.py for the source-
specific behavior; aoi.py/grid.py/local_source.py/cache.py/nodata.py/
reclassify.py hold the logic shared across the raster sources.
"""

from .aoi import AOI
from .basins import (
    NEPAL_BBOX_4326,
    basin_area_km2,
    basin_to_aoi,
    classify_support_status,
    get_basin,
    get_basin_pct_in_nepal,
    get_basin_support_status,
    list_basins_overlapping_nepal,
    pct_area_in_nepal,
    reset_basins_cache,
    reset_nepal_boundary_cache,
)
from .dem import DEMResult, compute_slope_degrees, get_dem
from .density_raster import BuildingDensityResult, compute_density_raster, get_building_density
from .distance_raster import (
    DistanceRasterResult,
    compute_distance_raster,
    get_distance_to_river,
    get_distance_to_road,
)
from .errors import (
    BasinNotFoundError,
    DataSourceUnavailableError,
    NodataValidationError,
    ReclassificationError,
)
from .grid import AOIGrid, compute_aoi_grid, reproject_to_grid
from .hydrology import (
    DrainageDensityResult,
    FlowAccumulationResult,
    TWIResult,
    compute_drainage_density_raster,
    compute_flow_accumulation,
    get_drainage_density,
    get_twi,
)
from .osm import OSMResult, WaterwaysResult, get_osm_features, get_waterways, reset_local_osm_parser_cache
from .reclassify import (
    apply_reclassification,
    apply_reclassification_cached,
    rules_fingerprint,
    validate_reclassification_rules,
)
from .worldcover import WorldCoverResult, get_worldcover

__all__ = [
    "AOI",
    "AOIGrid",
    "compute_aoi_grid",
    "reproject_to_grid",
    "DEMResult",
    "get_dem",
    "compute_slope_degrees",
    "WorldCoverResult",
    "get_worldcover",
    "OSMResult",
    "get_osm_features",
    "WaterwaysResult",
    "get_waterways",
    "reset_local_osm_parser_cache",
    "DistanceRasterResult",
    "compute_distance_raster",
    "get_distance_to_river",
    "get_distance_to_road",
    "BuildingDensityResult",
    "compute_density_raster",
    "get_building_density",
    "FlowAccumulationResult",
    "compute_flow_accumulation",
    "TWIResult",
    "get_twi",
    "DrainageDensityResult",
    "compute_drainage_density_raster",
    "get_drainage_density",
    "NEPAL_BBOX_4326",
    "basin_area_km2",
    "basin_to_aoi",
    "classify_support_status",
    "get_basin",
    "get_basin_pct_in_nepal",
    "get_basin_support_status",
    "list_basins_overlapping_nepal",
    "pct_area_in_nepal",
    "reset_basins_cache",
    "reset_nepal_boundary_cache",
    "apply_reclassification",
    "apply_reclassification_cached",
    "rules_fingerprint",
    "validate_reclassification_rules",
    "BasinNotFoundError",
    "DataSourceUnavailableError",
    "NodataValidationError",
    "ReclassificationError",
]
