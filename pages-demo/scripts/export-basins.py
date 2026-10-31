"""Publish simplified research basin outlines; no private incident records."""
import importlib.util
import json
from pathlib import Path
spec=importlib.util.spec_from_file_location('hazard',Path(__file__).with_name('export-hazard.py'))
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
np=h.np

def simplify(points,tolerance=.001):
    a=np.asarray(points,dtype=float)[:,:2]
    if len(a)<=4: return a.round(5).tolist()
    # Iterative RDP retains endpoints and all vertices beyond tolerance.
    keep={0,len(a)-1}; stack=[(0,len(a)-1)]
    while stack:
        lo,hi=stack.pop()
        if hi-lo<=1: continue
        line=a[hi]-a[lo]; length=float(line@line)
        middle=a[lo+1:hi]
        if length:
            t=np.clip(((middle-a[lo])@line)/length,0,1)
            distance=np.linalg.norm(middle-(a[lo]+t[:,None]*line),axis=1)
        else: distance=np.linalg.norm(middle-a[lo],axis=1)
        idx=int(np.argmax(distance))
        if distance[idx]>tolerance:
            split=lo+idx+1;keep.add(split);stack.extend([(lo,split),(split,hi)])
    result=a[sorted(keep)].round(5).tolist()
    return result if len(result)>=4 else a.round(5).tolist()

def export():
    manifest=json.loads((h.OUT/'manifest.json').read_text(encoding='utf-8'))
    wanted={int(tag.split('_')[0]):tag for tag in manifest['validatedUnits']}
    units={int(r['hybas']):r for r in h.rows('backend/data/cache/v2/units.csv')}
    features=[]
    for level in [8,9]:
        reader=h.shapefile.Reader(str(h.ROOT/f'backend/data/raw/basins/hybas_as_lev0{level}_v1c/hybas_as_lev0{level}_v1c.shp'))
        for i,r in enumerate(reader.iterRecords()):
            code=int(r['HYBAS_ID'])
            if code not in wanted: continue
            shape=reader.shape(i);geo=shape.__geo_interface__
            if geo['type']=='Polygon': coords=[simplify(ring) for ring in geo['coordinates']]
            elif geo['type']=='MultiPolygon': coords=[[simplify(ring) for ring in poly] for poly in geo['coordinates']]
            else: raise ValueError(geo['type'])
            unit=units[code]
            features.append(dict(type='Feature',properties=dict(id=wanted[code],hybas=str(code),level=level,
                label=('Kathmandu Valley / ' if code==4080848980 else '')+f'HydroBASINS {code} (L{level})',
                areaInNepalKm2=float(unit['area_in_nepal_km2']),eventUnit=unit['event_unit']),
                bbox=list(shape.bbox),geometry=dict(type=geo['type'],coordinates=coords)))
        reader.close()
    assert len(features)==len(wanted)
    collection=dict(type='FeatureCollection',features=sorted(features,key=lambda f:f['properties']['label']),
        attribution='HydroBASINS / HydroSHEDS, WWF. Basin outlines simplified at 0.001 degree tolerance; full basin outlines may extend outside Nepal. Raster coverage remains Nepal-only.',
        source='https://www.hydrosheds.org/products/hydrobasins')
    out=h.OUT.parent/'basins.json';out.write_text(json.dumps(collection,separators=(',',':')),encoding='utf-8')
    print(f'Exported {len(features)} research basin outlines, {out.stat().st_size:,} bytes')

if __name__=='__main__': export()
