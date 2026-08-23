from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Point

from app.ahp.errors import AHPConsistencyError
from app.data.attribution import OSM_ATTRIBUTION
from app.data.grid import AOIGrid
from app.data.osm import OSMResult
from app.data.population import PopulationResult
from app.overlay.errors import OverlayValidationError
from app.overlay.report import compute_vulnerability_report
from app.overlay.service import OverlayCriterionRequest

GRID = AOIGrid(crs="EPSG:32645", resolution_m=10.0, origin_x=0.0, origin_y=0.0, width=2, height=2)


def _fake_resolve(monkeypatch, class_value=3):
    def fake(aoi, criterion_id, source, rules, stream_threshold_cells=None):
        return np.full((2, 2), class_value, dtype=np.uint8), GRID, "Fake Source Attribution", None

    monkeypatch.setattr("app.overlay.service.resolve_criterion_raster", fake)


def _fake_population(monkeypatch, density_value=50000.0):
    def fake(aoi):
        density = np.full((2, 2), density_value, dtype=np.float32)
        return PopulationResult(density=density, grid=GRID, nodata=-9999.0, source_used="fake")

    monkeypatch.setattr("app.overlay.report.get_population", fake)


def _fake_osm_features(monkeypatch, buildings_gdf):
    def fake(aoi):
        return OSMResult(buildings=buildings_gdf, roads=gpd.GeoDataFrame(geometry=[]), source_used="fake")

    monkeypatch.setattr("app.overlay.report.get_osm_features", fake)


def _one_building_at(x, y):
    return gpd.GeoDataFrame({"id": [1]}, geometry=[Point(x, y).buffer(1)], crs="EPSG:32645")


# --- equal weighting mode ---


def test_equal_weighting_mode_produces_a_complete_report(test_aoi, monkeypatch):
    _fake_resolve(monkeypatch, class_value=3)
    _fake_population(monkeypatch)
    _fake_osm_features(monkeypatch, _one_building_at(5, -5))  # GRID's valid y range is (-20, 0]
    criteria = [OverlayCriterionRequest(id="a", source="dem_elevation", reclassification_rules=[])]

    report = compute_vulnerability_report(
        test_aoi, criteria, {"a": 1.0}, complete=True,
        criterion_names={"a": "Elevation"}, weighting_method="equal",
    )

    assert report.weighting.method == "equal"
    assert report.weighting.ahp is None
    assert report.criteria[0].name == "Elevation"
    assert report.criteria[0].cluster is None  # no AHP breakdown to derive it from
    assert len(report.zonal_stats) == 5  # always all 5 classes
    assert report.attribution == ["Fake Source Attribution"]
    assert len(report.cache_key) == 64


def test_criterion_name_defaults_to_id_when_not_supplied(test_aoi, monkeypatch):
    _fake_resolve(monkeypatch)
    _fake_population(monkeypatch)
    _fake_osm_features(monkeypatch, gpd.GeoDataFrame({"id": []}, geometry=[], crs="EPSG:32645"))
    criteria = [OverlayCriterionRequest(id="dem_elevation", source="dem_elevation", reclassification_rules=[])]

    report = compute_vulnerability_report(test_aoi, criteria, {"dem_elevation": 1.0}, complete=True)

    assert report.criteria[0].name == "dem_elevation"


# --- AHP weighting mode ---


def _all_ones_matrix(n):
    # A perfectly consistent matrix regardless of size: every judgment=1
    # (CR=0 exactly -- see this test module's own comment for why).
    return [[1.0] * n for _ in range(n)]


def test_ahp_weighting_mode_produces_a_complete_report_with_cluster_breakdown(test_aoi, monkeypatch):
    _fake_resolve(monkeypatch)
    _fake_population(monkeypatch)
    _fake_osm_features(monkeypatch, gpd.GeoDataFrame({"id": []}, geometry=[], crs="EPSG:32645"))
    criteria = [
        OverlayCriterionRequest(id="a", source="dem_elevation", reclassification_rules=[]),
        OverlayCriterionRequest(id="b", source="dem_slope", reclassification_rules=[]),
    ]
    cluster_comparison = {
        "items": ["Topographic", "Hydrological", "Land Use", "Infrastructure", "Exposure"],
        "matrix": _all_ones_matrix(5),
    }
    within_cluster_comparisons = {"Topographic": {"items": ["a", "b"], "matrix": _all_ones_matrix(2)}}
    # Only 1 of 5 clusters covered (a normal, everyday case -- see config/
    # criteria.js's own note on a cluster like Exposure sometimes having
    # nothing selected). Raw recomputed weights here are 0.1 each (0.2
    # cluster weight * 0.5 within-cluster weight), which never sums to 1
    # on its own at just these 2 criteria -- final_weights below (0.5
    # each) is what the frontend's own AHP-mode renormalization (see
    # state/AppStateContext.jsx's useFinalWeights) produces from exactly
    # this same partial breakdown, preserving the 1:1 PROPORTION between
    # "a" and "b" while satisfying compute_overlay's separate "must sum
    # to 1" requirement. The consistency check renormalizes the same way
    # before comparing (see report._weighting_consistency_warning's own
    # docstring), so this must be a clean match, not a false "mismatch".
    report = compute_vulnerability_report(
        test_aoi, criteria, {"a": 0.5, "b": 0.5}, complete=True,
        weighting_method="ahp",
        ahp_cluster_comparison=cluster_comparison,
        ahp_within_cluster_comparisons=within_cluster_comparisons,
    )

    assert report.weighting.method == "ahp"
    assert report.weighting.ahp is not None
    assert report.weighting.ahp.cluster_comparison.consistent
    assert pytest.approx(report.weighting.ahp.cluster_comparison.eigenvector_weights[0]) == 0.2  # all-ones -> equal
    assert report.weighting.consistency_warning is None
    by_id = {c.id: c for c in report.criteria}
    assert by_id["a"].cluster == "Topographic"
    assert by_id["b"].cluster == "Topographic"


def test_ahp_mode_requires_both_matrices(test_aoi, monkeypatch):
    _fake_resolve(monkeypatch)
    _fake_population(monkeypatch)
    _fake_osm_features(monkeypatch, gpd.GeoDataFrame({"id": []}, geometry=[], crs="EPSG:32645"))
    criteria = [OverlayCriterionRequest(id="a", source="dem_elevation", reclassification_rules=[])]

    with pytest.raises(OverlayValidationError, match="requires both"):
        compute_vulnerability_report(
            test_aoi, criteria, {"a": 1.0}, complete=True, weighting_method="ahp",
        )


def test_ahp_mode_propagates_a_genuinely_inconsistent_matrix_as_an_error(test_aoi, monkeypatch):
    """Same contract as POST /api/ahp/compute for a bad matrix -- this
    function doesn't swallow or silently ignore an inconsistent AHP
    submission just because it's "only for the report".
    """
    _fake_resolve(monkeypatch)
    _fake_population(monkeypatch)
    _fake_osm_features(monkeypatch, gpd.GeoDataFrame({"id": []}, geometry=[], crs="EPSG:32645"))
    criteria = [OverlayCriterionRequest(id="a", source="dem_elevation", reclassification_rules=[])]
    # A classic maximally-inconsistent 3x3 (a >> b >> c >> a, cyclically).
    bad_cluster_comparison = {
        "items": ["Topographic", "Hydrological", "Land Use", "Infrastructure", "Exposure"],
        "matrix": [
            [1, 9, 1 / 9, 1, 1],
            [1 / 9, 1, 9, 1, 1],
            [9, 1 / 9, 1, 1, 1],
            [1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1],
        ],
    }

    with pytest.raises(AHPConsistencyError):
        compute_vulnerability_report(
            test_aoi, criteria, {"a": 1.0}, complete=True, weighting_method="ahp",
            ahp_cluster_comparison=bad_cluster_comparison,
            ahp_within_cluster_comparisons={"Topographic": {"items": ["a"], "matrix": [[1.0]]}},
        )


# --- weighting consistency check (final_weights vs recomputed AHP) ---


def test_equal_weighting_mode_never_has_a_consistency_warning(test_aoi, monkeypatch):
    _fake_resolve(monkeypatch)
    _fake_population(monkeypatch)
    _fake_osm_features(monkeypatch, gpd.GeoDataFrame({"id": []}, geometry=[], crs="EPSG:32645"))
    criteria = [OverlayCriterionRequest(id="a", source="dem_elevation", reclassification_rules=[])]

    report = compute_vulnerability_report(test_aoi, criteria, {"a": 1.0}, complete=True, weighting_method="equal")

    assert report.weighting.consistency_warning is None


def _full_5_cluster_ahp_setup():
    """5 criteria, one per canonical cluster, all-ones matrices at both
    levels -- the only way to get compute_overlay's own (separate, always-
    enforced) "final_weights must sum to 1" requirement to coincide with a
    FULLY matchable AHP recompute: a genuinely partial (< 5 cluster)
    breakdown's own final_weights can never sum to 1 at all, so "does
    final_weights match the AHP recompute" can only be tested for a real
    match using full 5-cluster coverage. Mirrors test_integration.py's own
    CLUSTER_CRITERIA fixture. Each criterion's recomputed weight: 0.2
    (cluster) * 1.0 (only item in its cluster) = 0.2, summing to 1.0.
    """
    criteria = [
        OverlayCriterionRequest(id=cid, source="dem_elevation", reclassification_rules=[])
        for cid in ("a", "b", "c", "d", "e")
    ]
    cluster_comparison = {
        "items": ["Topographic", "Hydrological", "Land Use", "Infrastructure", "Exposure"],
        "matrix": _all_ones_matrix(5),
    }
    within_cluster_comparisons = {
        cluster: {"items": [cid], "matrix": [[1.0]]}
        for cluster, cid in zip(
            ["Topographic", "Hydrological", "Land Use", "Infrastructure", "Exposure"], ("a", "b", "c", "d", "e")
        )
    }
    return criteria, cluster_comparison, within_cluster_comparisons


def test_final_weights_matching_the_ahp_breakdown_has_no_consistency_warning(test_aoi, monkeypatch):
    _fake_resolve(monkeypatch)
    _fake_population(monkeypatch)
    _fake_osm_features(monkeypatch, gpd.GeoDataFrame({"id": []}, geometry=[], crs="EPSG:32645"))
    criteria, cluster_comparison, within_cluster_comparisons = _full_5_cluster_ahp_setup()
    matching_final_weights = {cid: 0.2 for cid in ("a", "b", "c", "d", "e")}

    report = compute_vulnerability_report(
        test_aoi, criteria, matching_final_weights, complete=True, weighting_method="ahp",
        ahp_cluster_comparison=cluster_comparison, ahp_within_cluster_comparisons=within_cluster_comparisons,
    )

    assert report.weighting.consistency_warning is None


def test_final_weights_diverging_from_the_ahp_breakdown_surfaces_a_visible_warning_not_an_error(
    test_aoi, monkeypatch
):
    """The exact scenario this check exists for: a caller submits
    final_weights that don't match what the ALSO-submitted pairwise
    matrices actually produce (e.g. stale final_weights left over from
    an earlier AHP run). Must not raise -- the risk surface is still
    computed from final_weights as given -- but must be visibly flagged,
    since a silent mismatch would undermine the report's own credibility.
    """
    _fake_resolve(monkeypatch)
    _fake_population(monkeypatch)
    _fake_osm_features(monkeypatch, gpd.GeoDataFrame({"id": []}, geometry=[], crs="EPSG:32645"))
    criteria, cluster_comparison, within_cluster_comparisons = _full_5_cluster_ahp_setup()
    # Sums to 1.0 (satisfies compute_overlay's own requirement) but wildly
    # skewed away from the recomputed uniform 0.2-each.
    diverging_final_weights = {"a": 0.6, "b": 0.1, "c": 0.1, "d": 0.1, "e": 0.1}

    report = compute_vulnerability_report(
        test_aoi, criteria, diverging_final_weights, complete=True, weighting_method="ahp",
        ahp_cluster_comparison=cluster_comparison, ahp_within_cluster_comparisons=within_cluster_comparisons,
    )

    assert report.weighting.final_weights == diverging_final_weights  # the surface computation is unaffected
    assert report.weighting.consistency_warning is not None
    assert "0.6" in report.weighting.consistency_warning
    assert "0.2" in report.weighting.consistency_warning


def test_mismatched_criterion_sets_between_final_weights_and_ahp_breakdown_are_flagged(test_aoi, monkeypatch):
    _fake_resolve(monkeypatch)
    _fake_population(monkeypatch)
    _fake_osm_features(monkeypatch, gpd.GeoDataFrame({"id": []}, geometry=[], crs="EPSG:32645"))
    criteria = [OverlayCriterionRequest(id="a", source="dem_elevation", reclassification_rules=[])]
    cluster_comparison = {
        "items": ["Topographic", "Hydrological", "Land Use", "Infrastructure", "Exposure"],
        "matrix": _all_ones_matrix(5),
    }
    # The AHP breakdown is about a criterion "b" that final_weights never mentions.
    within_cluster_comparisons = {"Topographic": {"items": ["b"], "matrix": [[1.0]]}}

    report = compute_vulnerability_report(
        test_aoi, criteria, {"a": 1.0}, complete=True, weighting_method="ahp",
        ahp_cluster_comparison=cluster_comparison, ahp_within_cluster_comparisons=within_cluster_comparisons,
    )

    assert report.weighting.consistency_warning is not None
    assert "different criteria" in report.weighting.consistency_warning


def test_a_genuine_proportional_divergence_is_still_caught_under_partial_ahp_coverage(test_aoi, monkeypatch):
    """The renormalization the consistency check applies (to avoid the
    false-positive the earlier "cluster breakdown" test above would
    otherwise trip on every normal partial-cluster-coverage request)
    must not make it blind to an ACTUAL problem: final_weights whose
    relative proportions genuinely don't match what the submitted
    matrices produce, not just a different absolute scale.
    """
    _fake_resolve(monkeypatch)
    _fake_population(monkeypatch)
    _fake_osm_features(monkeypatch, gpd.GeoDataFrame({"id": []}, geometry=[], crs="EPSG:32645"))
    criteria = [
        OverlayCriterionRequest(id="a", source="dem_elevation", reclassification_rules=[]),
        OverlayCriterionRequest(id="b", source="dem_slope", reclassification_rules=[]),
    ]
    cluster_comparison = {
        "items": ["Topographic", "Hydrological", "Land Use", "Infrastructure", "Exposure"],
        "matrix": _all_ones_matrix(5),
    }
    # Recomputed (raw): 0.1 each -> renormalized 1:1 (0.5/0.5). A genuinely
    # different PROPORTION (0.9/0.1, still summing to 1) must still trip
    # the warning, not just an absolute-scale difference.
    within_cluster_comparisons = {"Topographic": {"items": ["a", "b"], "matrix": _all_ones_matrix(2)}}
    wrong_proportion_final_weights = {"a": 0.9, "b": 0.1}

    report = compute_vulnerability_report(
        test_aoi, criteria, wrong_proportion_final_weights, complete=True, weighting_method="ahp",
        ahp_cluster_comparison=cluster_comparison, ahp_within_cluster_comparisons=within_cluster_comparisons,
    )

    assert report.weighting.consistency_warning is not None


# --- headline figures / totals ---


def test_headline_totals_and_high_risk_figures(test_aoi, monkeypatch):
    _fake_resolve(monkeypatch, class_value=5)  # every pixel classifies to hazard class 5 (Very High)
    _fake_population(monkeypatch, density_value=100000.0)
    # GRID's origin_y=0 is the TOP-left corner (y decreases downward, per
    # this project's north-up raster convention) -- valid y range for
    # this 2x2/10m grid is (-20, 0], not positive y.
    buildings = gpd.GeoDataFrame(
        {"id": [1, 2]}, geometry=[Point(5, -5).buffer(1), Point(15, -5).buffer(1)], crs="EPSG:32645"
    )
    _fake_osm_features(monkeypatch, buildings)
    criteria = [OverlayCriterionRequest(id="a", source="dem_elevation", reclassification_rules=[])]

    report = compute_vulnerability_report(test_aoi, criteria, {"a": 1.0}, complete=True)

    assert report.total_buildings == 2
    assert report.high_risk_building_count == 2  # both fall in class 5 (High/Very High)
    assert report.high_risk_building_pct == 100.0
    assert report.total_population > 0
    assert report.high_risk_population == pytest.approx(report.total_population)
    assert report.high_risk_population_pct == pytest.approx(100.0)
