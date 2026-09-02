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
import os
import pickle
import tempfile
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
        try:
            with open(cache_path, "rb") as f:
                result = pickle.load(f)
            logger.info("%s: cache hit for aoi=%s (key=%s)", source_name, aoi.bbox_4326, key)
            return result
        except (pickle.UnpicklingError, EOFError, OSError) as exc:
            # A file at this path that fails to unpickle is corrupt, not
            # absent -- most commonly a half-written file left behind by
            # a process that died (e.g. OOM-killed) mid-write, from
            # before this function wrote atomically (see the write path
            # below). Every subsequent request for this exact AOI/
            # version would otherwise hit this same corrupt file forever
            # (it "exists", so the cache-hit branch above keeps trying
            # and failing) -- discard it and fall through to recompute,
            # the same recovery a plain cache miss already gets.
            logger.warning(
                "%s: cache file corrupted for aoi=%s (key=%s), discarding and recomputing: %s",
                source_name, aoi.bbox_4326, key, exc,
            )
            cache_path.unlink(missing_ok=True)

    logger.info("%s: cache miss for aoi=%s (key=%s), computing", source_name, aoi.bbox_4326, key)
    result = compute_fn()

    # Write to a sibling temp file, then atomically rename it into place
    # -- os.replace() is atomic on both POSIX and Windows when source and
    # destination share a filesystem (guaranteed here: same directory).
    # Writing straight to cache_path (the previous behavior) left a
    # truncated, corrupt file at the real cache path if the process died
    # mid-write; with this, a crash at any point before the replace
    # leaves either nothing (a plain cache miss next time) or the
    # temp file (harmless, cleaned up in the except branch below), and a
    # crash can never corrupt an already-cached result either, since the
    # old file at cache_path is never touched until the new one is fully
    # written.
    fd, tmp_path = tempfile.mkstemp(dir=cache_dir, prefix=f"{key}.", suffix=".pkl.tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            pickle.dump(result, f)
        os.replace(tmp_path, cache_path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
    return result
