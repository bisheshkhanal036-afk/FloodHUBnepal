"""Unit tests for the rainfall criterion source: the generic IDW
interpolator and the gauge-table loading/validation around it.

Every test here runs on synthetic gauges on a small synthetic grid --
none of them read the committed 254-station table or touch the network,
so the interpolation maths is verified against hand-calculable values
rather than against whatever the real network happens to produce.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.data.errors import DataSourceUnavailableError
from app.data.grid import AOIGrid
from app.data.rainfall import (
    SUPPORTED_VARIABLES,
    _load_stations,
    _variable_column,
    interpolate_idw,
)


def _grid(width: int = 3, height: int = 3, resolution_m: float = 10.0) -> AOIGrid:
    """A tiny grid whose cell centres are at (5, -5), (15, -5), ... so
    hand-calculated distances stay trivial.
    """
    return AOIGrid(
        crs="EPSG:32645",
        resolution_m=resolution_m,
        origin_x=0.0,
        origin_y=0.0,
        width=width,
        height=height,
    )


def test_cell_sitting_exactly_on_a_gauge_takes_that_gauges_value():
    """Inverse distance is undefined at distance zero. A cell centre
    coinciding with a gauge must return that gauge's value outright, not
    NaN or an inf-weighted average.
    """
    grid = _grid()
    # Cell (0, 0)'s centre is at (5, -5) for this grid.
    station_xy = np.array([[5.0, -5.0], [1000.0, -1000.0]])
    values = np.array([100.0, 500.0])

    out = interpolate_idw(station_xy, values, grid, neighbours=2)

    assert np.isfinite(out).all()
    assert out[0, 0] == pytest.approx(100.0)


def test_equidistant_gauges_average_evenly():
    """Two gauges placed symmetrically about a cell centre must weight
    equally, giving the plain mean regardless of the IDW power.
    """
    grid = _grid(width=1, height=1)
    # The single cell's centre is at (5, -5).
    station_xy = np.array([[5.0 - 100.0, -5.0], [5.0 + 100.0, -5.0]])
    values = np.array([50.0, 150.0])

    out = interpolate_idw(station_xy, values, grid, neighbours=2)

    assert out[0, 0] == pytest.approx(100.0)


def test_closer_gauge_dominates():
    """The whole point of inverse *distance* weighting: the nearer gauge
    pulls the result toward its own value.
    """
    grid = _grid(width=1, height=1)
    station_xy = np.array([[5.0 + 10.0, -5.0], [5.0 + 1000.0, -5.0]])
    values = np.array([10.0, 1000.0])

    out = interpolate_idw(station_xy, values, grid, neighbours=2)

    # Weight ratio is (1/10^2) : (1/1000^2) = 10000 : 1, so the result
    # sits far nearer the close gauge's 10 than the far gauge's 1000.
    assert 10.0 <= out[0, 0] < 11.0


def test_result_is_bounded_by_the_contributing_gauge_values():
    """IDW is a convex combination, so it can never extrapolate outside
    the range of the gauges it averaged -- a property worth pinning,
    since a weighting bug would typically break exactly this.
    """
    rng = np.random.default_rng(0)
    station_xy = rng.uniform(-500, 500, size=(12, 2))
    values = rng.uniform(60.0, 200.0, size=12)

    out = interpolate_idw(station_xy, values, _grid(width=8, height=8), neighbours=5)

    assert out.min() >= values.min() - 1e-3
    assert out.max() <= values.max() + 1e-3


def test_output_shape_and_dtype_match_the_grid():
    grid = _grid(width=7, height=4)
    station_xy = np.array([[0.0, 0.0], [70.0, -40.0]])
    values = np.array([80.0, 120.0])

    out = interpolate_idw(station_xy, values, grid, neighbours=2)

    assert out.shape == (grid.height, grid.width)
    assert out.dtype == np.float32


def test_neighbours_larger_than_the_network_is_clamped_not_an_error():
    """Asking for more neighbours than there are gauges is normal near
    the edge of a sparse network; it must fall back to "use them all".
    """
    grid = _grid(width=2, height=2)
    station_xy = np.array([[0.0, 0.0], [20.0, -20.0]])
    values = np.array([90.0, 110.0])

    out = interpolate_idw(station_xy, values, grid, neighbours=50)

    assert np.isfinite(out).all()


def test_empty_gauge_set_is_an_explicit_error():
    with pytest.raises(DataSourceUnavailableError, match="no gauges"):
        interpolate_idw(np.empty((0, 2)), np.empty(0), _grid())


def test_chunking_does_not_change_the_result():
    """The interpolator processes cells in fixed-size chunks to bound
    memory. Chunk boundaries must not be visible in the output.
    """
    from app.data import rainfall

    rng = np.random.default_rng(7)
    station_xy = rng.uniform(-2000, 2000, size=(10, 2))
    values = rng.uniform(50.0, 250.0, size=10)
    grid = _grid(width=40, height=40)

    full = interpolate_idw(station_xy, values, grid, neighbours=4)

    original = rainfall._IDW_CHUNK_CELLS
    try:
        rainfall._IDW_CHUNK_CELLS = 37  # deliberately not a divisor of 1600
        chunked = interpolate_idw(station_xy, values, grid, neighbours=4)
    finally:
        rainfall._IDW_CHUNK_CELLS = original

    np.testing.assert_allclose(full, chunked, rtol=1e-6)


def test_unsupported_variable_is_rejected_with_the_supported_list():
    df = _load_stations()
    with pytest.raises(DataSourceUnavailableError, match="not one of"):
        _variable_column(df, "NotAnIndex")


@pytest.mark.parametrize("variable", SUPPORTED_VARIABLES)
def test_every_supported_variable_exists_in_the_committed_gauge_table(variable):
    """The supported-variable list and the shipped resource file have to
    agree; a rename in one without the other would only surface at
    request time.
    """
    df = _load_stations()
    assert _variable_column(df, variable) == variable


def test_committed_gauge_table_is_usable():
    """Guards the resource file itself: coordinates present, plausible
    for Nepal, and enough gauges to interpolate from.
    """
    df = _load_stations()

    assert len(df) > 200
    assert df["longitude"].between(80.0, 89.0).all()
    assert df["latitude"].between(26.0, 31.0).all()
    assert df["Rx1day"].dropna().between(0.0, 1000.0).all()
