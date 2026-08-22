"""Per-AOI cache for processed source results, separate from
/backend/data/raw/ (the optional local pre-downloaded sources) — this
caches the *output* of local-check/cloud-fallback + reproject/resample,
so a repeat request for the same AOI never re-fetches or re-reprojects,
regardless of which path (local, S3, R2) served the original request.

One cache entry per (source_name, AOI, version): keyed by AOI.cache_key()
plus an optional `version` string, so requests for the same bbox *and the
same version* always hit, but changing `version` — e.g. a criterion's
reclassification_rules being updated, per reclassify.py's
rules_fingerprint() — correctly misses rather than silently returning a
result computed under the old rules. `version` defaults to "" for
sources with nothing to version against (DEM/WorldCover/OSM's raw fetch
depends only on the AOI, not on any caller-supplied config).
"""

from __future__ import annotations

import logging
import pickle
from collections.abc import Callable
from typing import TypeVar

from . import config
from .aoi import AOI

logger = logging.getLogger(__name__)

T = TypeVar("T")


def cached_or_compute(source_name: str, aoi: AOI, compute_fn: Callable[[], T], *, version: str = "") -> T:
    cache_dir = config.PROCESSED_CACHE_DIR / source_name
    cache_dir.mkdir(parents=True, exist_ok=True)
    aoi_key = aoi.cache_key()
    key = f"{aoi_key}_{version}" if version else aoi_key
    cache_path = cache_dir / f"{key}.pkl"

    if cache_path.exists():
        logger.info("%s: cache hit for aoi=%s (key=%s)", source_name, aoi.bbox_4326, key)
        with open(cache_path, "rb") as f:
            return pickle.load(f)

    logger.info("%s: cache miss for aoi=%s (key=%s), computing", source_name, aoi.bbox_4326, key)
    result = compute_fn()
    with open(cache_path, "wb") as f:
        pickle.dump(result, f)
    return result
