"""Recent rainfall criterion source: accumulated near-real-time
precipitation over the last N days, from CHIRPS v3 preliminary daily
data, windowed-read directly from source and reprojected onto the AOI
grid.

Why this exists, and how it differs from a climatological rainfall layer
--------------------------------------------------------------------
This project's other criteria (elevation, slope, drainage density, land
cover, ...) all describe *static* characteristics of a place. Answering
"how prone is this location to flooding" from static terrain alone is
incomplete without also asking "has it actually been raining hard here
lately" -- antecedent rainfall is a standard input to short-term flood
risk, since saturated soil and full channels make identical terrain far
more flood-prone.

CHIRPS-prelim is a genuinely different data source from a gauge-based
climatology (contrast with a hypothetical historical-average rainfall
source): it is a real, continuously-updated satellite-based daily
product, so the value returned for an AOI actually changes day to day
and reflects rainfall that has recently occurred, not a long-term
average. It is NOT a forecast and does not know about flooding in
progress -- see the honesty note below.

Source
------
CHIRPS v3 preliminary daily data (Climate Hazards Center, UC Santa
Barbara + USGS), IMERG-disaggregated (`prelim/sat/`), public domain /
CC BY 4.0, no credentials needed. Verified live during implementation:

  https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/prelim/sat/{year}/chirps-v3.0.prelim.{YYYY}.{MM}.{DD}.tif

0.05 degree (~5.5 km) global grid, EPSG:4326, plain (non-tiled) GeoTIFF
-- confirmed live that this still supports fast windowed reads via GDAL's
HTTP range requests even though it isn't a true COG: at this coarse
global resolution a Nepal-sized window is a handful of full-width row
strips, on the order of a few hundred KB, not a full-file download.
Nodata is -9999 but is NOT embedded in the file's own GDAL metadata
(confirmed live), so it is set explicitly here rather than trusted from
the source.

Preliminary data is not published for today or for a few days back --
production lag was observed as ~4 days during implementation (a file
timestamped 2026-08-22 covered 2026-08-20), a day or two beyond CHIRPS'
own documented ~2-day IMERG lag. `_find_latest_available_date` therefore
probes backwards from today rather than assuming any fixed lag, and the
actual date used is returned to the caller so staleness is never silently
hidden.

Honesty about what this is not
-------------------------------
This is a "how much has it rained here recently" signal, not a flood
forecast, not a live water-level reading, and not aware of flooding
already in progress. It should never be presented to a user as a
real-time danger indicator on its own -- it is one input, alongside the
static terrain/exposure criteria, to the same AHP overlay every other
criterion feeds. `RecentRainfallResult.data_date` and `.days_stale` let
the caller show exactly how current the underlying data actually is,
rather than implying "right now" when the truth may be "4 days ago".

Accumulation window
--------------------
Sums daily rainfall over the trailing RECENT_RAINFALL_WINDOW_DAYS days
(default 7) ending at the latest available date. 7 days is a standard
antecedent-precipitation window in flood-susceptibility practice -- long
enough to capture soil saturation from a multi-day monsoon spell, short
enough to still mean "recent" rather than drifting back into
climatology. Configurable because, like RAINFALL_VARIABLE in a
climatological source, the right window is a methodological choice, not
a technical one.
"""

from __future__ import annotations

import datetime
import logging
import os

import numpy as np
import rasterio
from rasterio.errors import RasterioIOError
from rasterio.windows import from_bounds

from .aoi import AOI
from .attribution import CHIRPS_PRELIM_ATTRIBUTION
from .cache import cached_or_compute
from .errors import DataSourceUnavailableError
from .grid import AOIGrid, compute_aoi_grid, reproject_to_grid
from .nodata import require_defined_nodata

logger = logging.getLogger(__name__)

CHIRPS_BASE_URL = os.environ.get(
    "CHIRPS_PRELIM_BASE_URL",
    "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/prelim/sat",
)

# CHIRPS' own nodata sentinel for this product -- not embedded in the
# file's GDAL metadata (confirmed live), so passed explicitly to every
# read rather than relying on rasterio picking it up from the source.
CHIRPS_SOURCE_NODATA = -9999.0

RECENT_RAINFALL_OUTPUT_NODATA = -9999.0

WINDOW_DAYS = int(os.environ.get("RECENT_RAINFALL_WINDOW_DAYS", "7"))

# How many days back from today to search for the most recent published
# file before giving up. Generous relative to the ~4-day lag actually
# observed, so a slow production day doesn't hard-fail the criterion.
MAX_LOOKBACK_DAYS = int(os.environ.get("RECENT_RAINFALL_MAX_LOOKBACK_DAYS", "14"))

GDAL_HTTP_TIMEOUT_S = int(os.environ.get("GDAL_HTTP_TIMEOUT", "300"))


def _chirps_url(date: datetime.date) -> str:
    return f"{CHIRPS_BASE_URL}/{date.year}/chirps-v3.0.prelim.{date.year}.{date.month:02d}.{date.day:02d}.tif"


def _daily_file_exists(date: datetime.date) -> bool:
    """A cheap existence probe: open with rasterio and read nothing. GDAL's
    vsicurl only issues a small metadata request to open a dataset, not a
    full download, so probing several candidate dates this way is fast.
    """
    try:
        with rasterio.Env(GDAL_HTTP_TIMEOUT=GDAL_HTTP_TIMEOUT_S):
            with rasterio.open("/vsicurl/" + _chirps_url(date)):
                return True
    except RasterioIOError:
        return False


def _find_latest_available_date(today: datetime.date) -> datetime.date:
    """The most recent date for which a prelim file is actually published,
    found by probing backwards from today rather than assuming a fixed
    lag -- see the module docstring for why the lag isn't reliably fixed.
    """
    for offset in range(MAX_LOOKBACK_DAYS + 1):
        candidate = today - datetime.timedelta(days=offset)
        if _daily_file_exists(candidate):
            return candidate

    raise DataSourceUnavailableError(
        f"recent_rainfall: no CHIRPS-prelim file found in the last {MAX_LOOKBACK_DAYS} days "
        f"(searched back from {today.isoformat()}); the source may be temporarily down or its "
        "publication lag has grown beyond the configured lookback."
    )


def _read_day_on_grid(date: datetime.date, grid: AOIGrid) -> np.ndarray:
    """One day's CHIRPS-prelim rainfall (mm), windowed-read for `grid`'s
    extent and reprojected/resampled onto it. Returns an array already in
    mm with RECENT_RAINFALL_OUTPUT_NODATA where CHIRPS itself had no data.
    """
    url = "/vsicurl/" + _chirps_url(date)

    # The AOI's own bounds, in CHIRPS' geographic CRS, to compute a
    # source-side window -- read only the handful of rows this AOI needs,
    # not the whole 7200x2400 global grid.
    with rasterio.Env(GDAL_HTTP_TIMEOUT=GDAL_HTTP_TIMEOUT_S):
        with rasterio.open(url) as ds:
            minx, miny, maxx, maxy = grid_bounds_4326 = _grid_bounds_4326(grid)
            window = from_bounds(minx, miny, maxx, maxy, transform=ds.transform)
            # Pad by one source pixel on each side so bilinear resampling
            # at the AOI edges has real neighbours to interpolate from,
            # rather than starving at the window boundary.
            window = window.round_lengths().round_offsets()
            padded = rasterio.windows.Window(
                max(window.col_off - 1, 0),
                max(window.row_off - 1, 0),
                min(window.width + 2, ds.width - max(window.col_off - 1, 0)),
                min(window.height + 2, ds.height - max(window.row_off - 1, 0)),
            )
            source_array = ds.read(1, window=padded)
            source_transform = ds.window_transform(padded)

    reprojected = reproject_to_grid(
        source_array,
        source_transform,
        "EPSG:4326",
        grid,
        kind="continuous",
        src_nodata=CHIRPS_SOURCE_NODATA,
        dst_nodata=RECENT_RAINFALL_OUTPUT_NODATA,
        dtype=np.float32,
    )
    return reprojected


def _grid_bounds_4326(grid: AOIGrid) -> tuple[float, float, float, float]:
    """`grid`'s own bounds, reprojected to EPSG:4326 -- needed since the
    grid is in a projected UTM CRS but CHIRPS' native grid is geographic.
    """
    from rasterio.warp import transform_bounds

    minx = grid.origin_x
    maxy = grid.origin_y
    maxx = grid.origin_x + grid.width * grid.resolution_m
    miny = grid.origin_y - grid.height * grid.resolution_m
    return transform_bounds(grid.crs, "EPSG:4326", minx, miny, maxx, maxy)


class RecentRainfallResult:
    def __init__(
        self,
        rainfall_mm: np.ndarray,
        grid: AOIGrid,
        nodata: float,
        attribution: str,
        warning: str | None,
        data_date: datetime.date,
        window_days: int,
        days_stale: int,
    ):
        self.rainfall_mm = rainfall_mm
        self.grid = grid
        self.nodata = nodata
        self.attribution = attribution
        self.warning = warning
        self.data_date = data_date
        self.window_days = window_days
        self.days_stale = days_stale


def get_recent_rainfall(aoi: AOI, window_days: int | None = None) -> RecentRainfallResult:
    """The `recent_rainfall` criterion's raw layer for `aoi`: rainfall (mm)
    accumulated over the trailing `window_days` days of CHIRPS-prelim data,
    on the common per-AOI grid.

    Deliberately keyed into the per-AOI cache by today's date (via the
    version string below), not just the AOI: unlike every other source in
    this registry, the correct answer for the same AOI genuinely changes
    day to day, so yesterday's cached accumulation must never be served
    for today's request.
    """
    window_days = window_days or WINDOW_DAYS
    today = datetime.date.today()

    def _compute() -> RecentRainfallResult:
        grid = compute_aoi_grid(aoi.bounds_utm)

        latest_date = _find_latest_available_date(today)
        days_stale = (today - latest_date).days

        total = np.zeros((grid.height, grid.width), dtype=np.float64)
        valid_mask = np.zeros((grid.height, grid.width), dtype=bool)
        days_used = 0

        for offset in range(window_days):
            day = latest_date - datetime.timedelta(days=offset)
            try:
                day_mm = _read_day_on_grid(day, grid)
            except RasterioIOError as exc:
                logger.warning("recent_rainfall: %s unavailable, skipping (%s)", day, exc)
                continue

            day_valid = day_mm != RECENT_RAINFALL_OUTPUT_NODATA
            total[day_valid] += day_mm[day_valid]
            valid_mask |= day_valid
            days_used += 1

        if days_used == 0:
            raise DataSourceUnavailableError(
                f"recent_rainfall: none of the {window_days} requested days had readable data"
            )

        rainfall_mm = np.where(valid_mask, total, RECENT_RAINFALL_OUTPUT_NODATA).astype(np.float32)
        require_defined_nodata(RECENT_RAINFALL_OUTPUT_NODATA, "recent_rainfall")

        warning = (
            f"Recent-rainfall data is {days_stale} day(s) old (latest available: "
            f"{latest_date.isoformat()}) -- this is accumulated recent rainfall, not a live "
            "reading, forecast, or flood warning."
        )
        if days_used < window_days:
            warning += f" Only {days_used} of the requested {window_days} days had usable data."

        logger.info(
            "recent_rainfall: accumulated %d/%d day(s) ending %s (%d days stale)",
            days_used,
            window_days,
            latest_date.isoformat(),
            days_stale,
        )

        return RecentRainfallResult(
            rainfall_mm=rainfall_mm,
            grid=grid,
            nodata=RECENT_RAINFALL_OUTPUT_NODATA,
            attribution=CHIRPS_PRELIM_ATTRIBUTION,
            warning=warning,
            data_date=latest_date,
            window_days=window_days,
            days_stale=days_stale,
        )

    # today.isoformat() in the cache version is what makes this source
    # re-fetch once per calendar day instead of serving a stale
    # accumulation from an earlier cache hit for the same AOI.
    return cached_or_compute(
        "recent_rainfall", aoi, _compute, version=f"v1_{window_days}d_{today.isoformat()}"
    )
