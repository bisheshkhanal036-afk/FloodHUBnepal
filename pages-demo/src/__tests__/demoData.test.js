import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { colorFor, displayValue, mapPaths, metricValue, rankedDistricts, ratio, validateSnapshot } from '../demoData'
const data = JSON.parse(readFileSync('public/demo/snapshot.json', 'utf8'))
describe('committed research snapshot', () => {
  it('contains 77 unique districts and five complete schemes', () => { expect(validateSnapshot(data)).toBe(data); expect(data.schemes).toHaveLength(5) })
  it('keeps district population totals consistent with the national research output', () => {
    for (const scheme of data.schemes) {
      const sum = data.districts.reduce((n,d) => n+d.values[scheme.id].populationHigh,0)
      expect(Math.abs(sum-data.national[scheme.id].populationHigh)).toBeLessThan(1)
    }
  })
  it('does not mark missing coverage as zero risk', () => { expect(ratio(0,0)).toBeNull(); expect(metricValue({ areaHigh:0,areaValid:0 },'areaShare')).toBeNull(); expect(displayValue(null,'areaShare')).toBe('Not available') })
  it('uses the requested scheme and metric for rankings', () => {
    for (const metric of ['population','populationShare','areaShare','buildings']) {
      const rows=rankedDistricts(data.districts,'equal8',metric)
      expect(metricValue(rows[0].values.equal8,metric)).toBeGreaterThanOrEqual(metricValue(rows[1].values.equal8,metric))
    }
  })
  it('filters district names, provinces and district codes without case sensitivity', () => { expect(rankedDistricts(data.districts,'expert_median','population','kAtHmAnDu')[0].code).toBe('NP0327'); expect(rankedDistricts(data.districts,'equal8','population','no-match')).toEqual([]) })
  it('produces one finite SVG district path per district', () => { const paths=mapPaths(data.districts);expect(paths).toHaveLength(77);for(const p of paths){expect(p.path).toMatch(/^M/);expect(p.path).not.toMatch(/NaN|Infinity/)} })
  it('rejects an incomplete snapshot rather than inventing result values', () => { expect(()=>validateSnapshot({...data,districts:[]})).toThrow();const invalid=structuredClone(data);delete invalid.districts[0].values.equal8;expect(()=>validateSnapshot(invalid)).toThrow() })
  it('colors exact bin boundaries consistently', () => { expect(colorFor(99999,'population')).not.toBe(colorFor(100000,'population'));expect(displayValue(33.333,'areaShare')).toBe('33.3%') })
})
