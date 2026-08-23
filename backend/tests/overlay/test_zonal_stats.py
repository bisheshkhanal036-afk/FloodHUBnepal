from __future__ import annotations

import numpy as np

from app.data.grid import AOIGrid
from app.overlay.building_classification import ClassifiedBuilding
from app.overlay.hazard_classes import HAZARD_CLASS_NODATA
from app.overlay.zonal_stats import compute_zonal_stats

GRID = AOIGrid(crs="EPSG:32645", resolution_m=10.0, origin_x=0.0, origin_y=0.0, width=4, height=4)
# 16 pixels, each 10m x 10m = 100 m^2 = 0.0001 km^2.
PIXEL_AREA_KM2 = 0.0001


def _flat_raster(fill: int) -> np.ndarray:
    return np.full((4, 4), fill, dtype=np.uint8)


def test_area_km2_is_pixel_count_times_true_pixel_area():
    # 6 pixels of class 3 (a known composition), rest nodata.
    hazard = _flat_raster(HAZARD_CLASS_NODATA)
    hazard[0, :] = 3  # 4 pixels
    hazard[1, 0:2] = 3  # +2 pixels = 6 total

    population = np.zeros((4, 4), dtype=np.float32)  # irrelevant to this test
    stats = compute_zonal_stats(hazard, GRID, population, -9999.0, classified_buildings=[])

    by_class = {s.hazard_class: s for s in stats}
    assert by_class[3].area_km2 == 6 * PIXEL_AREA_KM2
    assert by_class[1].area_km2 == 0.0  # a class with zero pixels is zero-filled, not missing


def test_all_5_classes_are_always_present_even_if_empty_in_this_aoi():
    hazard = _flat_raster(HAZARD_CLASS_NODATA)  # nothing but nodata
    population = np.zeros((4, 4), dtype=np.float32)

    stats = compute_zonal_stats(hazard, GRID, population, -9999.0, classified_buildings=[])

    assert {s.hazard_class for s in stats} == {1, 2, 3, 4, 5}
    assert all(s.area_km2 == 0.0 and s.population == 0.0 and s.building_count == 0 for s in stats)


def test_population_is_density_times_pixel_area_not_a_raw_density_sum():
    """The exact bug this function exists to prevent: summing density
    VALUES directly would be off by a factor of ~10,000 (1/PIXEL_AREA_KM2)
    at this grid's resolution -- the same count-vs-density unit mistake
    population.py's own _count_to_density fix was written to catch one
    layer up.
    """
    hazard = _flat_raster(HAZARD_CLASS_NODATA)
    hazard[0, 0:2] = 4  # 2 pixels of class 4
    population_density = np.zeros((4, 4), dtype=np.float32)
    population_density[0, 0] = 50000.0  # people/km^2
    population_density[0, 1] = 100000.0  # people/km^2

    stats = compute_zonal_stats(hazard, GRID, population_density, -9999.0, classified_buildings=[])

    by_class = {s.hazard_class: s for s in stats}
    expected = (50000.0 + 100000.0) * PIXEL_AREA_KM2  # NOT 50000.0 + 100000.0
    assert by_class[4].population == expected
    assert by_class[4].population != 50000.0 + 100000.0  # the bug this test would have caught


def test_population_nodata_pixels_contribute_zero_not_excluded_from_the_class():
    hazard = _flat_raster(HAZARD_CLASS_NODATA)
    hazard[0, 0:2] = 2  # 2 pixels of class 2
    population_density = np.full((4, 4), -9999.0, dtype=np.float32)  # all population-nodata
    population_density[0, 0] = 20000.0  # one real value

    stats = compute_zonal_stats(hazard, GRID, population_density, -9999.0, classified_buildings=[])

    by_class = {s.hazard_class: s for s in stats}
    # Both pixels count toward area (2 pixels), but only the non-nodata one
    # contributes population.
    assert by_class[2].area_km2 == 2 * PIXEL_AREA_KM2
    assert by_class[2].population == 20000.0 * PIXEL_AREA_KM2


def test_building_count_per_class_from_classified_buildings():
    hazard = _flat_raster(HAZARD_CLASS_NODATA)
    population = np.zeros((4, 4), dtype=np.float32)
    buildings = [
        ClassifiedBuilding(geometry=None, hazard_class=5, hazard_label="Very High"),
        ClassifiedBuilding(geometry=None, hazard_class=5, hazard_label="Very High"),
        ClassifiedBuilding(geometry=None, hazard_class=1, hazard_label="Very Low"),
        ClassifiedBuilding(geometry=None, hazard_class=None, hazard_label=None),  # unclassified, must not count
    ]

    stats = compute_zonal_stats(hazard, GRID, population, -9999.0, classified_buildings=buildings)

    by_class = {s.hazard_class: s for s in stats}
    assert by_class[5].building_count == 2
    assert by_class[1].building_count == 1
    assert by_class[2].building_count == 0
    assert sum(s.building_count for s in stats) == 3  # the unclassified one is excluded from every class
