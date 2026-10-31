// Deliberate allowlist: aggregate research outputs and district outlines only.
// Run locally when refreshing the snapshot; CI builds from committed exports.
import { readFileSync, writeFileSync, mkdirSync, copyFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { resolve } from 'node:path'
import { createHash } from 'node:crypto'
import { parseShp, parseDbf, combine } from 'shpjs'

const root = fileURLToPath(new URL('../../', import.meta.url))
const output = resolve(root, 'pages-demo/public/demo')
mkdirSync(output, { recursive: true })

function csv(text) {
  const rows = []; let row = [], field = '', quoted = false
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (c === '"') { if (quoted && text[i + 1] === '"') { field += '"'; i++ } else quoted = !quoted }
    else if (c === ',' && !quoted) { row.push(field); field = '' }
    else if (c === '\n' && !quoted) { row.push(field.replace(/\r$/, '')); if (row.some(Boolean)) rows.push(row); row = []; field = '' }
    else field += c
  }
  if (field || row.length) { row.push(field.replace(/\r$/, '')); rows.push(row) }
  const headers = rows.shift()
  return rows.map(values => Object.fromEntries(headers.map((key, i) => [key, values[i]])))
}
const source = path => readFileSync(resolve(root, path))
const rows = csv(source('results/rq3_exposure_by_district.csv').toString())
const totals = csv(source('results/rq3_national_totals.csv').toString())
const schemes = [
  { id: 'expert_median', name: 'Expert median', detail: 'Median published expert weights across included sets.' },
  { id: 'expert_median_nepal', name: 'Expert median · Nepal', detail: 'Median weights from the Nepal-only subset.' },
  { id: 'equal8', name: 'Equal weights', detail: 'Equal weights across the eight research criteria.' },
  { id: 'fitted_cluster', name: 'Fitted · clusters', detail: 'Research-fitted cluster-weight reference; not a live forecast.' },
  { id: 'fitted_full', name: 'Fitted · full', detail: 'Research-fitted full-weight reference; not a live forecast.' },
]
const fields = {
  populationHigh: 'population_cal_high', populationValid: 'population_cal_valid_total', populationAll: 'population_cal_all_total',
  areaHigh: 'area_m2_high', areaValid: 'area_m2_valid_total', areaAll: 'area_m2_all_total',
  buildingsHigh: 'buildings_high', buildingsValid: 'buildings_valid_total',
}
function metrics(row, national = false) {
  const result = {}
  for (const [key, column] of Object.entries(fields)) {
    if (national && (key === 'populationAll' || key === 'areaAll')) continue
    const value = Number(row[column])
    if (!Number.isFinite(value) || value < 0) throw new Error(`Invalid ${column} for ${row.pcode || row.scheme}`)
    result[key] = Math.round(value * 100) / 100
  }
  return result
}
function segmentDistance(p, a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1]
  const t = dx || dy ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy))) : 0
  return (p[0] - a[0] - t * dx) ** 2 + (p[1] - a[1] - t * dy) ** 2
}
function simplifyRing(points) {
  const keep = new Set([0, points.length - 1]), stack = [[0, points.length - 1]]
  while (stack.length) {
    const [a, b] = stack.pop(); let greatest = .002 ** 2, index = -1
    for (let i = a + 1; i < b; i++) { const d = segmentDistance(points[i], points[a], points[b]); if (d > greatest) { greatest = d; index = i } }
    if (index >= 0) { keep.add(index); stack.push([a, index], [index, b]) }
  }
  const selected = [...keep].sort((a, b) => a - b).map(i => points[i])
  return (selected.length >= 4 ? selected : points).map(([x, y]) => [Number(x.toFixed(4)), Number(y.toFixed(4))])
}
const shape = 'backend/data/raw/basins/npl_admin_boundaries.shp/npl_admin2'
const features = combine([parseShp(source(`${shape}.shp`), source(`${shape}.prj`).toString()), parseDbf(source(`${shape}.dbf`))]).features
const districts = features.map(feature => {
  const code = feature.properties.adm2_pcode
  const values = Object.fromEntries(schemes.map(scheme => {
    const matches = rows.filter(row => row.pcode === code && row.scheme === scheme.id && row.breaks === 'national' && row.definition === 'class45')
    if (matches.length !== 1) throw new Error(`Expected one district row: ${code}/${scheme.id}`)
    return [scheme.id, metrics(matches[0])]
  }))
  const { type, coordinates } = feature.geometry
  if (!['Polygon', 'MultiPolygon'].includes(type)) throw new Error(`Unexpected geometry ${type}`)
  return { code, name: feature.properties.adm2_name, province: feature.properties.adm1_name,
    geometry: { type, coordinates: type === 'Polygon' ? coordinates.map(simplifyRing) : coordinates.map(polygon => polygon.map(simplifyRing)) }, values }
})
if (districts.length !== 77 || new Set(districts.map(d => d.code)).size !== 77) throw new Error('Expected 77 unique districts')
const national = Object.fromEntries(schemes.map(scheme => {
  const matches = totals.filter(row => row.scheme === scheme.id && row.breaks === 'national' && row.definition === 'class45')
  if (matches.length !== 1) throw new Error(`Expected one national total for ${scheme.id}`)
  return [scheme.id, metrics(matches[0], true)]
}))
const artifacts = [
  { id: 'exposure', file: 'fig6_exposure.png', title: 'Exposure across Nepal', category: 'Map', description: 'District-level population in susceptibility classes 4–5 and agreement between district rankings.' },
  { id: 'validation', file: 'fig2_heldout_auc.png', title: 'Held-out performance', category: 'Validation', description: 'Precomputed held-out discrimination results. Study-specific evidence, not a live evaluation.' },
  { id: 'equivalence', file: 'fig3_equivalence.png', title: 'Do the weights change the result?', category: 'Weights', description: 'Research comparisons of equal and published expert weighting schemes.' },
  { id: 'shelters', file: 'fig7_shelters.png', title: 'How stable are candidate lists?', category: 'Shelters', description: 'Overlap between ranked Kathmandu candidate-site lists. This is a sensitivity result, not a map of approved shelters.' },
]
for (const artifact of artifacts) copyFileSync(resolve(root, 'figures', artifact.file), resolve(output, artifact.file))
const provenancePaths = ['results/rq3_exposure_by_district.csv', 'results/rq3_national_totals.csv', 'results/rq3_coverage_note.csv', ...artifacts.map(a => `figures/${a.file}`), `${shape}.shp`, `${shape}.dbf`, `${shape}.prj`]
const snapshot = {
  schemaVersion: 1, snapshotDate: '2026-10-31', schemes, national, districts, artifacts,
  method: 'Research snapshot: national reclassification breaks, classes 4–5, census-calibrated population. Not the interactive application’s raw-HRSL output.',
  coverage: 'One research unit was missing (133.758 km² inside Nepal, as recorded in rq3_coverage_note.csv). Coverage varies by district. Missing cells are not evidence of low susceptibility.',
  boundaryAttribution: { title: 'Nepal — Subnational Administrative Boundaries', source: 'Survey Department of Nepal; UN Resident Coordinator’s Office in Nepal; distributed via OCHA HDX', url: 'https://data.humdata.org/dataset/cod-ab-npl', license: 'CC BY-IGO', changes: 'District outlines simplified (~0.002° tolerance) and coordinates rounded for an overview map. Not for measurement or legal boundaries.' },
  provenance: provenancePaths.map(path => ({ path, sha256: createHash('sha256').update(source(path)).digest('hex') })),
}
try { snapshot.hazard = JSON.parse(source('pages-demo/public/demo/hazard/manifest.json')) } catch (error) { if (error.code !== 'ENOENT') throw error }
writeFileSync(resolve(output, 'snapshot.json'), JSON.stringify(snapshot))
const columns = ['scheme','district_code','district','province', ...Object.keys(fields)]
const quote = value => `"${String(value).replaceAll('"','""')}"`
const exported = districts.flatMap(d => schemes.map(s => [s.id,d.code,d.name,d.province,...Object.keys(fields).map(k => d.values[s.id][k])]))
writeFileSync(resolve(output, 'district-exposure.csv'), [columns,...exported].map(row => row.map(quote).join(',')).join('\r\n'))
writeFileSync(resolve(output, 'README.txt'), `Khola static demo, snapshot ${snapshot.snapshotDate}.\n${snapshot.method}\n${snapshot.coverage}\nBoundary attribution: ${snapshot.boundaryAttribution.source}. ${snapshot.boundaryAttribution.url}\nLicense: ${snapshot.boundaryAttribution.license}. ${snapshot.boundaryAttribution.changes}\nResearch figures: original project outputs, used without modifying their content. No raw incident records or shelter coordinates are included.\nSource fingerprints are recorded in snapshot.json. Regenerate with npm run demo:export from a local checkout with the documented inputs.\n`)
console.log(`Exported ${districts.length} districts, ${schemes.length} schemes, ${artifacts.length} figures.`)
