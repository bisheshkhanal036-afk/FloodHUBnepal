import { chromium } from '@playwright/test'
import { mkdirSync } from 'node:fs'
const url=process.argv[2] || 'https://bisheshkhanal036-afk.github.io/FloodHUBnepal/'
const browser=await chromium.launch({channel:process.env.CI?undefined:'chrome',headless:true})
try {
  const page=await browser.newPage({viewport:{width:1440,height:1000}})
  const errors=[],requests=[]
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>requests.push(r.url()))
  const response=await page.goto(url,{waitUntil:'networkidle',timeout:60000})
  if(response.status()!==200)throw new Error(`Live page returned ${response.status()}`)
  await page.getByRole('heading',{name:'Kathmandu',exact:true}).waitFor()
  const before=await page.getByTestId('district-value').innerText()
  await page.getByLabel('Weighting scheme').selectOption('equal8')
  if(await page.getByTestId('district-value').innerText()===before)throw new Error('Scheme switch did not change the saved result')
  await page.getByLabel('Inspect a district').selectOption('NP0104')
  await page.getByRole('heading',{name:'Jhapa',exact:true}).waitFor()
  const dataResponse=await page.request.get(new URL('demo/snapshot.json',url).href)
  const data=await dataResponse.json()
  if(data.districts.length!==77||data.schemes.length!==5)throw new Error('Incorrect live snapshot')
  const csv=await page.request.get(new URL('demo/district-exposure.csv',url).href)
  if(csv.status()!==200||(await csv.text()).split('\n').length!==386)throw new Error('CSV download failed')
  await page.getByRole('button',{name:'Shelters',exact:true}).click()
  const figure=page.getByRole('img',{name:/Overlap between ranked Kathmandu/})
  await figure.scrollIntoViewIfNeeded()
  await page.waitForFunction(()=>{const image=document.querySelector('.demo-figure img');return image?.complete&&image.naturalWidth>0})
  if(errors.length||requests.some(r=>r.includes('/api/')||r.includes(':8000')))throw new Error(`Unexpected runtime/API errors: ${JSON.stringify(errors)}`)
  mkdirSync('test-results',{recursive:true})
  await page.evaluate(()=>window.scrollTo(0,0))
  await page.screenshot({path:'test-results/live-desktop.png',fullPage:true})
  await page.setViewportSize({width:390,height:844})
  if(!await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth))throw new Error('Mobile page overflow')
  await page.screenshot({path:'test-results/live-mobile.png',fullPage:true})
  console.log(JSON.stringify({url,status:response.status(),districts:data.districts.length,schemes:data.schemes.length,csvRows:385,figures:'loaded',runtimeErrors:errors.length,apiRequests:requests.filter(r=>r.includes('/api/')).length,mobileOverflow:false},null,2))
}finally{await browser.close()}
