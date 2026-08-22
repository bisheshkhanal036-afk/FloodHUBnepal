"""The shared local-check-first decision used by both the DEM and
WorldCover sources: does a pre-downloaded local raster exist, and does it
fully cover this AOI? Identical logic for both, per the brief — this is
that single shared helper.

Local files are purely an optional fast-path: returning None here is not
an error, it's the expected, normal case in any environment that hasn't
pre-downloaded a local extent, and always means "fall back to the cloud
read" one level up.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import rasterio
from rasterio.warp import transform_bounds

from .aoi import AOI

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LocalRasterMatch:
    path: Path


def find_local_raster_covering_aoi(
    local_dir: Path, aoi: AOI, patterns: tuple[str, ...] = ("*.tif", "*.tiff")
) -> LocalRasterMatch | None:
    """None means "no usable local file" — either the directory doesn't
    exist, has no raster files, or none of the files fully cover the AOI.
    Every one of those is the normal, expected case in a fresh
    environment, not a failure.
    """
    if not local_dir.exists():
        return None

    candidates = sorted({p for pattern in patterns for p in local_dir.glob(pattern)})
    if not candidates:
        return None

    aoi_minx, aoi_miny, aoi_maxx, aoi_maxy = aoi.bbox_4326
    for path in candidates:
        try:
            with rasterio.open(path) as ds:
                left, bottom, right, top = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds)
        except rasterio.errors.RasterioIOError as exc:
            logger.warning("local raster %s could not be opened, skipping: %s", path, exc)
            continue

        if left <= aoi_minx and bottom <= aoi_miny and right >= aoi_maxx and top >= aoi_maxy:
            return LocalRasterMatch(path=path)

    return None
