from __future__ import annotations

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
