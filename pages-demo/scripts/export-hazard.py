"""Export nearest-cell categorical overviews from canonical Tier A caches.
Local preparation only: pip install numpy pillow pyproj pyshp.
"""
import csv
import hashlib
import json
import math
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.hazard-export'))
import numpy as np
from PIL import Image
from pyproj import Transformer
import shapefile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'pages-demo/public/demo/hazard'
CRITERIA = ['dem_elevation','dem_slope','twi','hand','drainage_density','dist_to_river','soil_infiltration','worldcover_land_cover']
IDS = ['expert_median','expert_median_nepal','equal8','fitted_cluster','fitted_full']
COLORS = ['#32885b','#a8c66c','#f5d56b','#ee964b','#c94c43']

def rows(path):
    with (ROOT/path).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def weights():
    experts = {r['set_id']:r for r in rows('expert_weights.csv') if r['excluded'] != 'yes'}
    result = []
    for region in [None, 'Nepal']:
        sets = [json.loads(r['weights_mapped_arm_a']) for r in experts.values() if region is None or r['region']==region]
        w = np.median([[s.get(c,0) for c in CRITERIA] for s in sets],axis=0)
        w = w / sum(w); result.append(w / w.sum())
    result.append(np.full(8,1/8))
    fitted = rows('results/rq1_fitted_weights.csv')
    for model in IDS[3:]:
        r = next(r for r in fitted if r['fold']=='ALL' and r['model']==model)
        result.append(np.array([float(r['w_'+c]) for c in CRITERIA]))
    return np.array(result)

def grid(bounds, transform):
    a,b,c,d=bounds
    x,y=transform.transform([a,a,c,c],[b,d,b,d])
    ox=math.floor(min(x)/10)*10; oy=math.ceil(max(y)/10)*10
    return ox,oy,math.ceil((max(x)-ox)/10),math.ceil((oy-min(y))/10)

def classify(values, criterion, breaks):
    if criterion=='worldcover_land_cover':
        lookup=np.zeros(256,dtype=np.uint8)
        for k,v in {10:1,20:2,30:2,40:3,50:5,60:4,70:1,80:5,90:5,95:3,100:2}.items(): lookup[k]=v
        return lookup[values.astype(np.uint8)]
    bins=np.digitize(values.astype(np.float64),breaks[criterion],right=False)
    return bins+1 if criterion in ['twi','drainage_density'] else 5-bins

def score_classes(scores):
    return np.clip(np.floor(np.round(scores,10)+.5),1,5).astype(np.uint8)

def export():
    OUT.mkdir(parents=True,exist_ok=True)
    transform=Transformer.from_crs(4326,32645,always_xy=True)
    w=weights(); breaks={r['criterion']:[float(r['b'+str(i)]) for i in range(1,5)] for r in rows('results/rq3_national_breaks.csv')}
    files=sorted((ROOT/'backend/data/cache/v2/tier_a').glob('*.npz'))
    wanted={int(p.stem.split('_')[0]) for p in files}; bounds={}
    for level in [8,9]:
        reader=shapefile.Reader(str(ROOT/f'backend/data/raw/basins/hybas_as_lev0{level}_v1c/hybas_as_lev0{level}_v1c.shp'))
        for i,r in enumerate(reader.iterRecords()):
            code=int(r['HYBAS_ID'])
            if code in wanted: bounds[code]=reader.shape(i).bbox
        reader.close()
    # Geographic cell centers transformed once; categorical nearest-cell sampling.
    extent=[80.0,26.3,88.3,30.5]; width,height=3320,1680
    lon=extent[0]+(np.arange(width)+.5)*(extent[2]-extent[0])/width
    lat=extent[3]-(np.arange(height)+.5)*(extent[3]-extent[1])/height
    xx,yy=transform.transform(*np.meshgrid(lon,lat))
    images=np.zeros((5,height,width),dtype=np.uint8)
    basin_images=np.zeros_like(images); units=[]; overlaps=0
    for n,path in enumerate(files):
        bbox=bounds[int(path.stem.split('_')[0])]; ox,oy,sw,sh=grid(bbox,transform)
        with np.load(path,allow_pickle=False) as z:
            assert tuple(z['shape'])==(sh,sw), (path.name,z['shape'],(sh,sw))
            col=np.where((lon>=bbox[0]-.01)&(lon<=bbox[2]+.01))[0]
            row=np.where((lat>=bbox[1]-.01)&(lat<=bbox[3]+.01))[0]
            if not len(col) or not len(row): continue
            rr,cc=np.meshgrid(row,col,indexing='ij'); rr=rr.ravel(); cc=cc.ravel()
            sx=np.floor((xx[rr,cc]-ox)/10).astype(np.int64); sy=np.floor((oy-yy[rr,cc])/10).astype(np.int64)
            inside=(sx>=0)&(sx<sw)&(sy>=0)&(sy<sh)
            rr=rr[inside];cc=cc[inside]; source=sy[inside]*sw+sx[inside]
            valid=np.flatnonzero(np.unpackbits(z['valid_bits'],count=sh*sw))
            pos=np.searchsorted(valid,source); good=pos<len(valid)
            good[good]=valid[pos[good]]==source[good]
            rr=rr[good];cc=cc[good];pos=pos[good]
            scores=np.zeros((5,len(pos)),dtype=np.float64)
            basin_scores=np.zeros_like(scores)
            basin_breaks=json.loads(str(z['meta_json']))['per_basin_quintile_breaks']
            for j,c in enumerate(CRITERIA):
                values=z['x_'+c][pos]
                classes=classify(values,c,breaks)
                assert np.all((classes>=1)&(classes<=5))
                scores+=w[:,j,None]*classes
                basin_scores+=w[:,j,None]*classify(values,c,basin_breaks)
            overlaps+=int(np.count_nonzero(images[0,rr,cc]))
            images[:,rr,cc]=score_classes(scores)
            basin_images[:,rr,cc]=score_classes(basin_scores)
            units.append(path.stem)
        if n%25==0: print(f'{n+1}/{len(files)} grids validated',flush=True)
    palette=[0,0,0]+[int(c[i:i+2],16) for c in COLORS for i in [1,3,5]]
    # Leaflet projects image bounds to Web Mercator. Warp the rows explicitly
    # rather than stretching a geographic image linearly in Mercator space.
    north=np.arcsinh(np.tan(np.radians(extent[3])))
    south=np.arcsinh(np.tan(np.radians(extent[1])))
    display_lat=np.degrees(np.arctan(np.sinh(north-(np.arange(height)+.5)*(north-south)/height)))
    source_rows=np.clip(np.floor((extent[3]-display_lat)/(extent[3]-extent[1])*height).astype(int),0,height-1)
    for prefix,stack in [('',images),('basin_',basin_images)]:
        for i,name in enumerate(IDS):
            for suffix,arr in [('',stack[i]),('_3857',stack[i,source_rows,:])]:
                im=Image.fromarray(arr,mode='P'); im.putpalette(palette+[0]*(768-len(palette)))
                im.save(OUT/f'{prefix}{name}{suffix}.png',transparency=0,optimize=True)
    sources=['expert_weights.csv','results/rq1_fitted_weights.csv','results/rq3_national_breaks.csv','optimization_config.yaml']
    manifest=dict(bounds=extent,width=width,height=height,colors=COLORS,files={s:f'hazard/{s}.png' for s in IDS},
        webMercatorFiles={s:f'hazard/{s}_3857.png' for s in IDS},
        basinFiles={s:f'hazard/basin_{s}.png' for s in IDS},
        basinWebMercatorFiles={s:f'hazard/basin_{s}_3857.png' for s in IDS},
        basinMethod='Basin-relative quintiles from each cached research unit; fixed WorldCover classes; same five weight schemes and RQ3 score rounding. Classes are relative to each basin, so adjacent basin boundaries can show discontinuities. District and national exposure cards remain based on national breaks.',
        mapDisplayCRS='EPSG:3857 (nearest-neighbor row reprojection of the geographic overview)',
        description='National susceptibility overview: 0.0025 degree cells (about 250 m), nearest native 10 m cell. Not flood probability or an inundation forecast.',
        method='Eight criteria, national breaks, published weights; scores rounded to ten decimals then floor(score + 0.5), classes 1-5, matching RQ3. Transparent cells are unknown or outside the analysis domain. Zoom enlarges the overview, not its resolution.',
        sourceCRS='EPSG:32645',displayCRS='EPSG:4326',resampling='nearest',validatedUnits=units,overlappingSamples=overlaps,
        weights={s:dict(zip(CRITERIA,w[i].tolist())) for i,s in enumerate(IDS)},breaks=breaks,
        provenance=[dict(path=s,sha256=hashlib.sha256((ROOT/s).read_bytes()).hexdigest()) for s in sources])
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    snapshot=ROOT/'pages-demo/public/demo/snapshot.json'; data=json.loads(snapshot.read_text(encoding='utf-8'));data['hazard']=manifest
    snapshot.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    print(f'Exported five rasters; {len(units)} grids validated; {overlaps} overlapping overview samples.',flush=True)

if __name__=='__main__': export()
