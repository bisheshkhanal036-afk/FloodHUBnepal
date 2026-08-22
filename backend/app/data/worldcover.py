"""ESA WorldCover 10m source: land cover class raster, local-check-first
with a live S3 fallback — same shape as dem.py, sharing
local_source.find_local_raster_covering_aoi for the local-vs-cloud
decision.

Tile naming (verified live against the bucket, 2026): 3x3 degree cells
snapped to multiples of 3, e.g. .../ESA_WorldCover_10m_2021_v200_
N27E084_Map.tif for the cell covering 27-30N, 84-87E (contains Kathmandu
Valley). Nodata is 0 (also verified live, and declared in the source
file's own metadata — unlike GLO-30, WorldCover does tag nodata).
"""

from __future__ import annotations

import logging
import math

import numpy as np
import rasterio
from rasterio.merge import merge as rio_merge
from rasterio.windows import from_bounds

from . import config
from .aoi import AOI
from .attribution import WORLDCOVER_ATTRIBUTION
from .cache import cached_or_compute
from .grid import AOIGrid, compute_aoi_grid, reproject_to_grid
from .local_source import find_local_raster_covering_aoi
from .nodata import require_defined_nodata

logger = logging.getLogger(__name__)

WORLDCOVER_OUTPUT_NODATA = 0  # matches the source's own nodata class code
TILE_STEP_DEG = 3

S3_WORLDCOVER_URL_TEMPLATE = (
    "https://esa-worldcover.s3.amazonaws.com/v200/2021/map/"
    "ESA_WorldCover_10m_2021_v200_{ns}{lat:02d}{ew}{lon:03d}_Map.tif"
)


class WorldCoverResult:
    def __init__(self, land_cover_class, grid: AOIGrid, nodata: int, source_used: str):
        self.land_cover_class = land_cover_class
        self.grid = grid
        self.nodata = nodata
        self.source_used = source_used
        self.attribution = WORLDCOVER_ATTRIBUTION


def _worldcover_tile_ids_for_bbox(bbox_4326: tuple[float, float, float, float]) -> list[tuple[int, int, str, str]]:
    minx, miny, maxx, maxy = bbox_4326
    lat_lo = math.floor(miny / TILE_STEP_DEG) * TILE_STEP_DEG
    lat_hi = math.floor(maxy / TILE_STEP_DEG) * TILE_STEP_DEG
    lon_lo = math.floor(minx / TILE_STEP_DEG) * TILE_STEP_DEG
    lon_hi = math.floor(maxx / TILE_STEP_DEG) * TILE_STEP_DEG
    tiles = []
    for lat in range(lat_lo, lat_hi + TILE_STEP_DEG, TILE_STEP_DEG):
        for lon in range(lon_lo, lon_hi + TILE_STEP_DEG, TILE_STEP_DEG):
            tiles.append((abs(lat), abs(lon), "N" if lat >= 0 else "S", "E" if lon >= 0 else "W"))
    return tiles


def _fetch_worldcover_from_s3(aoi: AOI):
    """Live windowed read + mosaic from s3://esa-worldcover. Isolated as
    its own function so tests can mock exactly this call for the
    cloud-fallback path without touching the network.
    """
    tiles = _worldcover_tile_ids_for_bbox(aoi.bbox_4326)
    urls = [S3_WORLDCOVER_URL_TEMPLATE.format(ns=ns, lat=lat, ew=ew, lon=lon) for lat, lon, ns, ew in tiles]
    logger.info("worldcover: cloud fallback, fetching %d tile(s) from s3://esa-worldcover", len(urls))

    datasets = [rasterio.open(url) for url in urls]
    try:
        mosaic, mosaic_transform = rio_merge(datasets, bounds=aoi.bbox_4326)
        crs = datasets[0].crs
        src_nodata = datasets[0].nodata
    finally:
        for ds in datasets:
            ds.close()
    return mosaic[0], mosaic_transform, crs, src_nodata


def _read_local_window(path, aoi: AOI):
    with rasterio.open(path) as ds:
        window = from_bounds(*aoi.bbox_4326, transform=ds.transform)
        data = ds.read(1, window=window)
        window_transform = ds.window_transform(window)
        crs = ds.crs
        src_nodata = ds.nodata
    return data, window_transform, crs, src_nodata


def get_worldcover(aoi: AOI) -> WorldCoverResult:
    def _compute() -> WorldCoverResult:
        match = find_local_raster_covering_aoi(config.LOCAL_WORLDCOVER_DIR, aoi)
        if match:
            logger.info("worldcover: LOCAL HIT for aoi=%s -> %s", aoi.bbox_4326, match.path)
            array, transform, crs, src_nodata = _read_local_window(match.path, aoi)
            source_used = f"local:{match.path.name}"
        else:
            logger.info("worldcover: no local coverage for aoi=%s, falling back to cloud (S3)", aoi.bbox_4326)
            array, transform, crs, src_nodata = _fetch_worldcover_from_s3(aoi)
            source_used = "s3://esa-worldcover"

        grid = compute_aoi_grid(aoi.bounds_utm)
        # Categorical data: nearest-neighbor resampling only (SPEC.md,
        # Grid/resolution convention) — never bilinear/average across
        # discrete land-cover class codes.
        land_cover_class = reproject_to_grid(
            array, transform, crs, grid,
            kind="categorical", src_nodata=src_nodata, dst_nodata=WORLDCOVER_OUTPUT_NODATA, dtype=np.uint8,
        )
        nodata = require_defined_nodata(WORLDCOVER_OUTPUT_NODATA, "worldcover")

        return WorldCoverResult(land_cover_class=land_cover_class, grid=grid, nodata=nodata, source_used=source_used)

    return cached_or_compute("worldcover", aoi, _compute)
