from __future__ import annotations

import math

import pytest

from app.data.errors import NodataValidationError
from app.data.nodata import assert_consistent_nodata, require_defined_nodata


def test_require_defined_nodata_passes_through_a_real_value():
    assert require_defined_nodata(-9999.0, "dem") == -9999.0
    assert require_defined_nodata(0, "worldcover") == 0


def test_require_defined_nodata_raises_on_none():
    with pytest.raises(NodataValidationError):
        require_defined_nodata(None, "dem")


def test_assert_consistent_nodata_passes_for_matching_values():
    assert_consistent_nodata({"dem": -9999.0, "slope": -9999.0})  # must not raise


def test_assert_consistent_nodata_raises_on_mismatch():
    with pytest.raises(NodataValidationError):
        assert_consistent_nodata({"dem": -9999.0, "worldcover": 0})


def test_assert_consistent_nodata_treats_nan_as_matching_nan():
    assert_consistent_nodata({"a": math.nan, "b": math.nan})  # must not raise


def test_assert_consistent_nodata_is_a_noop_for_a_single_raster():
    assert_consistent_nodata({"dem": -9999.0})  # must not raise
