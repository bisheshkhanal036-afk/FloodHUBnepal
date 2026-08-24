"""Rainfall criterion source: a continuous precipitation surface
interpolated from Nepal's DHM rain-gauge network onto the common per-AOI
grid.

Why this source exists
----------------------
Every published AHP flood-susceptibility model this project follows uses
precipitation as a conditioning factor -- it is the flood *trigger*,
where every other registered criterion describes the terrain, land cover
or exposure that turns rainfall into a flood. The reference method
(Parajuli et al., 2023, ISPRS IJGI 12(7), 286 -- "the Siraha paper"
referred to elsewhere in this codebase) weights Precipitation (PP) as one
of its two heaviest factors out of nine. Until this module, FloodHUB had
eleven criteria and no rainfall at all.

Data
----
`resources/nepal_precip_stations.csv` -- 254 Department of Hydrology and
Meteorology (DHM) gauges, 1980-2022, quality-controlled, with ETCCDI
climatological indices computed per station. Unlike every other local
source in this package (multi-GB DEM/OSM/WorldCover extracts under
`backend/data/raw/`, gitignored), this file is 22 KB and is committed as
a package resource, so the criterion works on a fresh checkout with no
download step.

Columns used here:
  Rx1day   -- mean annual maximum 1-day precipitation (mm). DEFAULT.
  Rx5day   -- mean annual maximum consecutive-5-day precipitation (mm)
  PRCPTOT  -- mean annual total precipitation (mm)
  R95pTOT  -- annual precipitation from very wet (>95th percentile) days

Which index the "rainfall" criterion represents is env-configurable
(RAINFALL_VARIABLE) rather than hardcoded, because the right choice is
methodological, not technical: Rx1day is the default since short-duration
extreme rainfall is what physically drives flash and pluvial flooding,
while PRCPTOT is the closer analogue to the reference paper's own annual
"Precipitation" factor and is the value to switch to for direct
comparison with it. The chosen variable is folded into the cache version,
so switching never serves a surface computed under the previous one.

Interpolation
-------------
Inverse Distance Weighting (IDW) over the K nearest gauges, computed in
the AOI's projected CRS so distances are true metres.

IDW rather than kriging or a lapse-rate model, deliberately: it is the
standard interpolator in the index-based flood-susceptibility literature
this project follows, it is deterministic and dependency-free, and it
degrades predictably where the gauge network is sparse. Its real
limitation in Nepal is that precipitation is strongly orographic and IDW
is elevation-blind -- two gauges equidistant from a cell but 2,000 m
apart in elevation are weighted identically. That limitation is reported
to the caller as a `warning` (the 5th element of the source tuple, the
same mechanism twi/drainage_density/hand use for their own AOI-edge
caveat) whenever the contributing gauges span a wide elevation range,
rather than being silently absorbed. An elevation-aware interpolation is
the natural next step, and is why `elevation_m` is retained in the
resource file.

The gauge network is nationwide and sparse (254 stations for all of
Nepal), so an AOI-sized window will frequently contain zero gauges. The K
nearest gauges are therefore always selected from the full network
regardless of whether they fall inside the AOI -- selecting only gauges
within the AOI would return an empty surface for most real requests.
"""

from __future__ import annotations

import functools
import logging
import os
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer

from .aoi import AOI
from .attribution import DHM_PRECIP_ATTRIBUTION
from .cache import cached_or_compute
from .errors import DataSourceUnavailableError
from .grid import AOIGrid, compute_aoi_grid

logger = logging.getLogger(__name__)

STATIONS_PATH = Path(
    os.environ.get(
        "PRECIP_STATIONS_PATH",
        str(Path(__file__).resolve().parent / "resources" / "nepal_precip_stations.csv"),
    )
)

# Which ETCCDI index the `rainfall` criterion represents. See the module
# docstring for why this is a configuration choice and not a constant.
RAINFALL_VARIABLE = os.environ.get("RAINFALL_VARIABLE", "Rx1day")

SUPPORTED_VARIABLES = ("Rx1day", "Rx5day", "PRCPTOT", "R95pTOT", "SDII")

# Number of nearest gauges contributing to each interpolated cell. 8 is a
# common IDW neighbourhood size and, at this network's mean gauge
# spacing, keeps the contributing set regional rather than national
# without so few gauges that one outlier dominates.
IDW_NEIGHBOURS = int(os.environ.get("RAINFALL_IDW_NEIGHBOURS", "8"))

# IDW exponent. 2 (inverse *squared* distance) is the standard default
# and the value used throughout the flood-susceptibility literature.
IDW_POWER = float(os.environ.get("RAINFALL_IDW_POWER", "2.0"))

# Elevation spread (metres) across the contributing gauges above which
# the orographic limitation described in the module docstring is
# reported as a warning rather than left implicit.
ELEVATION_SPREAD_WARN_M = float(os.environ.get("RAINFALL_ELEVATION_WARN_M", "1500.0"))

# Distance (km) to the nearest gauge beyond which the interpolation is
# really extrapolation into a sparse part of the network, and says so.
SPARSE_NETWORK_WARN_KM = float(os.environ.get("RAINFALL_SPARSE_WARN_KM", "50.0"))

# Rainfall in mm is always >= 0, so a negative sentinel is unambiguous --
# matching distance_raster.py's DISTANCE_RASTER_NODATA convention.
RAINFALL_NODATA = -1.0

# Bumped whenever the interpolation itself changes in a way that would
# make a previously cached surface wrong. The selected variable is
# appended separately at the call site.
_CACHE_VERSION = "v1"

# Chunk size for the cell-vs-gauge distance matrix. Keeps peak memory
# bounded regardless of AOI size (a district-sized AOI at 10 m is tens of
# millions of cells; the full matrix against 254 gauges would not fit).
_IDW_CHUNK_CELLS = 200_000


@functools.lru_cache(maxsize=1)
def _load_stations() -> pd.DataFrame:
    """The gauge table, read once per process.

    Cached because it is small, immutable, and read on every cache-miss
    compute -- the same "load once, reuse" treatment basins.py gives its
    own shapefile, for the same reason.
    """
    if not STATIONS_PATH.exists():
        raise DataSourceUnavailableError(
            f"rainfall: gauge table not found at {STATIONS_PATH}. This file ships with the "
            "repository; set PRECIP_STATIONS_PATH if it lives elsewhere."
        )

    df = pd.read_csv(STATIONS_PATH)

    required = {"longitude", "latitude", "elevation_m"}
    missing = required - set(df.columns)
    if missing:
        raise DataSourceUnavailableError(
            f"rainfall: gauge table {STATIONS_PATH} is missing required column(s): {sorted(missing)}"
        )

    return df


def _variable_column(df: pd.DataFrame, variable: str) -> str:
    if variable not in SUPPORTED_VARIABLES:
        raise DataSourceUnavailableError(
            f"rainfall: RAINFALL_VARIABLE={variable!r} is not one of {SUPPORTED_VARIABLES}"
        )
    if variable not in df.columns:
        raise DataSourceUnavailableError(
            f"rainfall: gauge table has no {variable!r} column (has: {sorted(df.columns)})"
        )
    return variable


def interpolate_idw(
    station_xy: np.ndarray,
    station_values: np.ndarray,
    grid: AOIGrid,
    *,
    neighbours: int = IDW_NEIGHBOURS,
    power: float = IDW_POWER,
) -> np.ndarray:
    """IDW-interpolate `station_values` (at projected coordinates
    `station_xy`, shape (n, 2)) onto every cell centre of `grid`.

    Deliberately independent of any rainfall specifics -- it takes bare
    coordinates and values -- so a future point-source criterion
    (temperature, a gauge-based discharge index) can reuse it directly,
    the same way compute_distance_raster is not river- or road-specific.

    A cell falling exactly on a gauge takes that gauge's value outright,
    avoiding the divide-by-zero that inverse distance implies there.
    """
    if len(station_xy) == 0:
        raise DataSourceUnavailableError("rainfall: no gauges available to interpolate from")

    xs = grid.transform.c + (np.arange(grid.width) + 0.5) * grid.transform.a
    ys = grid.transform.f + (np.arange(grid.height) + 0.5) * grid.transform.e
    grid_x, grid_y = np.meshgrid(xs, ys)
    cells = np.column_stack([grid_x.ravel(), grid_y.ravel()])

    k = min(neighbours, len(station_xy))
    out = np.empty(len(cells), dtype=np.float64)

    for start in range(0, len(cells), _IDW_CHUNK_CELLS):
        block = cells[start : start + _IDW_CHUNK_CELLS]
        d = np.sqrt(
            (block[:, 0, None] - station_xy[None, :, 0]) ** 2
            + (block[:, 1, None] - station_xy[None, :, 1]) ** 2
        )

        if k < d.shape[1]:
            nearest = np.argpartition(d, k - 1, axis=1)[:, :k]
        else:
            nearest = np.tile(np.arange(d.shape[1]), (len(block), 1))

        d_near = np.take_along_axis(d, nearest, axis=1)
        v_near = station_values[nearest]

        exact = d_near < 1e-6
        has_exact = exact.any(axis=1)

        with np.errstate(divide="ignore"):
            w = 1.0 / np.power(d_near, power)
        w[exact] = 0.0

        block_out = np.einsum("ij,ij->i", w, v_near) / w.sum(axis=1)

        if has_exact.any():
            exact_vals = np.where(exact, v_near, 0.0).sum(axis=1) / np.maximum(exact.sum(axis=1), 1)
            block_out = np.where(has_exact, exact_vals, block_out)

        out[start : start + _IDW_CHUNK_CELLS] = block_out

    return out.reshape(grid.height, grid.width).astype(np.float32)


class RainfallResult:
    def __init__(
        self,
        rainfall_mm: np.ndarray,
        grid: AOIGrid,
        nodata: float,
        attribution: str,
        warning: str | None,
        variable: str,
        n_stations_used: int,
    ):
        self.rainfall_mm = rainfall_mm
        self.grid = grid
        self.nodata = nodata
        self.attribution = attribution
        self.warning = warning
        self.variable = variable
        self.n_stations_used = n_stations_used


def get_rainfall(aoi: AOI, variable: str | None = None) -> RainfallResult:
    """The `rainfall` criterion's raw layer for `aoi`: interpolated
    precipitation in mm on the common per-AOI grid.
    """
    variable = variable or RAINFALL_VARIABLE

    def _compute() -> RainfallResult:
        df = _load_stations()
        column = _variable_column(df, variable)

        usable = df[["longitude", "latitude", "elevation_m", column]].dropna()
        if usable.empty:
            raise DataSourceUnavailableError(f"rainfall: no gauge has a usable {column!r} value")

        grid = compute_aoi_grid(aoi.bounds_utm)

        # Gauge coordinates are geographic; the grid is projected. Both
        # must be in the same CRS for IDW distances to be real metres.
        to_grid = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)
        sx, sy = to_grid.transform(usable["longitude"].to_numpy(), usable["latitude"].to_numpy())
        station_xy = np.column_stack([sx, sy])
        station_values = usable[column].to_numpy(dtype=np.float64)

        rainfall_mm = interpolate_idw(station_xy, station_values, grid)

        # Which gauges actually drove this AOI, for the quality checks
        # below: the K nearest to the AOI centre stand in for the
        # per-cell neighbourhoods, which vary from cell to cell.
        cx = grid.transform.c + (grid.width / 2) * grid.transform.a
        cy = grid.transform.f + (grid.height / 2) * grid.transform.e
        d_centre = np.hypot(station_xy[:, 0] - cx, station_xy[:, 1] - cy)
        k = min(IDW_NEIGHBOURS, len(station_xy))
        contributing = usable.iloc[np.argsort(d_centre)[:k]]

        elev_spread = float(contributing["elevation_m"].max() - contributing["elevation_m"].min())
        nearest_km = float(d_centre.min() / 1000.0)

        warning = None
        if elev_spread > ELEVATION_SPREAD_WARN_M:
            warning = (
                f"Rainfall is interpolated (IDW) from {k} gauges spanning {elev_spread:.0f} m of "
                f"elevation; the nearest is {nearest_km:.0f} km away. Precipitation in Nepal is "
                "strongly orographic and this interpolation is elevation-blind, so values in steep "
                "terrain should be treated as indicative."
            )
        elif nearest_km > SPARSE_NETWORK_WARN_KM:
            warning = (
                f"The nearest rain gauge is {nearest_km:.0f} km from this area, so interpolated "
                "rainfall here is extrapolated from a sparse part of the network."
            )

        logger.info(
            "rainfall: interpolated %s from %d gauges (nearest %.0f km, elevation spread %.0f m)",
            column,
            k,
            nearest_km,
            elev_spread,
        )

        return RainfallResult(
            rainfall_mm=rainfall_mm,
            grid=grid,
            nodata=RAINFALL_NODATA,
            attribution=DHM_PRECIP_ATTRIBUTION,
            warning=warning,
            variable=column,
            n_stations_used=k,
        )

    return cached_or_compute("rainfall", aoi, _compute, version=f"{_CACHE_VERSION}_{variable}")
