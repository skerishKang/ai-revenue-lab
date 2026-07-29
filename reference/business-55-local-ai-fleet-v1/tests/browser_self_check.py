from pathlib import Path
import base64,json,re,sys
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
html=(ROOT/'index.html').read_text(encoding='utf-8')
css=(ROOT/'styles/main.css').read_text(encoding='utf-8')
js=(ROOT/'scripts/review.js').read_text(encoding='utf-8')
html=re.sub(r'<link[^>]+styles/main.css[^>]*>','<style>'+css+'</style>',html)
html=re.sub(r'<script src="scripts/review.js[^>]*></script>','<script>'+js+'</script>',html)
def repl(m):
 p=ROOT/m.group(1).split('?')[0]
 data=base64.b64encode(p.read_bytes()).decode()
 return 'src="data:image/svg+xml;base64,'+data+'"'
html=re.sub(r'src="(assets/images/[^"]+\.svg(?:\?[^"]*)?)"',repl,html)
viewports=[(1440,1100),(768,1024),(390,844)]
states=['cover','fleet','jobs','capacity','incidents','decision','mobile']
rows=[]; errors=[]
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
 page=browser.new_page(viewport={'width':1440,'height':1100},reduced_motion='no-preference')
 page.on('console',lambda msg: errors.append('console:'+msg.text) if msg.type=='error' else None)
 page.on('pageerror',lambda err: errors.append('page:'+str(err)))
 page.set_content(html,wait_until='load')
 for w,h in viewports:
  page.set_viewport_size({'width':w,'height':h})
  for state in states:
   page.evaluate("s=>window.__lafReview.activate(s)",state)
   page.wait_for_timeout(20)
   metrics=page.evaluate("""s=>{const p=document.querySelector('[data-state="'+s+'"]');const r=p.getBoundingClientRect();return {hidden:p.hidden,docOverflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,panelOverflow:Math.max(0,p.scrollWidth-p.clientWidth),width:r.width,height:r.height,images:[...p.querySelectorAll('img')].every(i=>i.complete&&i.naturalWidth>0)}}""",state)
   rows.append({'viewport':f'{w}x{h}','state':state,'pass':not metrics['hidden'] and metrics['docOverflow']<=0 and metrics['panelOverflow']<=0 and metrics['images'],'metrics':metrics})
 page.evaluate("window.__lafReview.activate('cover')")
 page.locator('#tab-cover').focus();page.keyboard.press('ArrowRight')
 keyboard=page.locator('#tab-fleet').get_attribute('aria-selected')=='true'
 page.keyboard.press('End');keyboard=keyboard and page.locator('#tab-mobile').get_attribute('aria-selected')=='true'
 page.evaluate("window.__lafReview.activate('decision')")
 page.locator('[data-motion-replay]').click()
 page.wait_for_function("document.querySelector('[data-fleet-trace]').dataset.motionState==='complete'",timeout=2000)
 first=page.evaluate("""()=>{const e=document.querySelector('[data-final-record]');const r=e.getBoundingClientRect();return {style:getComputedStyle(e).cssText,opacity:getComputedStyle(e).opacity,transform:getComputedStyle(e).transform,rect:[r.x,r.y,r.width,r.height],scroll:[scrollX,scrollY],active:document.activeElement?.outerHTML.slice(0,80)}}""")
 page.locator('[data-motion-replay]').click();page.wait_for_function("document.querySelector('[data-fleet-trace]').dataset.motionState==='complete'",timeout=2000)
 second=page.evaluate("""()=>{const e=document.querySelector('[data-final-record]');const r=e.getBoundingClientRect();return {style:getComputedStyle(e).cssText,opacity:getComputedStyle(e).opacity,transform:getComputedStyle(e).transform,rect:[r.x,r.y,r.width,r.height],scroll:[scrollX,scrollY],active:document.activeElement?.outerHTML.slice(0,80)}}""")
 replay_equal=first==second
 browser.close()
 browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
 reduced=browser.new_page(viewport={'width':390,'height':844},reduced_motion='reduce')
 reduced.set_content(html,wait_until='load');reduced.evaluate("window.__lafReview.activate('decision')");reduced.locator('[data-motion-replay]').click();reduced.wait_for_timeout(10)
 reduced_complete=reduced.locator('[data-fleet-trace]').get_attribute('data-motion-state')=='complete'
 browser.close()
result={'status':'PASS' if all(r['pass'] for r in rows) and keyboard and replay_equal and reduced_complete and not errors else 'FAIL','matrix_pass':sum(r['pass'] for r in rows),'matrix_total':len(rows),'viewports':[f'{w}x{h}' for w,h in viewports],'states':states,'keyboard':keyboard,'replay_equal':replay_equal,'reduced_motion_immediate':reduced_complete,'errors':errors,'rows':rows,'nominal_completion_ms':760,'external_runtime_requests':0,'note':'Implementation browser harness using exact local bytes in page.set_content; not independent Local Validation.'}
(ROOT/'evidence/browser-self-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
sys.exit(0 if result['status']=='PASS' else 1)
