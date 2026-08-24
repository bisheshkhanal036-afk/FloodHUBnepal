"""METEOR Project Nepal flood hazard source: modeled water depth (meters)
from the Fathom global flood hazard framework -- local-only, unlike
every other module in this package. There is no live cloud fallback
here: METEOR only exposes raw numeric depth values through a one-time
downloadable GeoTIFF package, not through any windowed-read-friendly
endpoint the way dem.py/worldcover.py/soil.py/chirps.py's cloud
fallbacks do (their public WMS/WMTS tile service serves pre-styled RGB
PNG only, useless as numeric criterion input -- verified live during
implementation). A missing local file is therefore a hard failure here
(DataSourceUnavailableError), not the normal "fall back to cloud" case
every local-check-first module in this package treats it as.

This is also a genuinely different *kind* of criterion from every other
source registered in overlay/sources.py: it isn't a proxy correlated
with flood risk (distance to river, TWI, HAND, rainfall, ...) -- it's a
third party's own modeled flood hazard output, i.e. someone else's
answer to the same question this project's AHP pipeline is built to
compute. Registered anyway, at explicit request, as one input among
several rather than a replacement for the others: METEOR/Fathom's own
metadata.txt is explicit that "it is not recommended to use the data
for detailed local scale assessments or engineering purposes" given its
~90m/regional-scale modelling assumptions -- the same kind of caveat
this project's own hand/soil_infiltration criteria already carry a
frontend disclaimer for (config/criteria.js's DATA_GAP_DISCLAIMERS);
flood_hazard_meteor is added to that same list.

See attribution.py's METEOR_FLOOD_ATTRIBUTION for the full citation and
config.py's LOCAL_METEOR_FLOOD_DIR comment for the live-verified file
format (CRS, dtype, both sentinel nodata values, and real value range).
"""

from __future__ import annotations

import logging
import math

import numpy as np
import rasterio
from rasterio.windows import Window, from_bounds

from . import config
from .aoi import AOI
from .attribution import METEOR_FLOOD_ATTRIBUTION
from .cache import cached_or_compute
from .errors import DataSourceUnavailableError
from .grid import AOIGrid, compute_aoi_grid, reproject_to_grid
from .local_source import find_local_raster_covering_aoi
from .nodata import require_defined_nodata

logger = logging.getLogger(__name__)

METEOR_FLOOD_OUTPUT_NODATA = -9999.0

# Below this fraction of in-AOI pixels actually falling inside the
# Fathom model's simulated floodplain domain, attach a warning -- not
# because anything is wrong (see this module's docstring: most of
# Nepal's terrain is legitimately outside any floodplain the model ever
# attempts to flood), but because a user drawing an AOI that lands
# mostly on hillslope/ridge terrain should understand *why* this
# criterion looks sparse there, the same way twi/drainage_density/hand's
# own warnings explain an AOI-edge reliability caveat rather than
# leaving the caller to guess.
_LOW_COVERAGE_WARNING_THRESHOLD = 0.10


def _whole_pixel_window(aoi: AOI, transform) -> Window:
    """Same defensive expansion as chirps.py's own `_whole_pixel_window`
    (see that module's docstring for the real sub-pixel-window bug this
    guards against) -- METEOR's ~90m native pixels are coarser than
    DEM/WorldCover/SoilGrids, so a small polygon-drawn AOI could in
    principle still fall inside a single pixel's footprint.
    """
    window = from_bounds(*aoi.bbox_4326, transform=transform)
    col_off = math.floor(window.col_off)
    row_off = math.floor(window.row_off)
    width = max(1, math.ceil(window.col_off + window.width) - col_off)
    height = max(1, math.ceil(window.row_off + window.height) - row_off)
    return Window(col_off, row_off, width, height)


class MeteorFloodResult:
    def __init__(
        self,
        depth_m: np.ndarray,
        grid: AOIGrid,
        nodata: float,
        source_used: str,
        warning: str | None,
    ):
        self.depth_m = depth_m
        self.grid = grid
        self.nodata = nodata
        self.source_used = source_used
        self.warning = warning
        self.attribution = METEOR_FLOOD_ATTRIBUTION


def _mask_sentinels(raw: np.ndarray) -> np.ndarray:
    """Both empirically-found sentinel values (config.py's
    METEOR_FLOOD_NODATA_VALUES) become NaN, so reproject_to_grid's
    src_nodata can treat them uniformly -- the distinction between
    "outside model domain" (-9999) and the rarer masked value (999)
    doesn't matter downstream; both mean "no depth value here."
    """
    depth = raw.astype(np.float64)
    depth[np.isin(raw, config.METEOR_FLOOD_NODATA_VALUES)] = np.nan
    return depth


def _read_local_window(path, aoi: AOI):
    with rasterio.open(path) as ds:
        window = _whole_pixel_window(aoi, ds.transform)
        data = ds.read(1, window=window)
        window_transform = ds.window_transform(window)
        crs = ds.crs
    return data, window_transform, crs


def get_meteor_flood_hazard(aoi: AOI) -> MeteorFloodResult:
    def _compute() -> MeteorFloodResult:
        filename = f"{config.METEOR_FLOOD_TYPE}_{config.METEOR_FLOOD_RETURN_PERIOD}.tif"
        match = find_local_raster_covering_aoi(config.LOCAL_METEOR_FLOOD_DIR, aoi, patterns=(filename,))
        if match is None:
            raise DataSourceUnavailableError(
                f"meteor_flood: no local {filename!r} covering this AOI found in "
                f"{config.LOCAL_METEOR_FLOOD_DIR} -- there is no live cloud fallback for METEOR's "
                "raw numeric flood-depth values (only pre-styled WMS/WMTS tiles exist publicly, "
                "unsuitable as criterion input; see this module's own docstring). Download the "
                "flood hazard package from https://maps.meteor-project.org/map/flood-npl/download "
                f"and place the wanted layer at {config.LOCAL_METEOR_FLOOD_DIR / filename} (see "
                "app/data/config.py's LOCAL_METEOR_FLOOD_DIR comment for the naming convention)."
            )

        logger.info("meteor_flood: LOCAL HIT for aoi=%s -> %s", aoi.bbox_4326, match.path)
        array, transform, crs = _read_local_window(match.path, aoi)
        source_used = f"local:{match.path.name}"

        depth_native = _mask_sentinels(array)

        grid = compute_aoi_grid(aoi.bounds_utm)
        depth_resampled = reproject_to_grid(
            depth_native, transform, crs, grid,
            kind="continuous", src_nodata=float("nan"), dst_nodata=METEOR_FLOOD_OUTPUT_NODATA, dtype=np.float32,
        )
        nodata = require_defined_nodata(METEOR_FLOOD_OUTPUT_NODATA, "flood_hazard_meteor")

        valid_fraction = float(np.mean(depth_resampled != nodata))
        warning = None
        if valid_fraction < _LOW_COVERAGE_WARNING_THRESHOLD:
            warning = (
                f"Only {valid_fraction * 100:.1f}% of this AOI falls inside the Fathom model's "
                "simulated floodplain domain; the rest (e.g. hillslope or ridge terrain) is "
                "outside where this model ever attempts to flood, which is expected, not a data "
                "gap. This is a third-party modeled hazard estimate at ~90m resolution -- "
                "METEOR's own documentation recommends it for regional guidance, not detailed "
                "local-scale assessment."
            )

        return MeteorFloodResult(
            depth_m=depth_resampled, grid=grid, nodata=nodata, source_used=source_used, warning=warning
        )

    return cached_or_compute("flood_hazard_meteor", aoi, _compute)
