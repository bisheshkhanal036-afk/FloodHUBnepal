"""End-to-end integration test: real Phase 1 AHP engine + real Phase 2
local-fixture DEM/WorldCover data (no mocking anywhere in this file),
run through the real overlay pipeline, for the shared test AOI.

This is deliberately an artificial AHP hierarchy (5 clusters with one
criterion each, 2 of which reuse the same physical DEM source under
different criterion ids/rules) — it exists to prove the wiring between
all three phases is correct end to end, not to model realistic flood-risk
weights.
"""

from __future__ import annotations

import shutil

import numpy as np
import pytest
import rasterio
from affine import Affine

from app.ahp import compute_hierarchy
from app.ahp.constants import CANONICAL_CLUSTERS
from app.data import config
from app.overlay.compute import RISK_SURFACE_NODATA
from app.overlay.report import compute_vulnerability_report
from app.overlay.service import OverlayCriterionRequest, compute_overlay
from tests.overlay.conftest import DATA_FIXTURES_DIR

OSM_FIXTURE_PBF = DATA_FIXTURES_DIR / "osm" / "nepal-test-extract.osm.pbf"

# Broad, unbounded-ended rules so they safely cover whatever the resampled
# fixture data actually contains in the test AOI window, without needing
# to hand-derive the exact post-reprojection value range.
ELEVATION_RULES = [
    {"min": None, "max": 1310, "risk_class": 5},
    {"min": 1310, "max": 1330, "risk_class": 4},
    {"min": 1330, "max": 1350, "risk_class": 3},
    {"min": 1350, "max": 1370, "risk_class": 2},
    {"min": 1370, "max": None, "risk_class": 1},
]
SLOPE_RULES = [
    {"min": None, "max": 5, "risk_class": 5},
    {"min": 5, "max": 15, "risk_class": 4},
    {"min": 15, "max": 30, "risk_class": 3},
    {"min": 30, "max": 60, "risk_class": 2},
    {"min": 60, "max": None, "risk_class": 1},
]
LAND_COVER_RULES = [
    {"min": 10, "max": 10, "min_inclusive": True, "max_inclusive": True, "risk_class": 1},
    {"min": 30, "max": 30, "min_inclusive": True, "max_inclusive": True, "risk_class": 2},
    {"min": 50, "max": 50, "min_inclusive": True, "max_inclusive": True, "risk_class": 5},
    {"min": 60, "max": 60, "min_inclusive": True, "max_inclusive": True, "risk_class": 3},
    {"min": 80, "max": 80, "min_inclusive": True, "max_inclusive": True, "risk_class": 4},
]

# One criterion per canonical cluster; Infrastructure/Exposure reuse the
# DEM sources (only 3 distinct physical layers exist in Phase 2 today)
# under different criterion ids so a full 5-cluster, complete=True AHP
# result can be exercised without needing a 4th/5th real data source.
CLUSTER_CRITERIA = {
    "Topographic": ("elevation", "dem_elevation", ELEVATION_RULES),
    "Hydrological": ("slope_a", "dem_slope", SLOPE_RULES),
    "Land Use": ("land_cover", "worldcover_land_cover", LAND_COVER_RULES),
    "Infrastructure": ("elevation_dup", "dem_elevation", ELEVATION_RULES),
    "Exposure": ("slope_dup", "dem_slope", SLOPE_RULES),
}


@pytest.fixture(autouse=True)
def use_real_local_fixtures(monkeypatch):
    monkeypatch.setattr(config, "LOCAL_DEM_DIR", DATA_FIXTURES_DIR / "dem")
    monkeypatch.setattr(config, "LOCAL_WORLDCOVER_DIR", DATA_FIXTURES_DIR / "worldcover")


def test_full_pipeline_end_to_end_with_real_ahp_and_real_local_fixtures(test_aoi):
    # 1. Real AHP: an all-1s (equal-importance) 5x5 cluster matrix and a
    # 1x1 within-cluster matrix per cluster -- both trivially perfectly
    # consistent (CR=0), giving a genuine complete=True HierarchyResult.
    cluster_comparison = {
        "items": list(CANONICAL_CLUSTERS),
        "matrix": [[1.0] * 5 for _ in range(5)],
    }
    within_cluster_comparisons = {
        cluster: {"items": [criterion_id], "matrix": [[1.0]]}
        for cluster, (criterion_id, _source, _rules) in CLUSTER_CRITERIA.items()
    }

    hierarchy_result = compute_hierarchy(cluster_comparison, within_cluster_comparisons)

    assert hierarchy_result.complete is True
    assert hierarchy_result.final_weights == pytest.approx({cid: 0.2 for cid, _s, _r in CLUSTER_CRITERIA.values()})

    # 2. Real overlay, backed by real Phase 2 local-fixture DEM/WorldCover
    # reads (no mocking) -- resolve_criterion_raster runs for real.
    criteria = [
        OverlayCriterionRequest(id=criterion_id, source=source, reclassification_rules=rules)
        for criterion_id, source, rules in CLUSTER_CRITERIA.values()
    ]

    result = compute_overlay(test_aoi, criteria, hierarchy_result.final_weights, hierarchy_result.complete)

    surface = result.risk_surface.risk_surface
    assert surface.dtype == np.float32
    assert surface.shape == (result.risk_surface.grid.height, result.risk_surface.grid.width)

    # The whole point of this test: every pixel in the real, fully-wired
    # pipeline output is either a valid [0,1] score or exactly the nodata
    # sentinel -- nowhere else.
    valid = surface != RISK_SURFACE_NODATA
    assert np.all((surface[valid] >= 0.0) & (surface[valid] <= 1.0))
    assert np.all(surface[~valid] == RISK_SURFACE_NODATA)
    assert valid.any()  # the fixture AOI has at least some real (non-nodata) coverage

    assert len(result.cache_key) == 64
    # Real attribution text from both contributing Phase 2 sources.
    assert any("Copernicus" in a or "DLR" in a for a in result.attribution)
    assert any("WorldCover" in a or "Zanaga" in a for a in result.attribution)


def _write_local_population_fixture(path):
    """A tiny synthetic local population GeoTIFF covering test_aoi's
    bbox -- no committed binary fixture exists for population.py (unlike
    DEM/WorldCover/OSM), so this generates one on the fly, same technique
    tests/data/test_population.py's own local-hit tests already use, to
    keep this integration test's "real fixtures, no mocking" property for
    population too.
    """
    array = np.full((240, 240), 25.0, dtype=np.float64)  # a real (if arbitrary) count value
    transform = Affine(0.0002777777777780012, 0, 85.30, 0, -0.0002777777777780012, 27.72)
    with rasterio.open(
        path, "w", driver="GTiff", height=240, width=240, count=1,
        dtype="float64", crs="EPSG:4326", transform=transform, nodata=float("nan"),
    ) as ds:
        ds.write(array, 1)


def test_vulnerability_report_end_to_end_with_real_ahp_and_real_local_fixtures(test_aoi, monkeypatch, tmp_path):
    """Same real-fixtures, no-mocking philosophy as the risk-surface
    integration test above, extended through Parts 1-4 of the
    vulnerability-classification feature: real OSM building fixture data
    (a real .osm.pbf, parsed for real by pyrosm -- not mocked), a real
    (if synthetic) local population raster, and the real AHP hierarchy
    computation, all the way through to a fully assembled report.
    """
    osm_dir = tmp_path / "osm"
    osm_dir.mkdir()
    shutil.copy(OSM_FIXTURE_PBF, osm_dir / OSM_FIXTURE_PBF.name)
    monkeypatch.setattr(config, "LOCAL_OSM_DIR", osm_dir)

    population_dir = tmp_path / "population"
    population_dir.mkdir()
    _write_local_population_fixture(population_dir / "fake_hrsl.tif")
    monkeypatch.setattr(config, "LOCAL_POPULATION_DIR", population_dir)

    cluster_comparison = {"items": list(CANONICAL_CLUSTERS), "matrix": [[1.0] * 5 for _ in range(5)]}
    within_cluster_comparisons = {
        cluster: {"items": [criterion_id], "matrix": [[1.0]]}
        for cluster, (criterion_id, _source, _rules) in CLUSTER_CRITERIA.items()
    }
    hierarchy_result = compute_hierarchy(cluster_comparison, within_cluster_comparisons)
    criteria = [
        OverlayCriterionRequest(id=criterion_id, source=source, reclassification_rules=rules)
        for criterion_id, source, rules in CLUSTER_CRITERIA.values()
    ]

    report = compute_vulnerability_report(
        test_aoi, criteria, hierarchy_result.final_weights, hierarchy_result.complete,
        criterion_names={cid: cid for cid, _s, _r in CLUSTER_CRITERIA.values()},
        weighting_method="ahp",
        ahp_cluster_comparison=cluster_comparison,
        ahp_within_cluster_comparisons=within_cluster_comparisons,
    )

    # Real per-cluster derivation, from the real AHP breakdown.
    by_id = {c.id: c for c in report.criteria}
    for cluster, (criterion_id, _source, _rules) in CLUSTER_CRITERIA.items():
        assert by_id[criterion_id].cluster == cluster

    # Always all 5 hazard classes, and the zonal totals must be internally
    # consistent with the report's own headline figures.
    assert len(report.zonal_stats) == 5
    assert report.total_area_km2 == pytest.approx(sum(s.area_km2 for s in report.zonal_stats))
    assert report.total_population == pytest.approx(sum(s.population for s in report.zonal_stats))
    assert sum(s.building_count for s in report.zonal_stats) == report.total_buildings

    # The real fixture .pbf has exactly one building inside TEST_AOI_BBOX_4326
    # (tests/data/test_osm.py's own documented fixture contents) -- it must
    # come through this pipeline classified (or explicitly None, but present).
    assert len(report.buildings) == 1
    assert report.buildings[0].hazard_class is None or 1 <= report.buildings[0].hazard_class <= 5

    assert 0.0 <= report.high_risk_building_pct <= 100.0
    assert 0.0 <= report.high_risk_population_pct <= 100.0
    assert len(report.cache_key) == 64
    assert report.aoi.area_km2 > 0
