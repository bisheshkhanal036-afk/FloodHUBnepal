from __future__ import annotations

import numpy as np
import pytest

from app.overlay.errors import OverlayValidationError
from app.overlay.sources import (
    SUPPORTED_SOURCES,
    register_source,
    registered_sources,
    resolve_criterion_raster,
)


def test_rejects_unrecognized_source(test_aoi):
    with pytest.raises(OverlayValidationError, match="unrecognized criterion source"):
        resolve_criterion_raster(test_aoi, "mystery", "not_a_real_source", [])


def test_all_eight_built_in_sources_are_registered():
    """Phase 2's original 3, Phase 5's 4, and building_density (Exposure
    cluster's first criterion) — proves the additions actually landed in
    the registry, not just that the module imports without error.
    """
    expected = {
        "dem_elevation",
        "dem_slope",
        "worldcover_land_cover",
        "dist_to_river",
        "dist_to_road",
        "twi",
        "drainage_density",
        "building_density",
        "hand",
        "soil_infiltration",
    }
    assert expected <= set(registered_sources())
    assert expected <= set(SUPPORTED_SOURCES)


# --- Part 3's own claim, verified rather than just asserted: a brand-new
# source can be registered from OUTSIDE app/overlay/sources.py, using only
# the public register_source() function, and the overlay engine
# (resolve_criterion_raster, and by extension overlay/compute.py's
# weighted-sum math and overlay/service.py's orchestration) consumes it
# exactly like a built-in source — with zero changes to sources.py or any
# other overlay/ file to make this test pass. ---


def _dummy_constant_source(aoi, **_kwargs):
    from app.data.grid import compute_aoi_grid

    grid = compute_aoi_grid(aoi.bounds_utm)
    array = np.full((grid.height, grid.width), 3.0, dtype=np.float32)
    return array, grid, -9999.0, "dummy test attribution", None


def test_registry_extensibility_a_test_registered_dummy_source_is_fully_consumable(test_aoi):
    register_source("__test_dummy_constant_source__", _dummy_constant_source)

    assert "__test_dummy_constant_source__" in registered_sources()

    # A single unbounded rule (min=None, max=None) covers the dummy
    # source's constant value of 3.0 -> every pixel reclassifies to 5.
    rules = [{"min": None, "max": None, "risk_class": 5}]

    reclassified, grid, attribution, warning = resolve_criterion_raster(
        test_aoi, "dummy_criterion", "__test_dummy_constant_source__", rules
    )

    assert attribution == "dummy test attribution"
    assert warning is None
    assert reclassified.shape == (grid.height, grid.width)
    assert (reclassified == 5).all()


def test_register_source_rejects_a_duplicate_name():
    register_source("__test_duplicate_guard__", _dummy_constant_source)
    with pytest.raises(ValueError, match="already registered"):
        register_source("__test_duplicate_guard__", _dummy_constant_source)


# --- each of the 4 new built-in sources resolves via the registry (mocked
# at the app/data/ level, so these don't touch real files/network) ---


def test_dist_to_river_resolves_via_the_registry(test_aoi, monkeypatch):
    from app.data.distance_raster import DistanceRasterResult
    from app.data.grid import compute_aoi_grid

    grid = compute_aoi_grid(test_aoi.bounds_utm)
    fake = DistanceRasterResult(
        distance_m=np.full((grid.height, grid.width), 50.0, dtype=np.float32),
        grid=grid,
        nodata=-1.0,
        attribution="fake dist_to_river",
    )
    monkeypatch.setattr("app.overlay.sources.get_distance_to_river", lambda aoi: fake)

    rules = [{"min": None, "max": None, "risk_class": 2}]
    reclassified, out_grid, attribution, warning = resolve_criterion_raster(test_aoi, "c1", "dist_to_river", rules)

    assert attribution == "fake dist_to_river"
    assert warning is None
    assert (reclassified == 2).all()
    assert out_grid == grid


def test_dist_to_road_resolves_via_the_registry(test_aoi, monkeypatch):
    from app.data.distance_raster import DistanceRasterResult
    from app.data.grid import compute_aoi_grid

    grid = compute_aoi_grid(test_aoi.bounds_utm)
    fake = DistanceRasterResult(
        distance_m=np.full((grid.height, grid.width), 5.0, dtype=np.float32),
        grid=grid,
        nodata=-1.0,
        attribution="fake dist_to_road",
    )
    monkeypatch.setattr("app.overlay.sources.get_distance_to_road", lambda aoi: fake)

    rules = [{"min": None, "max": None, "risk_class": 4}]
    reclassified, _grid, attribution, warning = resolve_criterion_raster(test_aoi, "c2", "dist_to_road", rules)

    assert attribution == "fake dist_to_road"
    assert warning is None
    assert (reclassified == 4).all()


def test_twi_resolves_via_the_registry(test_aoi, monkeypatch):
    from app.data.grid import compute_aoi_grid
    from app.data.hydrology import TWIResult

    grid = compute_aoi_grid(test_aoi.bounds_utm)
    fake = TWIResult(
        twi=np.full((grid.height, grid.width), 8.0, dtype=np.float32),
        grid=grid,
        nodata=-9999.0,
        attribution="fake twi",
        warning="fake edge-reliability warning",
    )
    monkeypatch.setattr("app.overlay.sources.get_twi", lambda aoi: fake)

    rules = [{"min": None, "max": None, "risk_class": 3}]
    reclassified, _grid, attribution, warning = resolve_criterion_raster(test_aoi, "c3", "twi", rules)

    assert attribution == "fake twi"
    assert warning == "fake edge-reliability warning"
    assert (reclassified == 3).all()


def test_drainage_density_resolves_via_the_registry(test_aoi, monkeypatch):
    from app.data.grid import compute_aoi_grid
    from app.data.hydrology import DrainageDensityResult

    grid = compute_aoi_grid(test_aoi.bounds_utm)
    fake = DrainageDensityResult(
        drainage_density=np.full((grid.height, grid.width), 1.5, dtype=np.float32),
        grid=grid,
        nodata=-9999.0,
        attribution="fake drainage_density",
    )
    monkeypatch.setattr("app.overlay.sources.get_drainage_density", lambda aoi, **kwargs: fake)

    rules = [{"min": None, "max": None, "risk_class": 1}]
    reclassified, _grid, attribution, warning = resolve_criterion_raster(test_aoi, "c4", "drainage_density", rules)

    assert attribution == "fake drainage_density"
    assert warning is None
    assert (reclassified == 1).all()


def test_hand_resolves_via_the_registry(test_aoi, monkeypatch):
    """overlay/sources.py's `_hand` adapter (and, by extension, the rest
    of the overlay engine -- resolve_criterion_raster, compute.py's
    weighted-sum math, service.py's orchestration) consumes get_hand()
    with zero changes of its own, the same registry-extensibility claim
    every other source here already proves.
    """
    from app.data.grid import compute_aoi_grid
    from app.data.hydrology import HANDResult

    grid = compute_aoi_grid(test_aoi.bounds_utm)
    fake = HANDResult(
        hand=np.full((grid.height, grid.width), 1.0, dtype=np.float32),
        grid=grid,
        nodata=-9999.0,
        attribution="fake hand",
        warning="fake edge-reliability warning",
    )
    monkeypatch.setattr("app.overlay.sources.get_hand", lambda aoi, **kwargs: fake)

    rules = [{"min": None, "max": None, "risk_class": 5}]
    reclassified, _grid, attribution, warning = resolve_criterion_raster(test_aoi, "c6", "hand", rules)

    assert attribution == "fake hand"
    assert warning == "fake edge-reliability warning"
    assert (reclassified == 5).all()


def test_resolve_criterion_raster_forwards_stream_threshold_cells_to_drainage_density_and_hand(test_aoi, monkeypatch):
    """resolve_criterion_raster's stream_threshold_cells param (POST
    /api/overlay/compute's per-request override) must reach
    get_drainage_density/get_hand as their own threshold_cells kwarg --
    proven with a spy rather than just asserting the adapters look
    right, since a keyword-name typo wouldn't be caught by that alone.
    """
    from app.data.grid import compute_aoi_grid
    from app.data.hydrology import DrainageDensityResult, HANDResult

    grid = compute_aoi_grid(test_aoi.bounds_utm)
    rules = [{"min": None, "max": None, "risk_class": 1}]
    seen = {}

    def fake_drainage_density(aoi, threshold_cells=None):
        seen["drainage_density"] = threshold_cells
        return DrainageDensityResult(
            drainage_density=np.full((grid.height, grid.width), 1.0, dtype=np.float32),
            grid=grid, nodata=-9999.0, attribution="fake",
        )

    def fake_hand(aoi, threshold_cells=None):
        seen["hand"] = threshold_cells
        return HANDResult(
            hand=np.full((grid.height, grid.width), 1.0, dtype=np.float32), grid=grid, nodata=-9999.0, attribution="fake"
        )

    monkeypatch.setattr("app.overlay.sources.get_drainage_density", fake_drainage_density)
    monkeypatch.setattr("app.overlay.sources.get_hand", fake_hand)

    resolve_criterion_raster(test_aoi, "c", "drainage_density", rules, stream_threshold_cells=750)
    resolve_criterion_raster(test_aoi, "c", "hand", rules, stream_threshold_cells=750)

    assert seen == {"drainage_density": 750, "hand": 750}


def test_resolve_criterion_raster_ignores_stream_threshold_cells_for_unrelated_sources(test_aoi, monkeypatch):
    """Every other source's adapter absorbs the extra kwarg via **_kwargs
    without error -- an unrelated source passed a threshold override
    (e.g. because the frontend submits it whenever drainage_density/hand
    is selected, alongside other checked criteria) must still resolve
    normally, not raise a TypeError.
    """
    from app.data.dem import DEMResult
    from app.data.grid import compute_aoi_grid

    grid = compute_aoi_grid(test_aoi.bounds_utm)
    fake = DEMResult(
        elevation_m=np.full((grid.height, grid.width), 1500.0, dtype=np.float32),
        slope_degrees=np.zeros((grid.height, grid.width), dtype=np.float32),
        grid=grid, nodata=-9999.0, source_used="fake",
    )
    monkeypatch.setattr("app.overlay.sources.get_dem", lambda aoi: fake)

    rules = [{"min": None, "max": None, "risk_class": 4}]
    reclassified, _grid, _attribution, _warning = resolve_criterion_raster(
        test_aoi, "c", "dem_elevation", rules, stream_threshold_cells=750
    )

    assert (reclassified == 4).all()


def test_building_density_resolves_via_the_registry(test_aoi, monkeypatch):
    from app.data.density_raster import BuildingDensityResult
    from app.data.grid import compute_aoi_grid

    grid = compute_aoi_grid(test_aoi.bounds_utm)
    fake = BuildingDensityResult(
        density=np.full((grid.height, grid.width), 0.3, dtype=np.float32),
        grid=grid,
        nodata=None,
        attribution="fake building_density",
    )
    monkeypatch.setattr("app.overlay.sources.get_building_density", lambda aoi: fake)

    rules = [{"min": None, "max": None, "risk_class": 2}]
    reclassified, _grid, attribution, warning = resolve_criterion_raster(test_aoi, "c5", "building_density", rules)

    assert attribution == "fake building_density"
    assert warning is None
    assert (reclassified == 2).all()
