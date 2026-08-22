from __future__ import annotations

import numpy as np
from affine import Affine

from app.data.grid import compute_aoi_grid, reproject_to_grid


def test_compute_aoi_grid_is_deterministic_for_same_bounds():
    bounds = (100_000.0, 3_000_000.0, 100_650.0, 3_000_650.0)
    grid_a = compute_aoi_grid(bounds)
    grid_b = compute_aoi_grid(bounds)
    assert grid_a == grid_b


def test_compute_aoi_grid_snaps_origin_to_resolution_multiple():
    bounds = (100_003.0, 3_000_007.0, 100_650.0, 3_000_650.0)
    grid = compute_aoi_grid(bounds, resolution_m=10.0)
    assert grid.origin_x % 10.0 == 0
    assert grid.origin_y % 10.0 == 0
    assert grid.origin_x <= bounds[0]
    assert grid.origin_y >= bounds[3]


def test_compute_aoi_grid_covers_the_full_bounds():
    bounds = (100_003.0, 3_000_007.0, 100_650.0, 3_000_650.0)
    grid = compute_aoi_grid(bounds, resolution_m=10.0)
    far_x = grid.origin_x + grid.width * grid.resolution_m
    far_y = grid.origin_y - grid.height * grid.resolution_m
    assert far_x >= bounds[2]
    assert far_y <= bounds[1]


def test_reproject_to_grid_continuous_uses_bilinear_and_preserves_range():
    grid = compute_aoi_grid((0.0, 0.0, 100.0, 100.0), resolution_m=10.0)
    source = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
    source_transform = Affine(50, 0, 0, 0, -50, 100)  # a 2x2 grid over the same 100x100 extent

    out = reproject_to_grid(
        source, source_transform, "EPSG:32645", grid,
        kind="continuous", src_nodata=None, dst_nodata=-9999.0, dtype=np.float32,
    )

    assert out.shape == (grid.height, grid.width)
    assert out.dtype == np.float32
    # Bilinear interpolation of values in [1, 4] should stay within that range.
    assert out.min() >= 1.0 - 1e-3
    assert out.max() <= 4.0 + 1e-3


def test_reproject_to_grid_categorical_uses_nearest_and_preserves_discrete_values():
    grid = compute_aoi_grid((0.0, 0.0, 100.0, 100.0), resolution_m=10.0)
    source = np.array([[10, 50], [80, 60]], dtype=np.uint8)
    source_transform = Affine(50, 0, 0, 0, -50, 100)

    out = reproject_to_grid(
        source, source_transform, "EPSG:32645", grid,
        kind="categorical", src_nodata=0, dst_nodata=0, dtype=np.uint8,
    )

    # Nearest-neighbor must never invent a class code that wasn't in the input.
    assert set(np.unique(out)).issubset({0, 10, 50, 60, 80})


def test_reproject_to_grid_rejects_unknown_kind():
    grid = compute_aoi_grid((0.0, 0.0, 100.0, 100.0), resolution_m=10.0)
    source = np.zeros((2, 2), dtype=np.float32)
    source_transform = Affine(50, 0, 0, 0, -50, 100)

    try:
        reproject_to_grid(
            source, source_transform, "EPSG:32645", grid,
            kind="average", src_nodata=None, dst_nodata=0.0,
        )
        assert False, "expected ValueError for an unsupported resampling kind"
    except ValueError:
        pass
