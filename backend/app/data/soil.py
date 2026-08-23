"""ISRIC SoilGrids 2.0 soil-infiltration-capacity source: per-pixel topsoil
(0-5cm) sand content at 250m native resolution, local-check-first with a
live cloud fallback -- same shape as dem.py/worldcover.py/population.py.

Used as a flood-risk criterion via the standard soil-texture reasoning:
coarser (sandier) soil drains faster and infiltrates more, so higher sand
content means LOWER flood risk (frontend riskDirection: "descending", set
in config/criteria.js) -- the same relationship USDA Hydrologic Soil Group
classification is ultimately built on (Group A, mostly sand, has the
highest infiltration rate; Group D, mostly clay, the lowest). This module
deliberately stops at the raw sand-content proxy rather than deriving a
full Hydrologic Soil Group via the USDA texture triangle (which needs
clay% too, plus a lookup against non-trivial triangle boundaries) --
flagged as a decision to confirm; see this phase's closing decisions list.

--- Unlike every other source in this package: source CRS ---

DEM/WorldCover/Population's cloud sources are all native EPSG:4326, so
those modules' windowed reads pass aoi.bbox_4326 straight in as the
window bounds (the source transform is already in the same coordinate
space). SoilGrids' global mosaic is NOT -- verified live during
implementation: `rasterio.open()` against the real sand_0-5cm_mean.vrt
reports its CRS as Interrupted Goode Homolosine, a non-trivial global
projection in meters, not degrees. `_soilgrids_window_bounds` below
explicitly reprojects the AOI bbox into the source's own CRS
(`rasterio.warp.transform_bounds`) before building the read window --
skipping this (i.e. copying dem.py's `from_bounds(*aoi.bbox_4326, ...)`
pattern unmodified) would silently read the wrong window (Homolosine
coordinates numerically resemble large UTM-like meter values, so the
bug would not raise an error, just silently return data for the wrong
patch of the globe).

Confirmed safe for this project's real AOI: Nepal/Kathmandu Valley
(~85E, ~27.7N) sits well inside a single uninterrupted Homolosine lobe
(the projection's interruptions are placed in the oceans specifically so
they don't cut through populated landmasses) -- live-verified during
implementation by reading a real window over Kathmandu Valley and
confirming plausible, spatially coherent sand-content values (not the
scrambled/discontinuous values a seam-crossing read would produce).
`reproject_to_grid` (grid.py) itself needs no special-casing for this --
it already delegates to `rasterio.warp.reproject`, which supports
arbitrary source CRS via GDAL/PROJ exactly the same way regardless of
what that CRS is.

--- Value scaling ---

The raw int16 raster value is NOT a percentage. Confirmed via ISRIC's own
published SoilGrids conversion-factor table: sand's mapped unit is g/kg,
conversion factor 10, conventional unit g/100g (%) -- i.e. divide the raw
value by 10 to get sand content as a percentage of fine-earth mass. Doing
the scaling here (`_RAW_TO_PERCENT`), before reprojection, keeps
everything downstream of this module (reclassification breakpoints,
criteria.js's displayed unit) in the conventional "%" every other
percentage-like criterion in this project already uses -- not SoilGrids'
own internal encoding.

Source nodata is -32768 (int16), verified live -- kept as a genuine
"unknown" and propagated as nodata through reprojection (unlike
population.py's HRSL, whose nodata means a specifically-documented
confirmed zero; no equivalent documented reason was found for SoilGrids,
so this module uses this project's own default, more conservative
reading of nodata elsewhere: unknown stays unknown, not remapped to any
particular value). Live-verified over a wider Kathmandu Valley bbox
during implementation: ~74% of pixels valid, consistent with a
250m-native product read into a comparatively small window/AOI, not a
sign of a masking or read bug.
"""

from __future__ import annotations

import logging

import numpy as np
import rasterio
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds

from . import config
from .aoi import AOI
from .attribution import SOIL_ATTRIBUTION
from .cache import cached_or_compute
from .grid import AOIGrid, compute_aoi_grid, reproject_to_grid
from .local_source import find_local_raster_covering_aoi
from .nodata import require_defined_nodata

logger = logging.getLogger(__name__)

SOIL_OUTPUT_NODATA = -9999.0

# ISRIC's own documented conversion factor for sand: raw g/kg -> g/100g (%).
_RAW_TO_PERCENT = 10.0


class SoilInfiltrationResult:
    def __init__(self, sand_pct: np.ndarray, grid: AOIGrid, nodata: float, source_used: str):
        self.sand_pct = sand_pct
        self.grid = grid
        self.nodata = nodata
        self.source_used = source_used
        self.attribution = SOIL_ATTRIBUTION


def _soilgrids_window_bounds(aoi: AOI, src_crs) -> tuple[float, float, float, float]:
    """Reprojects the AOI's EPSG:4326 bbox into the source raster's own
    CRS -- see this module's own docstring for why this can't reuse
    dem.py/worldcover.py/population.py's `from_bounds(*aoi.bbox_4326, ...)`
    pattern (those all assume src CRS == EPSG:4326, true for their own
    sources but not this one).
    """
    return transform_bounds("EPSG:4326", src_crs, *aoi.bbox_4326)


def _scale_and_mask(raw: np.ndarray, src_nodata: float) -> tuple[np.ndarray, float]:
    """Converts a raw int16 SoilGrids array into a float32 percentage
    array, with nodata pixels carried through as NaN (rather than left as
    the raw -32768 sentinel, which `_RAW_TO_PERCENT` would otherwise
    silently turn into a nonsense -3276.8%). Returns (percent_array,
    nan_as_the_working_nodata_sentinel) for reproject_to_grid's
    `src_nodata` to consume.
    """
    nodata_mask = raw == src_nodata
    percent = raw.astype(np.float64) / _RAW_TO_PERCENT
    percent[nodata_mask] = np.nan
    return percent, float("nan")


def _fetch_sand_from_cloud(aoi: AOI):
    """Live windowed read from ISRIC's single global sand_0-5cm_mean.vrt
    mosaic. Isolated as its own function so tests can mock exactly this
    call for the cloud-fallback path without touching the network -- same
    pattern as dem.py/worldcover.py/population.py's own fetch functions.
    """
    logger.info("soil: cloud fallback, fetching window from %s", config.SOILGRIDS_SAND_VRT_URL)
    with rasterio.Env(**config.GDAL_HTTP_RETRY_ENV):
        with rasterio.open(config.SOILGRIDS_SAND_VRT_URL) as ds:
            minx, miny, maxx, maxy = _soilgrids_window_bounds(aoi, ds.crs)
            window = from_bounds(minx, miny, maxx, maxy, transform=ds.transform)
            data = ds.read(1, window=window)
            window_transform = ds.window_transform(window)
            crs = ds.crs
            src_nodata = ds.nodata
    return data, window_transform, crs, src_nodata


def _read_local_window(path, aoi: AOI):
    with rasterio.open(path) as ds:
        minx, miny, maxx, maxy = _soilgrids_window_bounds(aoi, ds.crs)
        window = from_bounds(minx, miny, maxx, maxy, transform=ds.transform)
        data = ds.read(1, window=window)
        window_transform = ds.window_transform(window)
        crs = ds.crs
        src_nodata = ds.nodata
    return data, window_transform, crs, src_nodata


def get_soil_infiltration(aoi: AOI) -> SoilInfiltrationResult:
    def _compute() -> SoilInfiltrationResult:
        match = find_local_raster_covering_aoi(config.LOCAL_SOIL_DIR, aoi)
        if match:
            logger.info("soil: LOCAL HIT for aoi=%s -> %s", aoi.bbox_4326, match.path)
            array, transform, crs, src_nodata = _read_local_window(match.path, aoi)
            source_used = f"local:{match.path.name}"
        else:
            logger.info("soil: no local coverage for aoi=%s, falling back to cloud (SoilGrids)", aoi.bbox_4326)
            array, transform, crs, src_nodata = _fetch_sand_from_cloud(aoi)
            source_used = "isric:soilgrids/sand_0-5cm_mean"

        percent_native, working_nodata = _scale_and_mask(array, src_nodata)

        grid = compute_aoi_grid(aoi.bounds_utm)
        percent_resampled = reproject_to_grid(
            percent_native, transform, crs, grid,
            kind="continuous", src_nodata=working_nodata, dst_nodata=SOIL_OUTPUT_NODATA, dtype=np.float32,
        )
        nodata = require_defined_nodata(SOIL_OUTPUT_NODATA, "soil")

        return SoilInfiltrationResult(sand_pct=percent_resampled, grid=grid, nodata=nodata, source_used=source_used)

    return cached_or_compute("soil_infiltration", aoi, _compute)
