from __future__ import annotations

import geopandas as gpd
import numpy as np
from shapely.geometry import box
from shapely.ops import unary_union

from app.data.grid import AOIGrid
from app.overlay.building_classification import classify_buildings
from app.overlay.hazard_classes import HAZARD_CLASS_NODATA

# 10x10 grid, 10m pixels, spanning x:[0,100), y:[0,100) -- origin_y=100 is
# the TOP (rasterio/this project's north-up convention: y decreases with
# row). Constructed directly in the grid's own CRS (not EPSG:4326) so the
# hand-computed pixel/coordinate math below isn't distorted by a real
# reprojection.
GRID = AOIGrid(crs="EPSG:32645", resolution_m=10.0, origin_x=0.0, origin_y=100.0, width=10, height=10)

# class 2 for x < 50 (columns 0-4), class 5 for x >= 50 (columns 5-9), every row.
HAZARD_RASTER = np.zeros((10, 10), dtype=np.uint8)
HAZARD_RASTER[:, 0:5] = 2
HAZARD_RASTER[:, 5:10] = 5


def _buildings_gdf(geoms):
    return gpd.GeoDataFrame({"id": range(len(geoms))}, geometry=geoms, crs=GRID.crs)


def test_building_entirely_within_one_class_gets_that_class():
    building = box(10, 40, 30, 60)  # x:[10,30) -- entirely in class-2 territory (x<50)
    result = classify_buildings(_buildings_gdf([building]), GRID, HAZARD_RASTER)

    assert result[0].hazard_class == 2
    assert result[0].hazard_label == "Low"


def test_majority_overlap_wins_over_centroid_when_they_disagree():
    """The case this whole feature's sampling-rule decision is about: a
    building whose GEOMETRIC CENTROID falls in one class but whose actual
    rasterized footprint majority falls in another.

    Rectangle A: x:[0,10), y:[40,60) -- 2 pixels, both class 2 (area 200 m^2).
    Rectangle B: x:[50,70), y:[40,60) -- 4 pixels, both class 5 (area 400 m^2).
    Combined (disjoint) shape's true area-weighted centroid_x =
    (200*5 + 400*60) / 600 ≈ 41.7 -- still on the class-2 side (x<50),
    even though class 5 has DOUBLE the pixel-rasterized area (4 vs 2
    pixels). Centroid sampling would report class 2 here; majority-
    overlap must report class 5.
    """
    rect_a = box(0, 40, 10, 60)
    rect_b = box(50, 40, 70, 60)
    building = unary_union([rect_a, rect_b])
    assert building.centroid.x < 50  # sanity-check the hand computation above

    result = classify_buildings(_buildings_gdf([building]), GRID, HAZARD_RASTER)

    assert result[0].hazard_class == 5  # majority (4 class-5 pixels vs 2 class-2 pixels), not centroid's class 2


def test_a_genuine_tie_resolves_to_the_higher_class():
    # x:[44,56), y:[40,60) -- covers column 4 (class 2, center x=45) and
    # column 5 (class 5, center x=55) across rows 4-5 (centers y=45,55):
    # exactly 2 class-2 pixels and 2 class-5 pixels, a genuine tie.
    building = box(44, 40, 56, 60)

    result = classify_buildings(_buildings_gdf([building]), GRID, HAZARD_RASTER)

    assert result[0].hazard_class == 5  # tie-break: higher class, per this module's documented rule


def test_a_building_smaller_than_one_pixel_falls_back_to_centroid():
    # A 1m x 1m footprint at (2,2)-(3,3) contains no pixel CENTER at all
    # (all_touched=False) -- nothing for majority-overlap to count.
    tiny_building = box(2, 2, 3, 3)  # centroid (2.5, 2.5) -> col 0, row 9 -> class 2

    result = classify_buildings(_buildings_gdf([tiny_building]), GRID, HAZARD_RASTER)

    assert result[0].hazard_class == 2


def test_a_building_entirely_outside_the_grid_gets_no_hazard_class():
    outside_building = box(200, 200, 210, 210)  # nowhere near the 0-100 grid extent

    result = classify_buildings(_buildings_gdf([outside_building]), GRID, HAZARD_RASTER)

    assert result[0].hazard_class is None
    assert result[0].hazard_label is None


def test_a_building_over_a_hazard_class_nodata_region_gets_no_hazard_class():
    raster_with_a_gap = HAZARD_RASTER.copy()
    raster_with_a_gap[:, 0:5] = HAZARD_CLASS_NODATA  # left half now has no hazard class at all
    building = box(10, 40, 30, 60)  # entirely in that now-nodata region

    result = classify_buildings(_buildings_gdf([building]), GRID, raster_with_a_gap)

    assert result[0].hazard_class is None


def test_multiple_buildings_are_classified_independently():
    low_building = box(10, 40, 30, 60)  # class 2
    high_building = box(60, 40, 80, 60)  # class 5

    result = classify_buildings(_buildings_gdf([low_building, high_building]), GRID, HAZARD_RASTER)

    assert [b.hazard_class for b in result] == [2, 5]


def test_empty_buildings_gdf_returns_empty_list():
    empty = gpd.GeoDataFrame({"id": []}, geometry=[], crs=GRID.crs)
    assert classify_buildings(empty, GRID, HAZARD_RASTER) == []
