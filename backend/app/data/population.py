"""Meta/CIESIN High Resolution Settlement Layer (HRSL) population source:
per-pixel estimated population count at ~30m resolution, local-check-
first with a live S3 fallback — same shape as dem.py/worldcover.py.

Unlike DEM/WorldCover, there's no manual per-tile URL templating here:
s3://dataforgood-fb-data/hrsl-cogs/hrsl_general/ publishes a single
`hrsl_general-latest.vrt` — a GDAL virtual-mosaic file already covering
the whole dataset extent — so a plain windowed rasterio.open() + read
against that one URL does the same "mosaic across whatever tiles the AOI
happens to straddle" job DEM/WorldCover's manual tile-ID math does for
their sources, without needing to know the tiling scheme at all.

Verified live during implementation: a real windowed read over Kathmandu
Valley (85.30-85.35E, 27.70-27.75N) returned 16,759 valid pixels out of
32,400 in the window, values in the tens-to-hundreds range per ~30m
pixel — consistent with HRSL's documented data model: this is estimated
population COUNT per source pixel, not a pre-normalized density value.
Source nodata is NaN (read from the dataset, not assumed — same "never
silently assume" rule nodata.py's own docstring describes for
DEM/WorldCover).

Count, not density, matters here: a count is an EXTENSIVE quantity (it
scales with the area it was counted over), unlike elevation/slope/
distance, which are intensive. Bilinear-resampling a raw count directly
from its native ~30m pixels onto this project's 10m grid would silently
stop being a count at all — it neither divides a pixel's count by 9 to
spread it correctly across the nine 10m pixels that now cover the same
ground, nor conserves the AOI's total population. `_count_to_density`
below converts count -> density (people/km²) at the source's own native
resolution FIRST — dividing by each row's true geodetic pixel area, not
one fixed constant, since a WGS84 pixel's ground area shrinks with
latitude (verified: at Kathmandu's ~27.7°N, roughly 27m E-W x 31m N-S,
not a flat 30x30) — and only THEN is the resulting density field handed
to reproject_to_grid for the normal bilinear resample every other
continuous source uses. See SPEC.md §2.2 for the general rule this is
an instance of.

Region config: see config.POPULATION_S3_REGION_ENV's own docstring for
why it's here and what live testing during implementation actually
showed (the plain-HTTPS access pattern used here worked without it, but
it's kept anyway per the brief's explicit instruction).
"""

from __future__ import annotations

import logging

import numpy as np
import rasterio
from rasterio.windows import from_bounds

from . import config
from .aoi import AOI
from .attribution import POPULATION_ATTRIBUTION
from .cache import cached_or_compute
from .grid import AOIGrid, compute_aoi_grid, reproject_to_grid
from .local_source import find_local_raster_covering_aoi
from .nodata import require_defined_nodata

logger = logging.getLogger(__name__)

POPULATION_OUTPUT_NODATA = -9999.0

S3_POPULATION_VRT_URL = "https://dataforgood-fb-data.s3.amazonaws.com/hrsl-cogs/hrsl_general/hrsl_general-latest.vrt"

# Degrees-to-km at the equator, the standard first-order spherical
# approximation used throughout this project's other area/distance math
# (not a survey-grade ellipsoidal figure — unnecessary at this
# resolution/precision).
KM_PER_DEGREE = 111.32


def _count_to_density(array: np.ndarray, transform, crs, nodata: float) -> np.ndarray:
    """Converts a per-pixel population COUNT array to a density
    (people/km²) array, dividing each pixel by its own true ground area
    — not a single fixed constant — so this is correct regardless of
    which row of the array (== which latitude, for a geographic source)
    a given pixel falls on. See this module's own docstring for why this
    conversion has to happen before reprojection, not after.

    `crs.is_geographic` (True for the S3/local HRSL source, EPSG:4326)
    means transform.a/transform.e are pixel width/height in DEGREES, so
    each row's area needs its own cos(latitude) correction for the
    east-west dimension — a pixel at higher latitude covers less true
    ground per degree of longitude. A projected CRS (units already in
    meters) has no such row-dependence: every pixel is the same physical
    size by construction, straight from the transform.
    """
    nodata_mask = np.isnan(array) if np.isnan(nodata) else (array == nodata)

    # Coerce to a real rasterio CRS object -- callers (including this
    # module's own _fetch_population_from_s3/_read_local_window) always
    # pass ds.crs, which already is one, but a plain EPSG string/WKT is
    # just as valid an input to accept defensively here.
    crs = rasterio.crs.CRS.from_user_input(crs)

    if crs.is_geographic:
        pixel_width_deg = abs(transform.a)
        pixel_height_deg = abs(transform.e)
        row_indices = np.arange(array.shape[0])
        row_center_lat = transform.f + transform.e * (row_indices + 0.5)
        area_km2_per_row = (
            (pixel_width_deg * KM_PER_DEGREE * np.cos(np.radians(row_center_lat)))
            * (pixel_height_deg * KM_PER_DEGREE)
        )
        area_km2 = area_km2_per_row[:, np.newaxis]  # broadcast down each row, not across columns
    else:
        pixel_area_m2 = abs(transform.a * transform.e)
        area_km2 = pixel_area_m2 / 1e6  # a scalar: every pixel is the same true size already

    density = array / area_km2
    return np.where(nodata_mask, nodata, density)


class PopulationResult:
    def __init__(self, density: np.ndarray, grid: AOIGrid, nodata: float, source_used: str):
        # `density`, not `population`/`count` -- deliberately named for
        # what this field actually holds after _count_to_density +
        # reprojection (people/km²), not HRSL's raw per-source-pixel
        # count. See this module's own docstring.
        self.density = density
        self.grid = grid
        self.nodata = nodata
        self.source_used = source_used
        self.attribution = POPULATION_ATTRIBUTION


def _fetch_population_from_s3(aoi: AOI):
    """Live windowed read from the single hrsl_general-latest.vrt mosaic.
    Isolated as its own function so tests can mock exactly this call for
    the cloud-fallback path without touching the network — same pattern
    as dem.py's _fetch_dem_from_s3/worldcover.py's _fetch_worldcover_from_s3.
    """
    logger.info("population: cloud fallback, fetching window from %s", S3_POPULATION_VRT_URL)
    env = {**config.GDAL_HTTP_RETRY_ENV, **config.POPULATION_S3_REGION_ENV}
    with rasterio.Env(**env):
        with rasterio.open(S3_POPULATION_VRT_URL) as ds:
            window = from_bounds(*aoi.bbox_4326, transform=ds.transform)
            data = ds.read(1, window=window)
            window_transform = ds.window_transform(window)
            crs = ds.crs
            src_nodata = ds.nodata
    return data, window_transform, crs, src_nodata


def _read_local_window(path, aoi: AOI):
    with rasterio.open(path) as ds:
        window = from_bounds(*aoi.bbox_4326, transform=ds.transform)
        data = ds.read(1, window=window)
        window_transform = ds.window_transform(window)
        crs = ds.crs
        src_nodata = ds.nodata
    return data, window_transform, crs, src_nodata


def get_population(aoi: AOI) -> PopulationResult:
    def _compute() -> PopulationResult:
        match = find_local_raster_covering_aoi(config.LOCAL_POPULATION_DIR, aoi)
        if match:
            logger.info("population: LOCAL HIT for aoi=%s -> %s", aoi.bbox_4326, match.path)
            array, transform, crs, src_nodata = _read_local_window(match.path, aoi)
            source_used = f"local:{match.path.name}"
        else:
            logger.info("population: no local coverage for aoi=%s, falling back to cloud (S3)", aoi.bbox_4326)
            array, transform, crs, src_nodata = _fetch_population_from_s3(aoi)
            source_used = "s3://dataforgood-fb-data/hrsl-cogs/hrsl_general"

        # Count -> density BEFORE reprojection, not after -- see this
        # module's own docstring and SPEC.md §2.2 for why bilinear-
        # resampling the raw count directly would be wrong.
        density_native = _count_to_density(array, transform, crs, src_nodata)

        grid = compute_aoi_grid(aoi.bounds_utm)
        density_resampled = reproject_to_grid(
            density_native, transform, crs, grid,
            kind="continuous", src_nodata=src_nodata, dst_nodata=POPULATION_OUTPUT_NODATA, dtype=np.float32,
        )
        nodata = require_defined_nodata(POPULATION_OUTPUT_NODATA, "population")

        return PopulationResult(density=density_resampled, grid=grid, nodata=nodata, source_used=source_used)

    return cached_or_compute("population", aoi, _compute)
