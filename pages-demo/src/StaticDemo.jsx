import { useEffect, useMemo, useState } from 'react'
import { COLORS, METRICS, compact, number, ratio, metricValue, colorFor, displayValue, rankedDistricts, validateSnapshot } from './demoData'
import './static-demo.css'
import ResearchMap from './ResearchMap'

const asset = path => `${import.meta.env.BASE_URL}demo/${path}`
const REPOSITORY = 'https://github.com/bisheshkhanal036-afk/FloodHUBnepal'

export default function StaticDemo({ initialData }) {
  const [classification, setClassification] = useState('national')
  const [layer, setLayer] = useState('hazard'), [opacity, setOpacity] = useState(.9)
  const [data, setData] = useState(initialData ? validateSnapshot(initialData) : null)
  const [error, setError] = useState(''), [attempt, setAttempt] = useState(0)
  const [scheme, setScheme] = useState('expert_median'), [metric, setMetric] = useState('population')
  const [selected, setSelected] = useState('NP0327'), [query, setQuery] = useState('')
  const [page, setPage] = useState(0), [figure, setFigure] = useState('exposure')
  useEffect(() => {
    if (initialData) return
    const controller = new AbortController(); setError(''); setData(null)
    fetch(asset('snapshot.json'), { signal: controller.signal }).then(response => {
      if (!response.ok) throw new Error('The precomputed research snapshot could not be loaded.')
      return response.json()
    }).then(value => setData(validateSnapshot(value))).catch(e => { if (e.name !== 'AbortError') setError(e.message) })
    return () => controller.abort()
  }, [initialData, attempt])
  const showHazard = layer === 'hazard' && !!data?.hazard
  const ranked = useMemo(() => data ? rankedDistricts(data.districts, scheme, metric, query) : [], [data, scheme, metric, query])
  const district = data?.districts.find(d => d.code === selected)
  const values = district?.values[scheme], national = data?.national[scheme]
  const selectedScheme = data?.schemes.find(s => s.id === scheme), selectedFigure = data?.artifacts.find(f => f.id === figure)
  const changeMetric = value => { setMetric(value); setPage(0) }
  const choose = code => setSelected(code)

  return <div className="static-demo">
    <a className="demo-skip" href="#explorer">Skip to district explorer</a>
    <header className="demo-header">
      <a className="demo-brand" href="#top"><img src={`${import.meta.env.BASE_URL}icon.png`} alt="" width="38" height="38" /><span>खोला <span className="demo-brand-en">Khola</span></span></a>
      <nav aria-label="Main navigation"><a href="#explorer">Explore</a><a href="#research">Research</a><a href="#about">About</a><a href={REPOSITORY} target="_blank" rel="noreferrer">Source ↗</a></nav>
      <span className="demo-badge"><span aria-hidden="true" />Static research demo</span>
    </header>

    <main id="top">
      <section className="demo-hero demo-container">
        <div><p className="demo-eyebrow">NEPAL / FLOOD SUSCEPTIBILITY RESEARCH</p><h1>See the pattern.<br /><span>Question the weights.</span></h1>
          <p className="demo-intro">Explore how different weighting choices change mapped exposure across Nepal. Real, precomputed research outputs. No account or analysis server needed.</p>
          <div className="demo-hero-actions"><a className="demo-button" href="#explorer">Explore the districts <span aria-hidden="true">↓</span></a><a className="demo-text-link" href="#about">What this demo can tell you ↗</a></div>
        </div>
        <aside className="demo-snapshot-note"><span className="demo-cross" aria-hidden="true">+</span><p className="demo-eyebrow">A FIXED RESEARCH SNAPSHOT</p><strong>77 districts.{' '}<br />5 ways to weigh{' '}<br />the same landscape.</strong><p>Compare existing results, not new predictions.</p><span>Snapshot · {data?.snapshotDate || '2026-10-31'}</span></aside>
      </section>

      <div className="demo-container"><div className="demo-notice"><strong>Research, not a flood warning.</strong> Classes 4–5 refer to modeled susceptibility. They do not mean residents or buildings are currently flooded. Live analysis, uploads and location assessments are unavailable here.</div></div>

      {!data && <section className="demo-container demo-loading" role={error ? 'alert' : 'status'}><h2>{error ? 'The snapshot is unavailable.' : 'Opening the research snapshot…'}</h2><p>{error || 'Loading district outlines and aggregate results from this site.'}</p>{error && <button className="demo-button" onClick={() => setAttempt(n => n+1)}>Retry loading</button>}</section>}

      {data && <>
        <section id="explorer" className="demo-container demo-section">
          <div className="demo-section-heading"><div><p className="demo-eyebrow">01 / THE DISTRICT EXPLORER</p><h2>One landscape. Different perspectives.</h2></div><a className="demo-download" href={asset('district-exposure.csv')} download>Download aggregate CSV ↓</a></div>
          <div className="demo-controls">
            {data.hazard && <label>Map layer<select value={layer} onChange={e=>{setLayer(e.target.value)}}><option value="hazard">Susceptibility raster</option><option value="exposure">District exposure</option></select></label>}
            {showHazard && <label>Raster opacity<input aria-label="Raster opacity" type="range" min="0.2" max="1" step="0.1" value={opacity} onChange={e=>setOpacity(Number(e.target.value))} /></label>}
            <label>Weighting scheme<select value={scheme} onChange={e => {setScheme(e.target.value);setPage(0)}}>{data.schemes.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
            <label>District summary metric<select value={metric} onChange={e => changeMetric(e.target.value)}>{Object.entries(METRICS).map(([id,m]) => <option value={id} key={id}>{m.label}</option>)}</select></label>
            <label>Inspect a district<select value={selected} onChange={e => choose(e.target.value)}>{[...data.districts].sort((a,b)=>a.name.localeCompare(b.name)).map(d => <option key={d.code} value={d.code}>{d.name}</option>)}</select></label>
          </div>
          <div className="demo-national" aria-live="polite">
            <div><span>Residents in classes 4–5</span><strong>{compact(national.populationHigh)}</strong><small>Census-calibrated estimate</small></div>
            <div><span>Share of mapped land area</span><strong>{ratio(national.areaHigh,national.areaValid).toFixed(1)}%</strong><small>Valid mapped cells only</small></div>
            <div><span>Buildings in classes 4–5</span><strong>{compact(national.buildingsHigh)}</strong><small>Research footprint count</small></div>
            <div className="demo-national-method"><span>Current view</span><strong>{selectedScheme.name}</strong><small>{selectedScheme.detail}</small></div>
          </div>
          <div className="demo-explorer">
            <div className="demo-map-card">
              <ResearchMap data={data} scheme={scheme} metric={metric} selected={selected} onSelect={choose} showHazard={showHazard} opacity={opacity} classification={classification} onClassificationChange={setClassification} />
              {showHazard ? <div className="demo-map-footer"><strong>Modeled flood susceptibility · classes 1–5</strong><div className="demo-map-legend">{data.hazard.colors.map((color,i)=><span key={color}><i style={{background:color}}/><small>{i+1} · {['Very low','Low','Moderate','High','Very high'][i]}</small></span>)}</div><p>{data.hazard.description.replace('National susceptibility','Susceptibility')}</p><p>{classification==='basin'?data.hazard.basinMethod:data.hazard.method}</p><a href={asset('hazard/manifest.json')} download>Download raster methods & provenance</a></div> : <div className="demo-map-footer"><strong>{METRICS[metric].label}</strong><div className="demo-map-legend">{COLORS.map((color,i)=><span key={color}><i style={{background:color}} /><small>{i===0?'Under ':i===4?'≥ ':''}{displayValue(i===0?METRICS[metric].breaks[0]:METRICS[metric].breaks[i-1],metric,true)}{i>0&&i<4?`–${displayValue(METRICS[metric].breaks[i],metric,true)}`:''}</small></span>)}</div><p>Simplified district overview · click or use the district selector · missing coverage is not low susceptibility</p></div>}
            </div>
            <aside className="demo-district-card" aria-live="polite" aria-label="Selected district details"><p className="demo-eyebrow">DISTRICT SPOTLIGHT / {district.code}</p><h3>{district.name}</h3><p className="demo-muted">{district.province} Province</p><div className="demo-spotlight"><span>{METRICS[metric].short}</span><strong data-testid="district-value">{displayValue(metricValue(values,metric),metric,true)}</strong><p>in modeled classes 4–5</p></div>
              <dl><div><dt>Estimated residents</dt><dd>{number(values.populationHigh)}</dd></div><div><dt>Share of mapped population</dt><dd>{displayValue(ratio(values.populationHigh,values.populationValid),'populationShare')}</dd></div><div><dt>Mapped land in classes 4–5</dt><dd>{number(values.areaHigh/1e6)} km²</dd></div><div><dt>Buildings in classes 4–5</dt><dd>{number(values.buildingsHigh)}</dd></div></dl>
              <div className="demo-coverage"><div><span>Mapped land coverage</span><strong>{ratio(values.areaValid,values.areaAll).toFixed(1)}%</strong></div><meter min="0" max="100" value={ratio(values.areaValid,values.areaAll)} aria-label="Mapped land coverage" /><p>Percent of the district analysis area with valid results. Other cells are unknown.</p></div>
            </aside>
          </div>
          <p className="demo-method-note">{data.method} {data.coverage}</p>

          <section className="demo-table-section" aria-label="District ranking"><div className="demo-table-top"><div><p className="demo-eyebrow">LOOK CLOSER</p><h3>Districts, in context.</h3></div><label>Find a district or province<input type="search" value={query} placeholder="Try Kathmandu or Koshi" onChange={e=>{setQuery(e.target.value);setPage(0)}} /></label></div>
            <div className="demo-table-scroll"><table><caption>Districts ordered by {METRICS[metric].label.toLowerCase()} · {selectedScheme.name}</caption><thead><tr><th scope="col">District</th><th scope="col">Province</th><th scope="col">{METRICS[metric].short}</th><th scope="col">Land coverage</th><th scope="col">Inspect</th></tr></thead><tbody>{ranked.slice(page*10,page*10+10).map(d=><tr key={d.code} className={d.code===selected?'is-selected':''}><th scope="row">{d.name}</th><td>{d.province}</td><td>{displayValue(metricValue(d.values[scheme],metric),metric)}</td><td>{ratio(d.values[scheme].areaValid,d.values[scheme].areaAll).toFixed(1)}%</td><td><button onClick={()=>{choose(d.code);document.getElementById('explorer')?.scrollIntoView({behavior:'smooth'})}} aria-label={`Inspect ${d.name}`}>View ↗</button></td></tr>)}</tbody></table>{!ranked.length&&<p role="status" className="demo-no-results">No districts match “{query}”. Try a different name or province.</p>}</div>
            <div className="demo-pagination"><span>{ranked.length?`${page*10+1}–${Math.min(page*10+10,ranked.length)} of ${ranked.length} districts`:'0 districts'}</span><div><button disabled={page===0} onClick={()=>setPage(n=>n-1)}>Previous</button><button disabled={(page+1)*10>=ranked.length} onClick={()=>setPage(n=>n+1)}>Next</button></div></div>
          </section>
        </section>

        <section id="research" className="demo-research"><div className="demo-container demo-section"><div className="demo-section-heading"><div><p className="demo-eyebrow">02 / BEHIND THE MAP</p><h2>The result is only the beginning.</h2></div><p>Explore original figures from the research pipeline.</p></div>
          <div className="demo-figure-tabs" aria-label="Research figure">{data.artifacts.map(f=><button key={f.id} aria-pressed={figure===f.id} onClick={()=>setFigure(f.id)}>{f.category}</button>)}</div>
          <figure className="demo-figure"><div className="demo-figure-title"><div><h3>{selectedFigure.title}</h3><p>{selectedFigure.description}</p></div><a href={asset(selectedFigure.file)} download>Download figure ↓</a></div><a href={asset(selectedFigure.file)} target="_blank" rel="noreferrer" aria-label={`Open full-size figure: ${selectedFigure.title}`}><img key={selectedFigure.file} src={asset(selectedFigure.file)} alt={selectedFigure.description} loading="eager" /></a><figcaption>Precomputed project output · {selectedFigure.file}. Open the figure for a full-size view. No calculation is performed when switching figures.</figcaption></figure>
        </div></section>

        <section id="about" className="demo-container demo-section"><p className="demo-eyebrow">03 / KNOW WHAT YOU’RE LOOKING AT</p><h2>Useful comparisons.<br />Honest boundaries.</h2><div className="demo-about-grid"><article><span>01</span><h3>A research snapshot</h3><p>This site explores saved results across five weighting schemes. It cannot draw a new study area, accept uploads, recalculate weights, assess your location, or run Citizen/NBS tools.</p></article><article><span>02</span><h3>Exposure, not a prediction</h3><p>The raster can use national breaks or basin-relative quintiles; the district view shows aggregate exposure. The district card always reports district totals, not values at the clicked pixel. A high value is not a current flood alert, a probability, or an instruction to evacuate.</p></article><article><span>03</span><h3>Methods matter</h3><p>These research outputs use national breaks and census-calibrated population. They are distinct from the interactive application’s raw-HRSL reports. Read the source tables and methodology before using the values.</p></article></div>
          <details className="demo-provenance"><summary>Sources, attribution & reproducibility</summary><div><p><strong>Boundaries:</strong> {data.boundaryAttribution.source}. <a href={data.boundaryAttribution.url} target="_blank" rel="noreferrer">OCHA HDX source</a> · {data.boundaryAttribution.license}. {data.boundaryAttribution.changes}</p><p><strong>Research inputs:</strong> the project’s Copernicus DEM, WorldCover, OSM, HRSL and other configured sources. Source choices, calibration and limitations are documented in the repository. Figures are original project outputs, unchanged.</p><p>No raw flood incident records, uploaded user files or individual shelter coordinates are included in this demo.</p><div className="demo-source-links"><a href={asset('snapshot.json')} download>Snapshot & source fingerprints ↓</a><a href={asset('README.txt')} download>Attribution notes ↓</a><a href={asset('methods.txt')} target="_blank" rel="noreferrer">Method notes ↗</a></div></div></details>
        </section>
      </>}
    </main>
    <footer className="demo-footer demo-container"><a className="demo-brand" href="#top">खोला <span className="demo-brand-en">Khola</span></a><p>Made to make the assumptions visible.</p><a href={REPOSITORY} target="_blank" rel="noreferrer">FloodHUBnepal on GitHub ↗</a></footer>
  </div>
}
