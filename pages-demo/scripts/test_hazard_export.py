"""Scientific edge cases and exported artifact checks; no raw inputs fetched."""
import importlib.util
import json
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('export_hazard',Path(__file__).with_name('export-hazard.py'))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
np=module.np

class HazardExportTests(unittest.TestCase):
    def test_rq3_half_class_boundaries_and_float_noise(self):
        np.testing.assert_array_equal(module.score_classes(np.array([1,1.5,2.5,3.49999,3.5-1e-12,4.5,5])),[1,2,3,3,4,5,5])

    def test_threshold_direction_and_exact_edges(self):
        values=np.array([0,1,2,3,4,5],dtype=float)
        np.testing.assert_array_equal(module.classify(values,'twi',{'twi':[1,2,3,4]}),[1,2,3,4,5,5])
        np.testing.assert_array_equal(module.classify(values,'hand',{'hand':[1,2,3,4]}),[5,4,3,2,1,1])

    def test_landcover_is_fixed_not_continuous(self):
        np.testing.assert_array_equal(module.classify(np.array([10,40,50,80,90]),'worldcover_land_cover',{}),[1,3,5,5,5])

    def test_outward_grid_snap_uses_all_four_corners(self):
        class Transform:
            def transform(self,x,y): return [1,8,23,21],[1,34,3,29]
        self.assertEqual(module.grid([0,0,1,1],Transform()),(0,40,3,4))

    def test_published_weights_and_artifacts(self):
        manifest=json.loads((module.OUT/'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(len(set(manifest['validatedUnits'])),366)
        self.assertEqual(manifest['overlappingSamples'],0)
        w=module.weights()
        self.assertTrue(np.all(w>=0))
        np.testing.assert_allclose(w.sum(axis=1),1,atol=.0001)
        for scheme in module.IDS:
            im=module.Image.open(module.OUT/f'{scheme}.png')
            self.assertEqual(im.size,(3320,1680))
            self.assertEqual(im.info['transparency'],0)
            self.assertEqual(set(np.unique(np.array(im))),set(range(6)))
            self.assertGreater(np.count_nonzero(np.array(im)),1000000)

    def test_basin_view_is_distinct_with_matching_valid_domain(self):
        for scheme in module.IDS:
            national=np.array(module.Image.open(module.OUT/f'{scheme}.png'))
            basin=np.array(module.Image.open(module.OUT/f'basin_{scheme}.png'))
            np.testing.assert_array_equal(national>0,basin>0)
            self.assertGreater(np.count_nonzero(national!=basin),10000)
            self.assertEqual(set(np.unique(basin)),set(range(6)))

    def test_mercator_overlay_matches_geographic_samples(self):
        # Independently locate geographic points in both projections. Flat
        # stretching would disagree by several rows over Nepal's latitude span.
        from pyproj import Transformer
        project=Transformer.from_crs(4326,3857,always_xy=True)
        _,south=project.transform(80,26.3);_,north=project.transform(88.3,30.5)
        for prefix in ['', 'basin_']:
            original=np.array(module.Image.open(module.OUT/f'{prefix}expert_median.png'))
            warped=np.array(module.Image.open(module.OUT/f'{prefix}expert_median_3857.png'))
            for row in [10,400,800,1200,1660]:
                # Inverse projection of the center of a display row.
                inverse=Transformer.from_crs(3857,4326,always_xy=True)
                _,lat=inverse.transform(0,north-(row+.5)*(north-south)/1680)
                geographic_row=int((30.5-lat)/4.2*1680)
                np.testing.assert_array_equal(warped[row],original[geographic_row])

    def test_basin_ids_match_the_cached_research_units(self):
        collection=json.loads((module.OUT.parent/'basins.json').read_text(encoding='utf-8'))
        manifest=json.loads((module.OUT/'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual({f['properties']['id'] for f in collection['features']},set(manifest['validatedUnits']))
        for feature in collection['features']:
            self.assertIn(feature['geometry']['type'],['Polygon','MultiPolygon'])
            self.assertGreater(feature['properties']['areaInNepalKm2'],0)

if __name__=='__main__': unittest.main()
