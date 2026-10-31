export const METRICS = {
  population: { label: 'Residents in classes 4–5', short: 'Estimated residents', breaks: [100000, 250000, 500000, 1000000], suffix: 'residents' },
  populationShare: { label: 'Share of mapped population', short: 'Mapped population share', breaks: [20, 40, 60, 80], suffix: '%' },
  areaShare: { label: 'Share of mapped land area', short: 'Mapped area share', breaks: [10, 25, 50, 75], suffix: '%' },
  buildings: { label: 'Buildings in classes 4–5', short: 'Buildings', breaks: [10000, 50000, 100000, 200000], suffix: 'buildings' },
}
export const COLORS = ['#d5e7e2', '#a3c9c1', '#6aa89b', '#357e71', '#175448']
export const number = value => Number.isFinite(value) ? new Intl.NumberFormat('en', { maximumFractionDigits: 0 }).format(value) : 'Not available'
export const compact = value => Number.isFinite(value) ? new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 2 }).format(value) : 'Not available'
export function ratio(numerator, denominator) { return denominator > 0 ? numerator / denominator * 100 : null }
export function metricValue(values, metric) {
  if (!values) return null
  if (metric === 'population') return values.populationHigh
  if (metric === 'buildings') return values.buildingsHigh
  if (metric === 'populationShare') return ratio(values.populationHigh, values.populationValid)
  if (metric === 'areaShare') return ratio(values.areaHigh, values.areaValid)
  throw new Error('Unknown map metric')
}
export function colorFor(value, metric) { return value == null ? '#e7e5e0' : COLORS[METRICS[metric].breaks.filter(b => value >= b).length] }
export function displayValue(value, metric, abbreviated = false) {
  if (value == null) return 'Not available'
  return METRICS[metric].suffix === '%' ? `${value.toFixed(1)}%` : (abbreviated ? compact(value) : number(value))
}
export function rankedDistricts(districts, scheme, metric, query = '') {
  const search = query.trim().toLowerCase()
  return districts.filter(d => `${d.name} ${d.province} ${d.code}`.toLowerCase().includes(search))
    .sort((a, b) => (metricValue(b.values[scheme], metric) ?? -Infinity) - (metricValue(a.values[scheme], metric) ?? -Infinity) || a.name.localeCompare(b.name))
}
export function validateSnapshot(data) {
  if (data?.schemaVersion !== 1 || !Array.isArray(data.districts) || data.districts.length !== 77 || !Array.isArray(data.schemes) || data.schemes.length !== 5 || !Array.isArray(data.artifacts)) throw new Error('This research snapshot has an unsupported format. Please reload or contact the project maintainer.')
  if (new Set(data.districts.map(d => d.code)).size !== 77) throw new Error('Duplicate district identifiers in snapshot.')
  for (const scheme of data.schemes) {
    if (!data.national?.[scheme.id]) throw new Error('Missing national summary.')
    for (const district of data.districts) {
      if (!district.geometry || !district.values[scheme.id] || !Object.values(district.values[scheme.id]).every(v => typeof v === 'number' && Number.isFinite(v) && v >= 0)) throw new Error('Incomplete district results in snapshot.')
    }
  }
  return data
}
export function mapPaths(districts) {
  const polygons = d => d.geometry.type === 'Polygon' ? [d.geometry.coordinates] : d.geometry.coordinates
  const points = districts.flatMap(d => polygons(d).flat(2))
  const xs = points.map(p => p[0] * Math.cos(28 * Math.PI / 180)), ys = points.map(p => -p[1])
  // Iteration avoids spread/argument limits when a snapshot contains many vertices.
  const minX = xs.reduce((a,b) => Math.min(a,b), Infinity), maxX = xs.reduce((a,b) => Math.max(a,b), -Infinity)
  const minY = ys.reduce((a,b) => Math.min(a,b), Infinity), maxY = ys.reduce((a,b) => Math.max(a,b), -Infinity)
  const scale = Math.min(940 / (maxX-minX), 490 / (maxY-minY))
  const offsetX = (1000-(maxX-minX)*scale)/2, offsetY = (550-(maxY-minY)*scale)/2
  const point = ([lon, lat]) => `${(offsetX+(lon*Math.cos(28*Math.PI/180)-minX)*scale).toFixed(2)},${(offsetY+(-lat-minY)*scale).toFixed(2)}`
  return districts.map(d => ({ code: d.code, path: polygons(d).map(polygon => polygon.map(ring => `M${ring.map(point).join('L')}Z`).join('')).join('') }))
}
