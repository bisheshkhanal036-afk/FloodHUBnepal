"""Copernicus GLO-30 DEM source: elevation + derived slope, local-check-
first with a live S3 fallback.

Local-check-first: backend/data/raw/dem/ is checked for a pre-downloaded
file covering the AOI (via local_source.find_local_raster_covering_aoi,
shared with worldcover.py). If none covers the AOI — including the
totally normal case of no local files at all — falls back to a live
windowed read from the public, anonymous-access AWS Open Data bucket
s3://copernicus-dem-30m (COG, no credentials needed; verified live
during implementation of this module).

Tile naming (verified live against the bucket, 2026): 1x1 degree cells,
e.g. .../Copernicus_DSM_COG_10_N27_00_E085_00_DEM/..._DEM.tif for the
cell covering 27-28N, 85-86E (which contains Kathmandu Valley). An AOI
that straddles a tile boundary is mosaicked from multiple tiles.
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
from .attribution import DEM_ATTRIBUTION
from .cache import cached_or_compute
from .grid import AOIGrid, compute_aoi_grid, reproject_to_grid
from .local_source import find_local_raster_covering_aoi
from .nodata import require_defined_nodata

logger = logging.getLogger(__name__)

DEM_OUTPUT_NODATA = -9999.0
SLOPE_OUTPUT_NODATA = -9999.0

S3_DEM_URL_TEMPLATE = (
    "https://copernicus-dem-30m.s3.amazonaws.com/"
    "Copernicus_DSM_COG_10_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM/"
    "Copernicus_DSM_COG_10_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM.tif"
)


class DEMResult:
    def __init__(self, elevation_m, slope_degrees, grid: AOIGrid, nodata: float, source_used: str):
        self.elevation_m = elevation_m
        self.slope_degrees = slope_degrees
        self.grid = grid
        self.nodata = nodata
        self.source_used = source_used
        self.attribution = DEM_ATTRIBUTION


def _dem_tile_ids_for_bbox(bbox_4326: tuple[float, float, float, float]) -> list[tuple[int, int, str, str]]:
    minx, miny, maxx, maxy = bbox_4326
    lat_lo, lat_hi = math.floor(miny), math.floor(maxy)
    lon_lo, lon_hi = math.floor(minx), math.floor(maxx)
    tiles = []
    for lat in range(lat_lo, lat_hi + 1):
        for lon in range(lon_lo, lon_hi + 1):
            tiles.append((abs(lat), abs(lon), "N" if lat >= 0 else "S", "E" if lon >= 0 else "W"))
    return tiles


def _fetch_dem_from_s3(aoi: AOI):
    """Live windowed read + mosaic from s3://copernicus-dem-30m. Isolated
    as its own function so tests can mock exactly this call for the
    cloud-fallback path without touching the network.
    """
    tiles = _dem_tile_ids_for_bbox(aoi.bbox_4326)
    urls = [S3_DEM_URL_TEMPLATE.format(ns=ns, lat=lat, ew=ew, lon=lon) for lat, lon, ns, ew in tiles]
    logger.info("dem: cloud fallback, fetching %d tile(s) from s3://copernicus-dem-30m", len(urls))

    with rasterio.Env(**config.GDAL_HTTP_RETRY_ENV):
        datasets = [rasterio.open(url) for url in urls]
        try:
            mosaic, mosaic_transform = rio_merge(datasets, bounds=aoi.bbox_4326)
            crs = datasets[0].crs
            # Verified live during implementation: GLO-30 COG tiles report no
            # nodata tag (void-filled product, no missing pixels within a
            # tile) — read it from the dataset rather than assume, so a
            # future change on the producer's side would surface here.
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


def compute_slope_degrees(elevation: np.ndarray, resolution_m: float, nodata: float) -> np.ndarray:
    """Slope in degrees via Horn's method (Horn, B.K.P., 1981. "Hill
    shading and the reflectance map." Proceedings of the IEEE, 69(1),
    14-47) — the weighted 3x3-kernel slope algorithm used by default in
    ArcGIS, QGIS, and gdaldem, chosen here for consistency with standard
    GIS terrain-analysis output rather than a plain unweighted
    central-difference gradient:

        dz/dx = ((c + 2f + i) - (a + 2d + g)) / (8 * resolution_m)
        dz/dy = ((g + 2h + i) - (a + 2b + c)) / (8 * resolution_m)

    for the 3x3 neighborhood
        a b c
        d e f
        g h i
    around each pixel e. slope = atan(hypot(dz/dx, dz/dy)).

    Edge handling: the input is edge-padded by one pixel (replicating the
    border row/column) so every pixel — including the AOI's own border —
    gets a full 3x3 window. This is the same convention most GIS tools
    use in the absence of data beyond the raster edge, and it means
    border-pixel slope is a slightly damped estimate compared to an
    interior pixel on the same true gradient (there's no getting around
    that without real data beyond the edge).

    Nodata propagates two ways, both forced explicitly rather than left
    to fall out of the arithmetic: a pixel whose *own* elevation is
    nodata is nodata in the output; and — since Horn's kernel is 8-
    connected — any pixel with a nodata neighbor anywhere in its 3x3
    window is nodata too, not just its 4 orthogonal neighbors.
    """
    valid = elevation != nodata
    elev = np.where(valid, elevation, np.nan).astype(np.float64)
    padded = np.pad(elev, pad_width=1, mode="edge")

    a, b, c = padded[0:-2, 0:-2], padded[0:-2, 1:-1], padded[0:-2, 2:]
    d, f = padded[1:-1, 0:-2], padded[1:-1, 2:]
    g, h, i = padded[2:, 0:-2], padded[2:, 1:-1], padded[2:, 2:]

    dz_dx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8 * resolution_m)
    dz_dy = ((g + 2 * h + i) - (a + 2 * b + c)) / (8 * resolution_m)

    slope_deg = np.degrees(np.arctan(np.hypot(dz_dx, dz_dy)))
    slope_deg = np.where(valid, slope_deg, np.nan)
    return np.where(np.isnan(slope_deg), SLOPE_OUTPUT_NODATA, slope_deg).astype(np.float32)


def get_dem(aoi: AOI) -> DEMResult:
    def _compute() -> DEMResult:
        match = find_local_raster_covering_aoi(config.LOCAL_DEM_DIR, aoi)
        if match:
            logger.info("dem: LOCAL HIT for aoi=%s -> %s", aoi.bbox_4326, match.path)
            array, transform, crs, src_nodata = _read_local_window(match.path, aoi)
            source_used = f"local:{match.path.name}"
        else:
            logger.info("dem: no local coverage for aoi=%s, falling back to cloud (S3)", aoi.bbox_4326)
            array, transform, crs, src_nodata = _fetch_dem_from_s3(aoi)
            source_used = "s3://copernicus-dem-30m"

        grid = compute_aoi_grid(aoi.bounds_utm)
        elevation = reproject_to_grid(
            array, transform, crs, grid,
            kind="continuous", src_nodata=src_nodata, dst_nodata=DEM_OUTPUT_NODATA, dtype=np.float32,
        )
        nodata = require_defined_nodata(DEM_OUTPUT_NODATA, "dem")
        slope = compute_slope_degrees(elevation, grid.resolution_m, nodata)

        return DEMResult(elevation_m=elevation, slope_degrees=slope, grid=grid, nodata=nodata, source_used=source_used)

    return cached_or_compute("dem", aoi, _compute)
