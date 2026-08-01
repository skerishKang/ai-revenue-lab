from pathlib import Path
from playwright.sync_api import sync_playwright
import json, re
ROOT=Path(__file__).resolve().parents[1]
import base64
html_source=(ROOT/'index.html').read_text(encoding='utf-8')
css=(ROOT/'styles/main.css').read_text(encoding='utf-8')
js=(ROOT/'scripts/review.js').read_text(encoding='utf-8')
html_source=html_source.replace('<link rel="stylesheet" href="styles/main.css">',f'<style>{css}</style>')
html_source=html_source.replace('<script src="scripts/review.js"></script>',f'<script>{js}</script>')
for asset in (ROOT/'assets/images').glob('*.svg'):
 data=base64.b64encode(asset.read_bytes()).decode('ascii')
 html_source=html_source.replace(f'assets/images/{asset.name}',f'data:image/svg+xml;base64,{data}')
states=['cover','procedure','citizen','staff','evidence','improvement','mobile']
viewports=[(1440,1100),(768,1024),(390,844)]
rows=[]
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
 for width,height in viewports:
  page=browser.new_page(viewport={'width':width,'height':height})
  console=[]; errors=[]; failed=[]; external=[]
  page.on('console',lambda m: console.append(m.text) if m.type=='error' else None)
  page.on('pageerror',lambda e: errors.append(str(e)))
  page.on('requestfailed',lambda r: failed.append(r.url))
  page.on('request',lambda r: external.append(r.url) if r.url.startswith(('http://','https://')) else None)
  page.set_content(html_source,wait_until='load')
  for key in states:
   page.locator(f'[data-state-control="{key}"]').click()
   page.wait_for_timeout(20)
   visible=page.locator('[data-state]:visible').count()
   selected=page.locator('[data-state-control][aria-selected="true"]').get_attribute('data-state-control')
   overflow=page.evaluate('document.documentElement.scrollWidth-document.documentElement.clientWidth')
   broken=page.evaluate("[...document.images].filter(i=>!i.complete||i.naturalWidth===0).length")
   labels_ok=page.evaluate("[...document.querySelectorAll('[data-state]:not([hidden]) .record-label')].every(e=>e.getBoundingClientRect().width>0&&e.getBoundingClientRect().right<=document.documentElement.clientWidth+1)")
   rows.append({'viewport':[width,height],'state':key,'visible':visible,'selected':selected,'overflow':overflow,'broken':broken,'labels_ok':labels_ok})
  page.locator('[data-state-control="cover"]').focus(); page.keyboard.press('ArrowRight')
  assert page.locator('[data-state-control="procedure"]').get_attribute('aria-selected')=='true'
  assert console==[] and errors==[] and failed==[] and external==[], {'console':console,'errors':errors,'failed':failed,'external':external}
  page.close()
 assert all(r['visible']==1 and r['selected']==r['state'] and r['overflow']==0 and r['broken']==0 and r['labels_ok'] for r in rows),rows
 page=browser.new_page(viewport={'width':1440,'height':1100})
 page.set_content(html_source,wait_until='load'); page.locator('[data-state-control="improvement"]').click(); page.locator('[data-motion-replay]').focus(); page.evaluate('window.scrollTo(0,120)')
 before=page.evaluate("({focus:document.activeElement.hasAttribute('data-motion-replay'),scroll:scrollY,rect:(()=>{const r=document.querySelector('[data-experience-trace]').getBoundingClientRect();return [r.x,r.y,r.width,r.height]})()})")
 seal=page.locator('.follow-up-seal')
 finals=[]
 timing=None
 for i in range(2):
  page.locator('[data-motion-replay]').click()
  if i==0:
   timing=page.evaluate("(()=>{const s=getComputedStyle(document.querySelector('.follow-up-seal'));const ms=v=>v.endsWith('ms')?parseFloat(v):parseFloat(v)*1000;return {delay:ms(s.animationDelay),duration:ms(s.animationDuration)}})()")
  page.wait_for_function("document.querySelector('[data-experience-trace]').dataset.motionState==='complete'")
  finals.append(page.evaluate("(()=>{const b=document.querySelector('[data-experience-trace]');const s=getComputedStyle(document.querySelector('.follow-up-seal'));return {state:b.dataset.motionState,opacity:s.opacity,transform:s.transform,visible:[...b.querySelectorAll('.citizen-step,.staff-step,.uncertainty-step')].every(e=>getComputedStyle(e).opacity==='1')}})()"))
 after=page.evaluate("({focus:document.activeElement.hasAttribute('data-motion-replay'),scroll:scrollY,rect:(()=>{const r=document.querySelector('[data-experience-trace]').getBoundingClientRect();return [r.x,r.y,r.width,r.height]})()})")
 assert finals[0]==finals[1] and finals[0]['state']=='complete' and finals[0]['visible']
 assert before['focus'] and after['focus'] and before['scroll']==after['scroll'] and before['rect']==after['rect']
 end=timing['delay']+timing['duration']; assert 700<=end<=800,end
 page.close()
 page=browser.new_page(viewport={'width':390,'height':844},reduced_motion='reduce')
 page.set_content(html_source,wait_until='load'); page.locator('[data-state-control="improvement"]').click(); page.locator('[data-motion-replay]').click()
 reduced=page.evaluate("({state:document.querySelector('[data-experience-trace]').dataset.motionState,all:[...document.querySelectorAll('[data-experience-trace] .trace-layer,[data-experience-trace] .follow-up-seal')].every(e=>getComputedStyle(e).opacity==='1')})")
 assert reduced=={'state':'complete','all':True},reduced
 page.close(); browser.close()
result={'status':'PASS','matrix':rows,'console_errors':0,'page_errors':0,'failed_requests':0,'external_runtime_requests':0,'motion':{'delay_ms':timing['delay'],'duration_ms':timing['duration'],'computed_end_ms':end,'replay_equal':finals[0]==finals[1],'focus_scroll_geometry_stable':before==after},'reduced_motion':reduced}
(ROOT/'evidence/browser-self-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'status':'PASS','combinations':len(rows),'computed_end_ms':end},ensure_ascii=False))
