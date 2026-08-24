"""CHIRPS satellite precipitation source: a continuous, gauge-informed
satellite precipitation surface, local-check-first with a live cloud
fallback -- same shape as dem.py/worldcover.py/soil.py.

Why this exists alongside `rainfall.py`
----------------------------------------
`rainfall.py` interpolates Nepal's own DHM gauge network (IDW,
elevation-blind, sparse in the mountains). This module is a genuinely
independent second precipitation estimate: CHIRPS (Climate Hazards
group InfraRed Precipitation with Station data, Funk et al. 2015) is a
satellite-derived, quasi-global product that itself blends infrared
cold-cloud-duration imagery with station data, at a dense, gapless
0.05° (~5.5km) grid -- so it never depends on how close the nearest DHM
gauge happens to be to a given AOI. Registered as its own criterion
(`precipitation_chirps`), not a silent fallback folded into
`rainfall.py`: the two are different measurements with different
failure modes (IDW's elevation-blindness vs. satellite IR's own known
bias over high, snow-covered, complex terrain), and a user should be
able to see, weight, and reason about them independently, the same way
`dist_to_river` and `drainage_density` are two separate hydrological
criteria rather than one blended one.

Data
----
CHIRPS-2.0's own 44-year (1981-2024) mean-annual-precipitation
climatology -- one global GeoTIFF, not a per-date fetch: a flood-risk
criterion wants "how much does it normally rain here", the same
climatological framing `rainfall.py`'s own ETCCDI indices use (computed
over 1980-2022), not a specific day's or year's weather.
config.CHIRPS_ANNUAL_NORMALS_URL points at it; see that constant's own
comment for the live-verified CRS/dtype/nodata/resolution details.

Unlike SoilGrids (soil.py), CHIRPS's CRS is plain EPSG:4326, so this
module's windowed reads pass aoi.bbox_4326 straight in as the window
bounds -- no Homolosine-style reprojection-before-windowing needed,
same as dem.py/worldcover.py.

Nodata is NOT declared in the file's own GDAL metadata (confirmed live:
`rasterio.open(...).nodata` reports `None`) -- so, unlike dem.py
(which reads `ds.nodata` off the dataset because GLO-30 COGs do declare
one), this module supplies config.CHIRPS_NODATA (-9999.0) explicitly
rather than trusting an absent tag, per SPEC.md's nodata-handling rule:
every input raster's nodata must be a known, explicit value before it
participates in any overlay math, never silently inferred.
"""

from __future__ import annotations

import logging
import math

import numpy as np
import rasterio
from rasterio.windows import Window, from_bounds

from . import config
from .aoi import AOI
from .attribution import CHIRPS_ATTRIBUTION
from .cache import cached_or_compute
from .grid import AOIGrid, compute_aoi_grid, reproject_to_grid
from .local_source import find_local_raster_covering_aoi
from .nodata import require_defined_nodata

logger = logging.getLogger(__name__)

CHIRPS_OUTPUT_NODATA = -9999.0


def _whole_pixel_window(aoi: AOI, transform) -> Window:
    """`from_bounds(*aoi.bbox_4326, transform=...)`, expanded outward to
    whole source pixels and floored at 1x1.

    A real bug found live during implementation: CHIRPS's own ~5.5km
    (0.05°) native pixels are coarse enough that a small AOI can fall
    entirely inside a single pixel's footprint -- the raw fractional
    window `from_bounds` returns for a real ~2km test AOI came back
    width=0.4, height=0.4 (pixels), which `ds.read()` then rejects
    outright ("Invalid dataset dimensions: 0 x 0") rather than silently
    rounding to something usable. Every other windowed-read source in
    this project (DEM 30m, WorldCover 10m, SoilGrids 250m) is fine-
    grained enough relative to this project's own AOI sizes that this
    never surfaces there; CHIRPS's much coarser native resolution is
    what makes it a real, not theoretical, case here.
    """
    window = from_bounds(*aoi.bbox_4326, transform=transform)
    col_off = math.floor(window.col_off)
    row_off = math.floor(window.row_off)
    width = max(1, math.ceil(window.col_off + window.width) - col_off)
    height = max(1, math.ceil(window.row_off + window.height) - row_off)
    return Window(col_off, row_off, width, height)


class ChirpsPrecipitationResult:
    def __init__(self, precipitation_mm: np.ndarray, grid: AOIGrid, nodata: float, source_used: str):
        self.precipitation_mm = precipitation_mm
        self.grid = grid
        self.nodata = nodata
        self.source_used = source_used
        self.attribution = CHIRPS_ATTRIBUTION


def _fetch_chirps_from_cloud(aoi: AOI):
    """Live windowed read from UCSB's own public hosting of the CHIRPS-2.0
    annual-normals GeoTIFF. Isolated as its own function so tests can mock
    exactly this call for the cloud-fallback path without touching the
    network -- same pattern as dem.py/worldcover.py/soil.py's own fetch
    functions.
    """
    logger.info("chirps: cloud fallback, fetching window from %s", config.CHIRPS_ANNUAL_NORMALS_URL)
    with rasterio.Env(**config.GDAL_HTTP_RETRY_ENV):
        with rasterio.open(config.CHIRPS_ANNUAL_NORMALS_URL) as ds:
            window = _whole_pixel_window(aoi, ds.transform)
            data = ds.read(1, window=window)
            window_transform = ds.window_transform(window)
            crs = ds.crs
    return data, window_transform, crs


def _read_local_window(path, aoi: AOI):
    with rasterio.open(path) as ds:
        window = _whole_pixel_window(aoi, ds.transform)
        data = ds.read(1, window=window)
        window_transform = ds.window_transform(window)
        crs = ds.crs
    return data, window_transform, crs


def get_chirps_precipitation(aoi: AOI) -> ChirpsPrecipitationResult:
    def _compute() -> ChirpsPrecipitationResult:
        match = find_local_raster_covering_aoi(config.LOCAL_CHIRPS_DIR, aoi)
        if match:
            logger.info("chirps: LOCAL HIT for aoi=%s -> %s", aoi.bbox_4326, match.path)
            array, transform, crs = _read_local_window(match.path, aoi)
            source_used = f"local:{match.path.name}"
        else:
            logger.info("chirps: no local coverage for aoi=%s, falling back to cloud (CHIRPS)", aoi.bbox_4326)
            array, transform, crs = _fetch_chirps_from_cloud(aoi)
            source_used = "chirps:global_annual/1981-2024.44yrs"

        grid = compute_aoi_grid(aoi.bounds_utm)
        precipitation = reproject_to_grid(
            array.astype(np.float32), transform, crs, grid,
            kind="continuous", src_nodata=config.CHIRPS_NODATA, dst_nodata=CHIRPS_OUTPUT_NODATA, dtype=np.float32,
        )
        nodata = require_defined_nodata(CHIRPS_OUTPUT_NODATA, "precipitation_chirps")

        return ChirpsPrecipitationResult(
            precipitation_mm=precipitation, grid=grid, nodata=nodata, source_used=source_used
        )

    return cached_or_compute("precipitation_chirps", aoi, _compute)
