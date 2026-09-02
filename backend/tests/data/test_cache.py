from __future__ import annotations

import os

from app.data import config
from app.data.aoi import AOI
from app.data.cache import cached_or_compute


def test_second_call_for_same_aoi_hits_cache_not_compute_fn(test_aoi: AOI):
    calls = []

    def compute():
        calls.append(1)
        return {"value": 42}

    first = cached_or_compute("dummy_source", test_aoi, compute)
    second = cached_or_compute("dummy_source", test_aoi, compute)

    assert first == {"value": 42}
    assert second == {"value": 42}
    assert len(calls) == 1


def test_different_aoi_does_not_share_cache_entry():
    calls = []

    def compute():
        calls.append(1)
        return len(calls)

    aoi_a = AOI(bbox_4326=(85.30, 27.70, 85.31, 27.71))
    aoi_b = AOI(bbox_4326=(85.32, 27.72, 85.33, 27.73))

    result_a = cached_or_compute("dummy_source", aoi_a, compute)
    result_b = cached_or_compute("dummy_source", aoi_b, compute)

    assert result_a == 1
    assert result_b == 2
    assert len(calls) == 2


def test_different_source_name_does_not_share_cache_entry(test_aoi: AOI):
    calls = []

    def compute():
        calls.append(1)
        return len(calls)

    result_dem = cached_or_compute("dem", test_aoi, compute)
    result_worldcover = cached_or_compute("worldcover", test_aoi, compute)

    assert result_dem == 1
    assert result_worldcover == 2


def _cache_path_for(source_name: str, aoi: AOI) -> str:
    return str(config.PROCESSED_CACHE_DIR / source_name / f"{aoi.cache_key()}.pkl")


def test_corrupt_cache_file_is_discarded_and_recomputed_not_raised(test_aoi: AOI):
    """Reproduces the real incident this recovery path was added for: a
    process killed (e.g. OOM) mid-write to cache.py's old non-atomic
    `open(cache_path, "wb")` could leave a truncated file behind, which
    then raised UnpicklingError on every subsequent read forever. A
    corrupt file at the cache path must be treated as equivalent to no
    file at all, not as a permanent failure.
    """
    calls = []

    def compute():
        calls.append(1)
        return {"value": len(calls)}

    cache_path = _cache_path_for("dummy_source", test_aoi)
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "wb") as f:
        f.write(b"not a valid pickle stream")

    result = cached_or_compute("dummy_source", test_aoi, compute)

    assert result == {"value": 1}
    assert len(calls) == 1
    # The corrupt file must be gone -- replaced by a real, freshly
    # computed (and correctly re-loadable) cache entry, not left in
    # place to poison the next call too.
    second = cached_or_compute("dummy_source", test_aoi, compute)
    assert second == {"value": 1}
    assert len(calls) == 1  # still 1 -- the second call was a real cache hit


def test_write_failure_leaves_no_partial_file_at_the_cache_path(test_aoi: AOI, monkeypatch):
    """The write path goes through a temp file + os.replace() specifically
    so a crash/exception mid-write can never leave a truncated file at
    the real cache path (the bug this whole module was fixed for). A
    pickling failure partway through the temp-file write must leave
    cache_path absent, not corrupt.
    """
    import pickle as pickle_module
    import threading

    def compute():
        return threading.Lock()  # a lock object cannot be pickled

    cache_path = _cache_path_for("dummy_source", test_aoi)

    try:
        cached_or_compute("dummy_source", test_aoi, compute)
    except (pickle_module.PicklingError, TypeError, AttributeError):
        pass

    assert not os.path.exists(cache_path)
    # No leftover .pkl.tmp files either -- the except branch cleans up.
    cache_dir = os.path.dirname(cache_path)
    leftovers = [f for f in os.listdir(cache_dir) if f.endswith(".tmp")] if os.path.isdir(cache_dir) else []
    assert leftovers == []
