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
