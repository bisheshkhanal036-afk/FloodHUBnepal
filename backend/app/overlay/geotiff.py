"""Materializes a risk surface array as a GeoTIFF file, for the
POST /api/overlay/compute response's `data_url`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio

from app.data.grid import AOIGrid


def write_risk_surface_geotiff(path: Path, array: np.ndarray, grid: AOIGrid, nodata: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=grid.height,
        width=grid.width,
        count=1,
        dtype="float32",
        crs=grid.crs,
        transform=grid.transform,
        nodata=nodata,
    ) as dst:
        dst.write(array, 1)


def write_hazard_class_geotiff(path: Path, array: np.ndarray, grid: AOIGrid, nodata: int) -> None:
    """Same shape as write_risk_surface_geotiff, but uint8/single-integer-
    band for the discrete 1-5 hazard-class raster (hazard_classes.py) --
    a separate function (not a shared one parameterized by dtype) since
    the two are conceptually different products a user downloads for
    different reasons (continuous score vs. discrete GIS classes), and
    keeping them as two small, obvious functions costs nothing.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=grid.height,
        width=grid.width,
        count=1,
        dtype="uint8",
        crs=grid.crs,
        transform=grid.transform,
        nodata=nodata,
    ) as dst:
        dst.write(array, 1)
