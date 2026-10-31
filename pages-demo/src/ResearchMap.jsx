import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { colorFor, displayValue, metricValue } from './demoData'

const asset = path => `${import.meta.env.BASE_URL}demo/${path}`
const imageryUrl = 'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
const imageryCredit = 'Imagery: Esri, Vantor, Earthstar Geographics, and the GIS User Community'
const latLngBounds = ([west,south,east,north]) => [[south,west],[north,east]]

export default function ResearchMap({data, scheme, metric, selected, onSelect, showHazard, opacity, classification, onClassificationChange}) {
  const element=useRef(null), map=useRef(null), districtLayer=useRef(null), basinLayer=useRef(null)
  const [ready,setReady]=useState(false), [basins,setBasins]=useState(null), [basinError,setBasinError]=useState('')
  const [basin,setBasin]=useState(''), [boundaries,setBoundaries]=useState('districts')
  const [background,setBackground]=useState('none')
  const [imageError,setImageError]=useState(false), [tileError,setTileError]=useState(false)
  const [level,setLevel]=useState(0), [expanded,setExpanded]=useState(false)
  const nationalBounds=latLngBounds(data.hazard?.bounds || [80,26.3,88.3,30.5])
  const selectedBasin=basins?.features.find(f=>f.properties.id===basin)
  const reset=()=>map.current?.fitBounds(nationalBounds,{padding:[15,15],animate:false})

  useEffect(()=>{
    const controller=new AbortController()
    fetch(asset('basins.json'),{signal:controller.signal}).then(r=>{if(!r.ok)throw new Error('Basin outlines are unavailable.');return r.json()})
      .then(value=>{if(value.type!=='FeatureCollection'||!value.features?.length)throw new Error('Invalid basin outlines.');setBasins(value)})
      .catch(e=>{if(e.name!=='AbortError')setBasinError(e.message)})
    return()=>controller.abort()
  },[])

  useEffect(()=>{
    const instance=L.map(element.current,{zoomControl:false,minZoom:5,maxZoom:16,zoomSnap:.25,
      scrollWheelZoom:false,attributionControl:true,zoomAnimation:false,fadeAnimation:false})
    map.current=instance
    instance.fitBounds(nationalBounds,{padding:[15,15]})
    instance.on('zoomend',()=>setLevel(instance.getZoom()))
    setLevel(instance.getZoom())
    L.control.scale({imperial:false}).addTo(instance)
    const observer=new ResizeObserver(()=>instance.invalidateSize())
    observer.observe(element.current)
    setReady(true)
    return()=>{observer.disconnect();instance.remove();map.current=null}
  },[])

  useEffect(()=>{
    if(!ready||background==='none')return
    setTileError(false)
    const tiles=L.tileLayer(imageryUrl,{attribution:`<a href="https://www.arcgis.com/home/item.html?id=10df2279f9684e4a9f6a7f08febac2a9" target="_blank" rel="noreferrer">${imageryCredit}</a>`,maxZoom:16,noWrap:true})
    tiles.on('tileerror',()=>setTileError(true));tiles.addTo(map.current)
    return()=>tiles.remove()
  },[ready,background])

  useEffect(()=>{
    if(!ready||!showHazard)return
    setImageError(false)
    const files=classification==='basin'?data.hazard.basinWebMercatorFiles:data.hazard.webMercatorFiles
    if(!files?.[scheme]){setImageError(true);return}
    const image=L.imageOverlay(asset(files[scheme]),nationalBounds,{opacity,alt:'Precomputed flood susceptibility raster',className:'demo-hazard-image'})
    image.on('error',()=>setImageError(true));image.addTo(map.current)
    image.getElement().setAttribute('data-testid','hazard-raster')
    return()=>image.remove()
  },[ready,showHazard,scheme,opacity,classification,data])

  useEffect(()=>{
    if(!ready)return
    const features=data.districts.map(d=>({type:'Feature',properties:d,geometry:d.geometry}))
    const layer=L.geoJSON(features,{interactive:boundaries!=='basins'||!showHazard,style:f=>({color:f.properties.code===selected?'#ad5135':'#fff',
      weight:f.properties.code===selected?2.5:.8,fillColor:colorFor(metricValue(f.properties.values[scheme],metric),metric),
      fillOpacity:showHazard?0:.85,opacity:boundaries==='districts'||!showHazard?1:0}),
      onEachFeature:(f,polygon)=>{
        const d=f.properties, label=`${d.name}: ${displayValue(metricValue(d.values[scheme],metric),metric)}`
        polygon.bindTooltip(label,{sticky:true})
        polygon.on('click',()=>onSelect(d.code))
        polygon.on('add',()=>{
          const path=polygon.getElement();if(!path)return
          path.setAttribute('role','button');path.setAttribute('tabindex','0');path.setAttribute('aria-label',label)
          path.setAttribute('aria-pressed',String(d.code===selected))
          path.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();onSelect(d.code)}})
        })
      }}).addTo(map.current)
    districtLayer.current=layer
    return()=>{layer.remove();districtLayer.current=null}
  },[ready,data,scheme,metric,selected,showHazard,boundaries,onSelect])

  useEffect(()=>{
    if(!ready||!basins||boundaries!=='basins')return
    const layer=L.geoJSON(basins,{style:f=>({color:f.properties.id===basin?'#f8e05e':'#324d5b',
      weight:f.properties.id===basin?3:1,fillOpacity:0}),onEachFeature:(f,polygon)=>{
      polygon.bindTooltip(f.properties.label,{sticky:true})
      polygon.on('click',()=>{setBasin(f.properties.id);map.current.fitBounds(polygon.getBounds(),{padding:[25,25],maxZoom:13,animate:false})})
    }}).addTo(map.current)
    basinLayer.current=layer
    return()=>{layer.remove();basinLayer.current=null}
  },[ready,basins,basin,boundaries])

  const selectBasin=id=>{
    setBasin(id);setBoundaries('basins')
    const f=basins?.features.find(f=>f.properties.id===id)
    if(f)map.current.fitBounds(latLngBounds(f.bbox),{padding:[25,25],maxZoom:13,animate:false})
    else reset()
  }
  const zoomDistrict=()=>{
    const polygon=districtLayer.current?.getLayers().find(l=>l.feature.properties.code===selected)
    if(polygon)map.current.fitBounds(polygon.getBounds(),{padding:[25,25],maxZoom:13,animate:false})
  }

  return <div className={`demo-slippy-section ${expanded?'is-expanded':''}`}>
    <div className="demo-map-options">
      {showHazard&&<label>Raster classification<select value={classification} onChange={e=>onClassificationChange(e.target.value)}><option value="national">National breaks</option><option value="basin">Basin-relative quintiles</option></select></label>}
      <label>Background imagery<select value={background} onChange={e=>setBackground(e.target.value)}><option value="none">None (offline background)</option><option value="satellite">Satellite imagery (online)</option></select></label>
      <label>Boundary overlay<select value={boundaries} onChange={e=>setBoundaries(e.target.value)}><option value="districts">Districts</option><option value="basins">Research basins</option><option value="none">None</option></select></label>
      <label>Zoom to research basin<select value={basin} disabled={!basins} onChange={e=>selectBasin(e.target.value)}><option value="">All Nepal{basins?` (${basins.features.length} basins)`:''}</option>{basins?.features.map(f=><option key={f.properties.id} value={f.properties.id}>{f.properties.label}</option>)}</select></label>
    </div>
    <div className="demo-map-header"><span>{showHazard?'PRECOMPUTED SUSCEPTIBILITY RASTER':'PRECOMPUTED DISTRICT EXPOSURE'}</span>
      <div className="demo-map-zoom"><button aria-label="Zoom out" onClick={()=>map.current?.zoomOut()}>−</button><span data-testid="map-zoom">z{level.toFixed(2)}</span><button aria-label="Zoom in" onClick={()=>map.current?.zoomIn()}>+</button><button onClick={()=>{setBasin('');reset()}}>Reset</button><button onClick={zoomDistrict}>Zoom to district</button><button aria-pressed={expanded} onClick={()=>setExpanded(v=>!v)}>{expanded?'Compact map':'Enlarge map'}</button></div>
    </div>
    <div ref={element} className="demo-slippy-map" role="region" aria-label="Interactive susceptibility map. Drag to pan, pinch or use zoom buttons; keyboard arrows pan and plus or minus zoom." />
    <p className="demo-map-help">Drag to pan · double-click or pinch to zoom · Shift-drag to zoom to a rectangle. Keyboard: arrows to pan, +/− to zoom. Satellite imagery is optional and needs internet; it is not live flood imagery.</p>
    {basinError&&<p role="status">{basinError} Raster and district navigation remain available.</p>}
    {imageError&&<p role="alert">The susceptibility raster could not be loaded. Reload the page or switch classification.</p>}
    {tileError&&background==='satellite'&&<p role="status">Some background imagery could not load. The local research raster remains available; switch background to None if offline.</p>}
    {selectedBasin&&<p className="demo-basin-note"><strong>{selectedBasin.properties.label}</strong> · {selectedBasin.properties.areaInNepalKm2.toLocaleString()} km² inside Nepal. Full basin outline shown; susceptibility coverage is Nepal-only. District cards report the selected district, not this basin.</p>}
    {boundaries==='basins'&&<p className="demo-map-help">{basins?.attribution} <a href={basins?.source} target="_blank" rel="noreferrer">HydroBASINS source</a></p>}
    {showHazard&&<p className="demo-classification-note"><strong>{classification==='basin'?'Basin-relative raster: ':'National-break raster: '}</strong>{classification==='basin'?data.hazard.basinMethod:'One set of national criterion thresholds across all basins. District and national exposure summaries use national breaks.'}</p>}
  </div>
}
