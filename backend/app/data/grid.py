"""The common per-AOI analysis grid and the reproject/resample step every
source in this layer goes through, regardless of whether the source array
came from a local file or a cloud read.

Implements SPEC.md's Grid/resolution convention: EPSG:32645, a fixed 10m
resolution, and a grid origin derived deterministically from the AOI
alone (never from a source raster's native alignment or from "when" the
request happened), so repeated requests for the same AOI always produce
an identical pixel grid.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from affine import Affine
from rasterio.warp import Resampling
from rasterio.warp import reproject as rio_reproject

RESOLUTION_M = 10.0
GRID_CRS = "EPSG:32645"

# SPEC.md, Grid/resolution convention: continuous data uses bilinear
# resampling; categorical/reclassified data uses nearest-neighbor only.
_RESAMPLING_BY_KIND = {
    "continuous": Resampling.bilinear,
    "categorical": Resampling.nearest,
}


@dataclass(frozen=True)
class AOIGrid:
    """Field names deliberately match schemas/risk_surface.schema.json's
    `grid` object, since this is the same grid a stored RiskSurface will
    eventually reference.
    """

    crs: str
    resolution_m: float
    origin_x: float
    origin_y: float
    width: int
    height: int

    @property
    def transform(self) -> Affine:
        return Affine(self.resolution_m, 0, self.origin_x, 0, -self.resolution_m, self.origin_y)


def compute_aoi_grid(bounds_utm: tuple[float, float, float, float], resolution_m: float = RESOLUTION_M) -> AOIGrid:
    """A deterministic 10m grid for one AOI: origin is the AOI's own UTM
    bounds snapped outward to the nearest resolution_m multiple — a pure
    function of `bounds_utm`, with no dependency on any source raster's
    alignment. Two calls with the same bounds_utm always return the same
    grid, which is what makes AOI-keyed caching (cache.py) correct.
    """
    minx, miny, maxx, maxy = bounds_utm
    origin_x = math.floor(minx / resolution_m) * resolution_m
    origin_y = math.ceil(maxy / resolution_m) * resolution_m
    width = max(1, math.ceil((maxx - origin_x) / resolution_m))
    height = max(1, math.ceil((origin_y - miny) / resolution_m))
    return AOIGrid(
        crs=GRID_CRS,
        resolution_m=resolution_m,
        origin_x=origin_x,
        origin_y=origin_y,
        width=width,
        height=height,
    )


def reproject_to_grid(
    source_array: np.ndarray,
    source_transform: Affine,
    source_crs,
    grid: AOIGrid,
    *,
    kind: str,
    src_nodata: float | None,
    dst_nodata: float,
    dtype=None,
) -> np.ndarray:
    """Reproject + resample one 2D array onto `grid`. `kind` selects the
    resampling method per SPEC.md (§2.2): "continuous" -> bilinear,
    "categorical" -> nearest-neighbor. Never any other method for
    categorical data (e.g. averaging across discrete class codes), by
    construction — there's no third option to pass.
    """
    if kind not in _RESAMPLING_BY_KIND:
        raise ValueError(f"kind must be 'continuous' or 'categorical', got {kind!r}")

    out_dtype = dtype if dtype is not None else source_array.dtype
    destination = np.full((grid.height, grid.width), dst_nodata, dtype=out_dtype)

    rio_reproject(
        source=source_array,
        destination=destination,
        src_transform=source_transform,
        src_crs=source_crs,
        src_nodata=src_nodata,
        dst_transform=grid.transform,
        dst_crs=grid.crs,
        dst_nodata=dst_nodata,
        resampling=_RESAMPLING_BY_KIND[kind],
    )
    return destination
