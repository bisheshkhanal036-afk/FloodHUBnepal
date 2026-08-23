"""Unit tests for the hydrological preprocessing shared by the TWI and
drainage-density criterion sources: DEM sink-fill, D8 flow direction,
flow accumulation (via pysheds), and the pure math built on top of it.

The V-shaped-valley DEM used below (and its exact expected numbers) was
hand-verified against a direct pysheds run during implementation — see
the accompanying conversation for the verification transcript — not
just asserted from a first successful run.
"""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import box

from app.data import config
from app.data.aoi import AOI
from app.data.attribution import DEM_ATTRIBUTION
from app.data.dem import DEMResult
from app.data.grid import AOIGrid, compute_aoi_grid
from app.data.hydrology import (
    HYDROLOGY_NODATA,
    MIN_SLOPE_RADIANS,
    FlowAccumulationResult,
    _compute_hand_raster,
    _hydrology_cache_version,
    _polygon_inside_mask,
    _run_pysheds_pipeline,
    compute_drainage_density_raster,
    compute_flow_accumulation,
    get_drainage_density,
    get_hand,
    get_twi,
)

TEST_AOI_BBOX_4326 = (85.3050, 27.7020, 85.3110, 27.7080)


@pytest.fixture
def test_aoi() -> AOI:
    return AOI(bbox_4326=TEST_AOI_BBOX_4326)


@pytest.fixture(autouse=True)
def isolated_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROCESSED_CACHE_DIR", tmp_path / "cache" / "processed")


# A north-south valley: elevation decreases 10m per row (flow moves
# south) and rises 10m per column-step away from the center column
# (flow converges toward column 2). No two adjacent cells are equal, so
# there's exactly one steepest-descent direction everywhere except the
# domain edge — the D8 result is unambiguous.
_V_VALLEY_ELEVATION = np.array(
    [
        [120, 110, 100, 110, 120],
        [110, 100, 90, 100, 110],
        [100, 90, 80, 90, 100],
        [90, 80, 70, 80, 90],
        [80, 70, 60, 70, 80],
    ],
    dtype=np.float64,
)


def _small_grid(width=5, height=5) -> AOIGrid:
    return AOIGrid(crs="EPSG:32645", resolution_m=10.0, origin_x=0.0, origin_y=50.0, width=width, height=height)


# --- _run_pysheds_pipeline: sink-fill + D8 flow direction + accumulation ---


def test_flow_accumulates_toward_the_valley_bottom_on_a_hand_verifiable_v_shaped_dem():
    grid = _small_grid()
    acc, _fdir, valid, _conditioned = _run_pysheds_pipeline(_V_VALLEY_ELEVATION, grid, dem_nodata=-9999.0, inside_mask=None)

    # Hand-verified: [1, 4, 9, 14, 25] down the valley-bottom column (2).
    centerline = acc[:, 2]
    assert list(centerline) == [1.0, 4.0, 9.0, 14.0, 25.0]
    assert np.all(np.diff(centerline) > 0), "accumulation must strictly increase downstream"

    # At every row (except the very top, where nothing has accumulated
    # yet), the valley bottom accumulates strictly more than its
    # immediate side-slope neighbors -- this is what "converges toward
    # the valley bottom" actually means, not just a coincidental
    # monotonic count down one column.
    for row in range(1, 5):
        assert acc[row, 2] > acc[row, 1] > 0
        assert acc[row, 2] > acc[row, 3] > 0

    # Every interior/edge cell resolves to a real D8 direction and is
    # valid, except the domain's own outlet (bottom-center): it's the
    # single lowest cell with nothing lower to flow to within the given
    # extent, so pysheds correctly reports it as an unresolved pit
    # rather than fabricating a direction — see the next test.
    assert valid[:4, :].all()


def test_edge_outlet_with_no_lower_neighbor_is_marked_invalid_not_fabricated():
    grid = _small_grid()
    _acc, fdir, valid, _conditioned = _run_pysheds_pipeline(_V_VALLEY_ELEVATION, grid, dem_nodata=-9999.0, inside_mask=None)

    # (4, 2) is the DEM's global minimum, sitting on the grid's own
    # southern edge -- there is genuinely no data beyond it to route
    # into, so this must come out as "no resolved direction", not a
    # silently-wrong fabricated code.
    assert valid[4, 2] == False  # noqa: E712 (explicit bool comparison reads clearer here)
    assert fdir[4, 2] not in (64, 128, 1, 2, 4, 8, 16, 32)


def test_own_nodata_pixel_is_invalid_and_does_not_receive_a_fabricated_direction():
    elevation = _V_VALLEY_ELEVATION.copy()
    elevation[1, 1] = -9999.0
    grid = _small_grid()

    _acc, _fdir, valid, _conditioned = _run_pysheds_pipeline(elevation, grid, dem_nodata=-9999.0, inside_mask=None)

    assert valid[1, 1] == False  # noqa: E712


# --- polygon clipping: the reason a basin-derived AOI is different from a bbox one ---


def test_polygon_clip_and_bbox_produce_different_flow_accumulation_near_the_boundary():
    grid = _small_grid()
    inside_mask = np.ones((5, 5), dtype=bool)
    inside_mask[:, 0] = False  # exclude the westmost column -- "outside the true basin boundary"

    acc_clipped, _fdir_c, valid_clipped, _cond_c = _run_pysheds_pipeline(
        _V_VALLEY_ELEVATION, grid, dem_nodata=-9999.0, inside_mask=inside_mask
    )
    acc_unclipped, _fdir_u, _valid_u, _cond_u = _run_pysheds_pipeline(
        _V_VALLEY_ELEVATION, grid, dem_nodata=-9999.0, inside_mask=None
    )

    # Excluded column is nodata in the clipped run and contributes to
    # neither its own nor anyone else's accumulation.
    assert valid_clipped[:, 0].any() == False  # noqa: E712
    assert (acc_clipped[:, 0] == 0).all()

    # The valley-bottom column's accumulation is strictly smaller once
    # the west column can no longer contribute inflow to it -- this is
    # the actual, exercised difference "clip to the true watershed
    # boundary" is supposed to make: a basin has no external inflow.
    # (Row 1 is unaffected: at that depth nothing has yet converged from
    # the excluded column in either the clipped or unclipped case, so
    # both start out equal at 4 -- the difference only shows up from
    # row 2 down, once the exclusion actually removes contributing area.)
    assert (acc_clipped[2:, 2] < acc_unclipped[2:, 2]).all()
    # Hand-verified: [1, 4, 8, 12, 20] vs. the unclipped [1, 4, 9, 14, 25].
    assert list(acc_clipped[:, 2]) == [1.0, 4.0, 8.0, 12.0, 20.0]


def test_polygon_inside_mask_matches_the_polygon_reprojected_onto_the_grid():
    # A grid whose origin/extent is a round UTM box, and a polygon
    # covering exactly its right half -- easy to hand-check which pixels
    # should end up True.
    grid = AOIGrid(crs="EPSG:32645", resolution_m=10.0, origin_x=0.0, origin_y=100.0, width=10, height=10)
    # box() in EPSG:32645 directly (skip the 4326 reprojection round-trip
    # by using a polygon whose CRS transform is identity-like enough to
    # hand-check -- this exercises the reprojection path with a real,
    # if tiny, geographic polygon over Kathmandu).
    from pyproj import Transformer

    to_wgs84 = Transformer.from_crs("EPSG:32645", "EPSG:4326", always_xy=True)
    utm_half = box(50.0, 0.0, 100.0, 100.0)  # right half of the 100x100m grid
    from shapely.ops import transform as shapely_transform

    polygon_4326 = shapely_transform(to_wgs84.transform, utm_half)

    mask = _polygon_inside_mask(polygon_4326, grid)

    assert mask.shape == (10, 10)
    assert not mask[:, :5].any(), "left half (x < 50) must be outside"
    assert mask[:, 5:].all(), "right half (x >= 50) must be inside"


# --- cache versioning: a basin AOI and a same-bbox plain AOI must never collide ---


def _fake_dem_result(elevation: np.ndarray, grid: AOIGrid, nodata: float = -9999.0) -> DEMResult:
    return DEMResult(
        elevation_m=elevation, slope_degrees=np.zeros_like(elevation), grid=grid, nodata=nodata, source_used="fake"
    )


def test_cache_version_differs_between_bbox_and_polygon_aoi_with_the_same_bbox():
    bbox_aoi = AOI(bbox_4326=TEST_AOI_BBOX_4326)
    polygon_aoi = AOI(bbox_4326=TEST_AOI_BBOX_4326, polygon=box(*TEST_AOI_BBOX_4326))

    assert _hydrology_cache_version(bbox_aoi) != _hydrology_cache_version(polygon_aoi)
    # Same bbox -> AOI.cache_key() (the other half of cache.py's key) is
    # identical for both by design (see aoi.py) -- version is the *only*
    # thing standing between them sharing a cache entry.
    assert bbox_aoi.cache_key() == polygon_aoi.cache_key()


def test_bbox_and_polygon_aoi_with_same_bbox_get_separate_cache_entries_on_disk(monkeypatch, tmp_path):
    grid = _small_grid()
    monkeypatch.setattr("app.data.hydrology.get_dem", lambda aoi: _fake_dem_result(_V_VALLEY_ELEVATION, grid))

    bbox_aoi = AOI(bbox_4326=TEST_AOI_BBOX_4326)
    polygon_aoi = AOI(bbox_4326=TEST_AOI_BBOX_4326, polygon=box(*TEST_AOI_BBOX_4326))

    compute_flow_accumulation(bbox_aoi)
    compute_flow_accumulation(polygon_aoi)

    cache_files = sorted((config.PROCESSED_CACHE_DIR / "hydrology").glob("*.pkl"))
    assert len(cache_files) == 2


def test_repeated_call_for_same_aoi_hits_the_processed_cache(monkeypatch, test_aoi):
    grid = _small_grid()
    calls = []

    def fake_get_dem(aoi):
        calls.append(aoi)
        return _fake_dem_result(_V_VALLEY_ELEVATION, grid)

    monkeypatch.setattr("app.data.hydrology.get_dem", fake_get_dem)

    first = compute_flow_accumulation(test_aoi)
    second = compute_flow_accumulation(test_aoi)

    assert len(calls) == 1
    assert np.array_equal(first.flow_accumulation, second.flow_accumulation)


def test_bbox_aoi_result_carries_an_edge_reliability_warning_polygon_aoi_does_not(monkeypatch):
    grid = _small_grid()
    monkeypatch.setattr("app.data.hydrology.get_dem", lambda aoi: _fake_dem_result(_V_VALLEY_ELEVATION, grid))

    bbox_result = compute_flow_accumulation(AOI(bbox_4326=TEST_AOI_BBOX_4326))
    polygon_result = compute_flow_accumulation(AOI(bbox_4326=TEST_AOI_BBOX_4326, polygon=box(*TEST_AOI_BBOX_4326)))

    # attribution is always the plain, unmodified citation -- on both
    # paths -- the warning lives in its own field instead.
    assert bbox_result.attribution == DEM_ATTRIBUTION
    assert polygon_result.attribution == DEM_ATTRIBUTION

    assert bbox_result.clipped_to_polygon is False
    assert bbox_result.warning is not None
    assert "edges" in bbox_result.warning.lower()

    assert polygon_result.clipped_to_polygon is True
    assert polygon_result.warning is None


# --- TWI ---


def test_twi_flat_terrain_floors_slope_instead_of_diverging(monkeypatch):
    """On perfectly flat ground, raw slope is 0 and tan(0) = 0, so an
    unfloored TWI = ln(alpha / 0) would be +inf -- not a usable risk
    value. get_twi must floor slope to MIN_SLOPE_RADIANS first. Flow
    accumulation is faked directly (rather than run through pysheds'
    real, and much messier, flat-resolution behavior) so this test
    isolates exactly the slope-flooring logic in get_twi itself.
    """
    grid = _small_grid()
    flat_elevation = np.full((5, 5), 1300.0, dtype=np.float64)
    monkeypatch.setattr("app.data.hydrology.get_dem", lambda aoi: _fake_dem_result(flat_elevation, grid))

    fake_flow = FlowAccumulationResult(
        flow_accumulation=np.full((5, 5), 4.0),
        flow_direction=np.zeros((5, 5), dtype=np.int64),
        grid=grid,
        nodata=HYDROLOGY_NODATA,
        valid_mask=np.ones((5, 5), dtype=bool),
        clipped_to_polygon=False,
        attribution="fake attribution",
    )
    monkeypatch.setattr("app.data.hydrology.compute_flow_accumulation", lambda aoi: fake_flow)

    result = get_twi(AOI(bbox_4326=TEST_AOI_BBOX_4326))

    assert np.isfinite(result.twi).all()
    # Hand-verified: alpha (Moore et al. 1991 convention) = flow_accum *
    # resolution_m = 4.0 * 10.0 = 40.0; tan(MIN_SLOPE_RADIANS) is used in
    # place of tan(0); ln(40 / tan(0.001)) = 10.5966...
    expected = np.log(40.0 / np.tan(MIN_SLOPE_RADIANS))
    assert result.twi == pytest.approx(expected, abs=1e-3)
    assert result.nodata == HYDROLOGY_NODATA
    assert result.attribution == "fake attribution"
    assert result.warning is None


def test_twi_is_nodata_where_flow_accumulation_is_invalid(monkeypatch):
    grid = _small_grid()
    monkeypatch.setattr("app.data.hydrology.get_dem", lambda aoi: _fake_dem_result(_V_VALLEY_ELEVATION, grid))

    valid_mask = np.ones((5, 5), dtype=bool)
    valid_mask[4, 2] = False  # e.g. the unresolved domain-edge outlet
    fake_flow = FlowAccumulationResult(
        flow_accumulation=np.full((5, 5), 4.0),
        flow_direction=np.zeros((5, 5), dtype=np.int64),
        grid=grid,
        nodata=HYDROLOGY_NODATA,
        valid_mask=valid_mask,
        clipped_to_polygon=False,
        attribution="fake",
    )
    monkeypatch.setattr("app.data.hydrology.compute_flow_accumulation", lambda aoi: fake_flow)

    result = get_twi(AOI(bbox_4326=TEST_AOI_BBOX_4326))

    assert result.twi[4, 2] == HYDROLOGY_NODATA


def test_twi_propagates_the_flow_accumulation_warning(monkeypatch):
    grid = _small_grid()
    monkeypatch.setattr("app.data.hydrology.get_dem", lambda aoi: _fake_dem_result(_V_VALLEY_ELEVATION, grid))
    fake_flow = FlowAccumulationResult(
        flow_accumulation=np.full((5, 5), 4.0),
        flow_direction=np.zeros((5, 5), dtype=np.int64),
        grid=grid,
        nodata=HYDROLOGY_NODATA,
        valid_mask=np.ones((5, 5), dtype=bool),
        clipped_to_polygon=False,
        attribution="fake",
        warning="fake edge-reliability warning",
    )
    monkeypatch.setattr("app.data.hydrology.compute_flow_accumulation", lambda aoi: fake_flow)

    result = get_twi(AOI(bbox_4326=TEST_AOI_BBOX_4326))

    assert result.warning == "fake edge-reliability warning"


# --- drainage density ---


def test_compute_drainage_density_raster_hand_verified_single_stream_pixel():
    flow_acc = np.ones((5, 5), dtype=np.float64)
    flow_acc[2, 2] = 10.0  # the only pixel at/above the threshold
    valid = np.ones((5, 5), dtype=bool)

    density = compute_drainage_density_raster(
        flow_acc, valid, resolution_m=10.0, threshold_cells=5, window_radius_m=10.0
    )

    # Hand-verified: radius_px=1 gives a 5-cell "plus" kernel (corners
    # excluded, since sqrt(2) > 1). Window area = 5 * 10*10 m^2 = 500 m^2
    # = 0.0005 km^2. The one stream pixel contributes 10m = 0.01km. Every
    # pixel whose plus-shaped window includes (2,2) -- itself plus its 4
    # orthogonal neighbors -- gets 0.01/0.0005 = 20 km/km^2; every other
    # pixel gets 0.
    expected = np.zeros((5, 5), dtype=np.float32)
    expected[2, 2] = expected[1, 2] = expected[3, 2] = expected[2, 1] = expected[2, 3] = 20.0
    assert density == pytest.approx(expected, abs=1e-4)


def test_compute_drainage_density_raster_below_threshold_everywhere_is_all_zero():
    flow_acc = np.full((5, 5), 2.0)
    valid = np.ones((5, 5), dtype=bool)

    density = compute_drainage_density_raster(
        flow_acc, valid, resolution_m=10.0, threshold_cells=500, window_radius_m=50.0
    )

    assert (density == 0.0).all()


def test_get_drainage_density_reads_threshold_and_radius_from_config(monkeypatch):
    grid = _small_grid()
    monkeypatch.setattr("app.data.hydrology.get_dem", lambda aoi: _fake_dem_result(_V_VALLEY_ELEVATION, grid))
    monkeypatch.setattr(config, "DRAINAGE_DENSITY_THRESHOLD_CELLS", 5)
    monkeypatch.setattr(config, "DRAINAGE_DENSITY_WINDOW_RADIUS_M", 10.0)

    result = get_drainage_density(AOI(bbox_4326=TEST_AOI_BBOX_4326))

    # Valley-bottom column reaches accumulation >= 5 by row 2 (value 9) —
    # those pixels (and their plus-shaped neighborhoods) must be > 0.
    assert result.drainage_density[2, 2] > 0.0
    assert result.nodata == HYDROLOGY_NODATA
    # A plain bbox AOI (no polygon) -> the real compute_flow_accumulation
    # pipeline's edge-reliability warning propagates all the way through.
    assert result.warning is not None


def test_get_drainage_density_propagates_the_flow_accumulation_warning(monkeypatch):
    grid = _small_grid()
    fake_flow = FlowAccumulationResult(
        flow_accumulation=np.full((5, 5), 4.0),
        flow_direction=np.zeros((5, 5), dtype=np.int64),
        grid=grid,
        nodata=HYDROLOGY_NODATA,
        valid_mask=np.ones((5, 5), dtype=bool),
        clipped_to_polygon=True,
        attribution="fake",
        warning=None,
    )
    monkeypatch.setattr("app.data.hydrology.compute_flow_accumulation", lambda aoi: fake_flow)

    result = get_drainage_density(AOI(bbox_4326=TEST_AOI_BBOX_4326, polygon=box(*TEST_AOI_BBOX_4326)))

    assert result.warning is None  # a clipped (basin-derived) AOI has nothing to flag


def test_get_drainage_density_cache_busts_when_threshold_changes(monkeypatch):
    grid = _small_grid()
    monkeypatch.setattr("app.data.hydrology.get_dem", lambda aoi: _fake_dem_result(_V_VALLEY_ELEVATION, grid))
    aoi = AOI(bbox_4326=TEST_AOI_BBOX_4326)

    monkeypatch.setattr(config, "DRAINAGE_DENSITY_THRESHOLD_CELLS", 5)
    low_threshold = get_drainage_density(aoi)

    monkeypatch.setattr(config, "DRAINAGE_DENSITY_THRESHOLD_CELLS", 10_000)
    high_threshold = get_drainage_density(aoi)

    # An unreachably high threshold means no pixel is ever a "stream" ->
    # density is 0 everywhere valid data exists (the one invalid pixel,
    # the domain-edge outlet, stays HYDROLOGY_NODATA regardless of
    # threshold -- that's a validity fact, not a density value). If this
    # came back identical to low_threshold's result, the cache would
    # have wrongly reused the earlier computation despite the config
    # change.
    assert not np.array_equal(low_threshold.drainage_density, high_threshold.drainage_density)
    still_valid = high_threshold.drainage_density != HYDROLOGY_NODATA
    assert (high_threshold.drainage_density[still_valid] == 0.0).all()


# --- HAND (Height Above Nearest Drainage) ---
#
# Every expected number below was hand-verified against a direct pysheds
# `compute_hand` run on this exact V-shaped-valley DEM during
# implementation (same methodology this file's own header comment
# describes for the flow-accumulation numbers) -- not just asserted from
# a first successful run. One real, load-bearing discovery from that
# verification, not previously documented anywhere in this codebase:
# pysheds' compute_hand cannot resolve the OUTER 1-PIXEL RING of any
# finite grid (confirmed on grids from 5x5 up to 11x11) -- a border cell
# never has a full D8 neighborhood to trace a path through, regardless of
# how close it is to a stream cell, so it always comes back unresolved
# (raw NaN from pysheds, remapped to HYDROLOGY_NODATA by get_hand). This
# is a strictly worse edge effect than flow accumulation's own
# "underestimated near the edges" (EDGE_RELIABILITY_WARNING) -- HAND's
# edge pixels aren't underestimated, they're nodata outright -- but per
# the explicit instruction to reuse that warning rather than invent a
# second channel, get_hand still surfaces the same warning text/field on
# a bbox AOI. Flagged as a decision to confirm.


def test_compute_hand_raster_hand_verified_on_the_v_valley_dem():
    grid = _small_grid()
    acc, fdir, valid, conditioned = _run_pysheds_pipeline(_V_VALLEY_ELEVATION, grid, dem_nodata=-9999.0, inside_mask=None)
    # Same threshold convention as drainage_density's own stream
    # extraction (valid_mask & flow_accumulation >= threshold) -- (2, 2)
    # and (3, 2) are the only two cells at/above it (acc centerline is
    # [1, 4, 9, 14, 25]); (4, 2)'s acc=25 also clears it but that cell is
    # the domain's unresolved pit (invalid), so it's correctly excluded
    # from the stream mask, matching compute_drainage_density_raster's
    # own `valid_mask & (...)` gate.
    stream_mask = valid & (acc >= 9)
    assert list(zip(*np.where(stream_mask))) == [(2, 2), (3, 2)]

    hand = _compute_hand_raster(fdir, conditioned, stream_mask, grid, HYDROLOGY_NODATA)

    # On the stream itself: HAND ~ 0.
    assert hand[2, 2] == pytest.approx(0.0, abs=1e-6)
    assert hand[3, 2] == pytest.approx(0.0, abs=1e-6)
    # (1, 2): elevation 90, flows S directly into (2, 2) (elevation 80) --
    # one hop, HAND = 90 - 80 = 10.
    assert hand[1, 2] == pytest.approx(10.0, abs=1e-6)
    # (1, 1): elevation 100, flows SE directly into (2, 2) (elevation
    # 80) -- one diagonal hop, HAND = 100 - 80 = 20. High above the
    # stream, and hand-verified via a different (diagonal) path than
    # (1, 2)'s, so this isn't just the same number twice by coincidence.
    assert hand[1, 1] == pytest.approx(20.0, abs=1e-6)
    # (2, 1): elevation 90, flows SE directly into (3, 2) (elevation 70)
    # -- HAND = 90 - 70 = 20.
    assert hand[2, 1] == pytest.approx(20.0, abs=1e-6)

    # The outer ring (row 0, row 4, col 0, col 4) is unresolved --
    # documented pysheds edge behavior, not a bug -- see this section's
    # own header comment.
    assert np.isnan(hand[0, :]).all()
    assert np.isnan(hand[:, 0]).all()
    assert np.isnan(hand[:, 4]).all()


def test_get_hand_remaps_unresolved_edge_pixels_to_hydrology_nodata(monkeypatch):
    grid = _small_grid()
    monkeypatch.setattr("app.data.hydrology.get_dem", lambda aoi: _fake_dem_result(_V_VALLEY_ELEVATION, grid))
    monkeypatch.setattr(config, "DRAINAGE_DENSITY_THRESHOLD_CELLS", 9)

    result = get_hand(AOI(bbox_4326=TEST_AOI_BBOX_4326))

    # The raw np.nan pysheds returns for an unresolved edge pixel must
    # never leak into the public result -- only the project's own
    # explicit sentinel.
    assert not np.isnan(result.hand).any()
    assert result.hand[0, 0] == HYDROLOGY_NODATA
    assert result.hand[2, 2] == pytest.approx(0.0, abs=1e-6)  # on the stream
    assert result.hand[1, 1] == pytest.approx(20.0, abs=1e-6)  # hand-verified above
    assert result.nodata == HYDROLOGY_NODATA


def test_get_hand_reuses_the_cached_flow_accumulation_not_a_duplicate_sink_fill(monkeypatch):
    """The whole point of HAND consuming compute_flow_accumulation's
    result object rather than re-deriving flow direction/the stream
    network itself: computing another hydrology source for the same AOI
    first (warming the per-AOI cache), then get_hand, must run the
    actual pysheds sink-fill/flow-direction pipeline exactly once total
    -- not once per source.
    """
    grid = _small_grid()
    monkeypatch.setattr("app.data.hydrology.get_dem", lambda aoi: _fake_dem_result(_V_VALLEY_ELEVATION, grid))
    monkeypatch.setattr(config, "DRAINAGE_DENSITY_THRESHOLD_CELLS", 9)

    calls = []
    real_pipeline = _run_pysheds_pipeline

    def counting_pipeline(*args, **kwargs):
        calls.append(1)
        return real_pipeline(*args, **kwargs)

    monkeypatch.setattr("app.data.hydrology._run_pysheds_pipeline", counting_pipeline)

    aoi = AOI(bbox_4326=TEST_AOI_BBOX_4326)
    get_drainage_density(aoi)
    get_hand(aoi)

    assert len(calls) == 1


def test_get_hand_bbox_aoi_carries_edge_reliability_warning_polygon_aoi_does_not(monkeypatch):
    grid = _small_grid()
    monkeypatch.setattr("app.data.hydrology.get_dem", lambda aoi: _fake_dem_result(_V_VALLEY_ELEVATION, grid))
    monkeypatch.setattr(config, "DRAINAGE_DENSITY_THRESHOLD_CELLS", 9)

    bbox_result = get_hand(AOI(bbox_4326=TEST_AOI_BBOX_4326))
    polygon_result = get_hand(AOI(bbox_4326=TEST_AOI_BBOX_4326, polygon=box(*TEST_AOI_BBOX_4326)))

    # attribution is always the plain, unmodified citation on both paths
    # -- same convention as every other hydrology source.
    assert bbox_result.attribution == DEM_ATTRIBUTION
    assert polygon_result.attribution == DEM_ATTRIBUTION

    assert bbox_result.warning is not None
    assert "edges" in bbox_result.warning.lower()
    assert polygon_result.warning is None


def test_get_hand_propagates_a_fake_flow_accumulation_warning(monkeypatch):
    """Narrower companion to the bbox-vs-polygon test above: proves
    get_hand's warning comes from compute_flow_accumulation's own result
    (whatever it is), not re-derived independently -- by faking a
    FlowAccumulationResult with an arbitrary warning string and confirming
    it passes straight through unchanged.
    """
    grid = _small_grid()
    fake_flow = FlowAccumulationResult(
        flow_accumulation=np.full((5, 5), 20.0),
        flow_direction=np.full((5, 5), 4, dtype=np.int64),
        grid=grid,
        nodata=HYDROLOGY_NODATA,
        valid_mask=np.ones((5, 5), dtype=bool),
        clipped_to_polygon=False,
        attribution="fake",
        warning="fake edge-reliability warning",
        elevation_conditioned=_V_VALLEY_ELEVATION.copy(),
    )
    monkeypatch.setattr("app.data.hydrology.compute_flow_accumulation", lambda aoi: fake_flow)
    monkeypatch.setattr(config, "DRAINAGE_DENSITY_THRESHOLD_CELLS", 5)

    result = get_hand(AOI(bbox_4326=TEST_AOI_BBOX_4326))

    assert result.warning == "fake edge-reliability warning"


def test_get_hand_cache_busts_when_drainage_threshold_changes(monkeypatch):
    """HAND shares drainage_density's stream-network threshold (see this
    section's own header comment) -- recalibrating it later must
    invalidate HAND's cache too, exactly like drainage_density's own
    equivalent test.
    """
    grid = _small_grid()
    monkeypatch.setattr("app.data.hydrology.get_dem", lambda aoi: _fake_dem_result(_V_VALLEY_ELEVATION, grid))
    aoi = AOI(bbox_4326=TEST_AOI_BBOX_4326)

    monkeypatch.setattr(config, "DRAINAGE_DENSITY_THRESHOLD_CELLS", 9)
    low_threshold = get_hand(aoi)

    monkeypatch.setattr(config, "DRAINAGE_DENSITY_THRESHOLD_CELLS", 10_000)
    high_threshold = get_hand(aoi)

    # An unreachably high threshold means no cell is ever a "stream" ->
    # every resolvable pixel's HAND collapses to nodata (no drainage to
    # measure height above). If this came back identical to
    # low_threshold's result, the cache would have wrongly reused the
    # earlier computation despite the config change.
    assert not np.array_equal(low_threshold.hand, high_threshold.hand)
    assert (high_threshold.hand == HYDROLOGY_NODATA).all()
