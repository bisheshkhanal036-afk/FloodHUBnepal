"""NDVI (Normalized Difference Vegetation Index) source: a continuous
vegetation-greenness raster in [-1, 1], local-check-first with a live
Sentinel-2 fallback.

Same shape as dem.py / worldcover.py (local_source.find_local_raster_
covering_aoi decides local-vs-cloud), but the "cloud" path is a two-step
process rather than a fixed tile-URL template:

  1. Discover the least-cloudy Sentinel-2 L2A scene covering the AOI via
     Element 84's public Earth Search STAC API (config.NDVI_STAC_*).
  2. Windowed-read that scene's red (B04) and NIR (B08) 10 m COGs from the
     public sentinel-cogs bucket and compute NDVI = (NIR - red) / (NIR + red).

NDVI is CONTINUOUS -> bilinear resampling onto the shared grid (never
categorical/nearest). It complements worldcover_land_cover's discrete
class codes with a continuous vegetation-vigor signal: denser, greener
vegetation (high NDVI) slows runoff and stabilizes soil (lower flood
risk); bare/built/sparse surfaces (low or negative NDVI) shed water
faster (higher risk).

Sentinel-2 L2A radiometric offset: processing baseline >= 04.00 (scenes
after 2022-01-25) encodes surface reflectance with a -1000 BOA offset
that must be removed before the ratio is meaningful (the offset does NOT
cancel in NDVI's denominator). Earth Search flags this per-item via
`earthsearch:boa_offset_applied`; we honor it (see _boa_offset_for_item).
"""

from __future__ import annotations

import json
import logging
import urllib.request

import numpy as np
import rasterio
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds

from . import config
from .aoi import AOI
from .attribution import NDVI_ATTRIBUTION
from .cache import cached_or_compute
from .errors import DataSourceUnavailableError
from .grid import AOIGrid, compute_aoi_grid, reproject_to_grid
from .local_source import find_local_raster_covering_aoi

logger = logging.getLogger(__name__)

# NDVI is a bounded ratio; -9999 is safely outside [-1, 1] as the nodata
# sentinel for pixels with no valid red/NIR (scene nodata, or red+NIR==0).
NDVI_OUTPUT_NODATA = -9999.0

# Earth Search asset keys for the two bands NDVI needs. Both are 10 m,
# same grid within one scene, so one window read applies to both.
_RED_ASSET = "red"   # Sentinel-2 B04
_NIR_ASSET = "nir"   # Sentinel-2 B08


class NDVIResult:
    def __init__(self, ndvi: np.ndarray, grid: AOIGrid, nodata: float, source_used: str):
        self.ndvi = ndvi
        self.grid = grid
        self.nodata = nodata
        self.source_used = source_used
        self.attribution = NDVI_ATTRIBUTION


def _find_s2_scene(aoi: AOI) -> dict:
    """Query the Earth Search STAC API for the least-cloudy Sentinel-2 L2A
    scene overlapping the AOI. Raises DataSourceUnavailableError if none is
    found even after relaxing the cloud-cover filter.
    """
    def _search(max_cloud: float) -> list[dict]:
        body: dict = {
            "collections": [config.NDVI_STAC_COLLECTION],
            "bbox": list(aoi.bbox_4326),
            "query": {"eo:cloud_cover": {"lt": max_cloud}},
            "sortby": [{"field": "properties.eo:cloud_cover", "direction": "asc"}],
            "limit": 1,
        }
        if config.NDVI_DATE_RANGE:
            body["datetime"] = config.NDVI_DATE_RANGE
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            config.NDVI_STAC_SEARCH_URL,
            data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=config.GDAL_HTTP_RETRY_ENV["GDAL_HTTP_TIMEOUT"]) as resp:
            return json.loads(resp.read()).get("features", [])

    # Try the configured ceiling first, then relax once to 100% (better a
    # cloudy scene than a 503) before giving up.
    for max_cloud in (config.NDVI_MAX_CLOUD_COVER, 100.0):
        features = _search(max_cloud)
        if features:
            item = features[0]
            logger.info(
                "ndvi: selected S2 scene %s (cloud=%.1f%%)",
                item.get("id"), item.get("properties", {}).get("eo:cloud_cover", -1),
            )
            return item

    raise DataSourceUnavailableError(
        f"ndvi: no Sentinel-2 scene found for aoi={aoi.bbox_4326} via {config.NDVI_STAC_SEARCH_URL}"
    )


def _boa_offset_for_item(item: dict) -> float:
    """The additive offset (in raw DN) to apply to both bands before the
    NDVI ratio, per the scene's processing baseline. Baseline >= 04.00
    reflectance is stored with a -1000 BOA offset that must be removed;
    if Earth Search reports the offset is already applied, it's 0.
    """
    props = item.get("properties", {})
    if props.get("earthsearch:boa_offset_applied"):
        return 0.0
    try:
        baseline = float(props.get("s2:processing_baseline", "0"))
    except (TypeError, ValueError):
        baseline = 0.0
    return -1000.0 if baseline >= 4.0 else 0.0


def _read_band_window(url: str, aoi: AOI):
    """Windowed read of one Sentinel-2 COG (in its own UTM CRS) clipped to
    the AOI. Returns (array, transform, crs). The AOI bbox (EPSG:4326) is
    reprojected into the dataset's CRS first, since S2 COGs are UTM, not
    lat/lon.
    """
    with rasterio.open(url) as ds:
        ds_bounds = transform_bounds("EPSG:4326", ds.crs, *aoi.bbox_4326)
        window = from_bounds(*ds_bounds, transform=ds.transform)
        data = ds.read(1, window=window, boundless=True, fill_value=0)
        window_transform = ds.window_transform(window)
        return data, window_transform, ds.crs


def _fetch_ndvi_from_s2(aoi: AOI):
    """Discover a scene, read red+NIR, compute NDVI. Isolated so tests can
    mock exactly this call for the cloud path without hitting the network.
    Returns (ndvi_array, transform, crs, nodata) with the same shape as the
    local-read path.
    """
    item = _find_s2_scene(aoi)
    assets = item.get("assets", {})
    if _RED_ASSET not in assets or _NIR_ASSET not in assets:
        raise DataSourceUnavailableError(
            f"ndvi: S2 scene {item.get('id')} lacks '{_RED_ASSET}'/'{_NIR_ASSET}' assets"
        )
    red_url = assets[_RED_ASSET]["href"]
    nir_url = assets[_NIR_ASSET]["href"]
    offset = _boa_offset_for_item(item)

    with rasterio.Env(**config.GDAL_HTTP_RETRY_ENV):
        red, transform, crs = _read_band_window(red_url, aoi)
        nir, _, _ = _read_band_window(nir_url, aoi)

    red = red.astype("float32") + offset
    nir = nir.astype("float32") + offset
    denom = nir + red
    # Guard divide-by-zero (scene nodata is DN 0 -> denom ~0 after offset):
    # mark those pixels nodata rather than producing NaN/inf.
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = np.where(np.abs(denom) < 1e-6, NDVI_OUTPUT_NODATA, (nir - red) / denom)
    # Physically NDVI is in [-1, 1]; clamp valid pixels to kill numerical
    # spillover, leaving the nodata sentinel untouched.
    valid = ndvi != NDVI_OUTPUT_NODATA
    ndvi[valid] = np.clip(ndvi[valid], -1.0, 1.0)
    return ndvi.astype("float32"), transform, crs, NDVI_OUTPUT_NODATA


def _read_local_window(path, aoi: AOI):
    with rasterio.open(path) as ds:
        ds_bounds = transform_bounds("EPSG:4326", ds.crs, *aoi.bbox_4326)
        window = from_bounds(*ds_bounds, transform=ds.transform)
        data = ds.read(1, window=window)
        window_transform = ds.window_transform(window)
        return data, window_transform, ds.crs, ds.nodata


def get_ndvi(aoi: AOI) -> NDVIResult:
    def _compute() -> NDVIResult:
        match = find_local_raster_covering_aoi(config.LOCAL_NDVI_DIR, aoi)
        if match:
            logger.info("ndvi: LOCAL HIT for aoi=%s -> %s", aoi.bbox_4326, match.path)
            array, transform, crs, src_nodata = _read_local_window(match.path, aoi)
            source_used = f"local:{match.path.name}"
        else:
            logger.info("ndvi: no local coverage for aoi=%s, computing from Sentinel-2 (STAC)", aoi.bbox_4326)
            array, transform, crs, src_nodata = _fetch_ndvi_from_s2(aoi)
            source_used = "sentinel-2-l2a"

        grid = compute_aoi_grid(aoi.bounds_utm)
        # Continuous data: bilinear resampling (SPEC.md §2.2).
        ndvi = reproject_to_grid(
            array, transform, crs, grid,
            kind="continuous", src_nodata=src_nodata, dst_nodata=NDVI_OUTPUT_NODATA, dtype="float32",
        )
        return NDVIResult(ndvi=ndvi, grid=grid, nodata=NDVI_OUTPUT_NODATA, source_used=source_used)

    return cached_or_compute("ndvi", aoi, _compute)
