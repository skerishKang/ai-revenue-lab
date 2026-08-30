from pathlib import Path
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import base64, json
ROOT=Path(__file__).resolve().parents[1]
STATES=['cover','requirement','patch','tests','validation','package','mobile']
VIEWS=[('desktop',1440,1100),('tablet',768,1024),('mobile',390,844)]
failures=[]; errors=[]; external=[]; requests=[]

def inline_document():
    soup=BeautifulSoup((ROOT/'index.html').read_text(encoding='utf-8'),'html.parser')
    link=soup.find('link',rel='stylesheet')
    style=soup.new_tag('style')
    style.string=(ROOT/'styles/main.css').read_text(encoding='utf-8')
    link.replace_with(style)
    for img in soup.find_all('img',src=True):
        rel=img['src'].split('?')[0]
        raw=(ROOT/rel).read_bytes()
        img['src']='data:image/svg+xml;base64,'+base64.b64encode(raw).decode('ascii')
    ext=soup.find('script',src=True)
    script=soup.new_tag('script')
    script.string=(ROOT/'scripts/review.js').read_text(encoding='utf-8')
    ext.replace_with(script)
    return '<!doctype html>\n'+str(soup)
DOC=inline_document()

def overlap(rects):
    for i,a in enumerate(rects):
        if a['width']<=0 or a['height']<=0: continue
        for b in rects[i+1:]:
            if b['width']<=0 or b['height']<=0: continue
            x=max(0,min(a['x']+a['width'],b['x']+b['width'])-max(a['x'],b['x']))
            y=max(0,min(a['y']+a['height'],b['y']+b['height'])-max(a['y'],b['y']))
            if x*y>24: return True
    return False

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
    for name,w,h in VIEWS:
      page=browser.new_page(viewport={'width':w,'height':h},reduced_motion='no-preference')
      page.on('console',lambda m: errors.append(f'console:{m.type}:{m.text}') if m.type=='error' else None)
      page.on('pageerror',lambda e: errors.append(f'page:{e}'))
      page.on('request',lambda r: (requests.append(r.url), external.append(r.url) if not (r.url.startswith('data:') or r.url.startswith('about:')) else None))
      page.set_content(DOC,wait_until='load')
      for state in STATES:
        page.click(f'[data-state-control="{state}"]')
        visible=page.locator('[data-state]:visible').count()
        if visible!=1: failures.append(f'{name}:{state}:visible={visible}')
        selected=page.locator('[data-state-control][aria-selected="true"]').count()
        if selected!=1: failures.append(f'{name}:{state}:selected={selected}')
        tabindex=page.locator('[data-state-control][tabindex="0"]').count()
        if tabindex!=1: failures.append(f'{name}:{state}:tabindex0={tabindex}')
        overflow=page.evaluate('document.documentElement.scrollWidth-document.documentElement.clientWidth')
        if overflow>0: failures.append(f'{name}:{state}:overflow={overflow}')
        bad=page.evaluate("""() => [...document.querySelectorAll('[data-state]:not([hidden]) img')].filter(i => !i.complete || i.naturalWidth===0).length""")
        if bad: failures.append(f'{name}:{state}:broken={bad}')
        clipped=page.evaluate("""() => [...document.querySelectorAll('[data-state]:not([hidden]) *')].filter(e=>{const s=getComputedStyle(e); if(s.display==='none'||s.visibility==='hidden')return false; const r=e.getBoundingClientRect(); return r.right>innerWidth+1||r.left<-1}).length""")
        if clipped: failures.append(f'{name}:{state}:clipped={clipped}')
        rects=page.eval_on_selector_all('[data-state]:not([hidden]) .authority, [data-state]:not([hidden]) .persistent-boundaries span','els=>els.map(e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}})')
        if overlap(rects): failures.append(f'{name}:{state}:label-overlap')
      if name=='mobile':
        page.click('[data-state-control="mobile"]')
        required=['REQUIREMENT','CHANGED FILE MANIFEST','TEST STATUS','FAILED CHECK retained → RERUN RESULT PASS','INDEPENDENT VALIDATION','EXACT HEAD VERIFIED','NOT MERGED','DEPLOYMENT READINESS — NOT DEPLOYED','NEXT HUMAN ACTION']
        for label in required:
          loc=page.locator('.phone-brief').get_by_text(label,exact=True)
          if loc.count()!=1: failures.append(f'mobile:first-viewport-missing:{label}')
          else:
            box=loc.bounding_box()
            if not box or box['y']+box['height']>h: failures.append(f'mobile:first-viewport-below:{label}:{box}')
      page.click('[data-state-control="cover"]'); page.keyboard.press('ArrowRight')
      if page.locator('[data-state-control="requirement"]:focus').count()!=1: failures.append(f'{name}:keyboard-nav')
      outline=page.eval_on_selector('[data-state-control="requirement"]','e=>getComputedStyle(e).outlineStyle')
      if outline=='none': failures.append(f'{name}:focus-not-visible')
      page.close()

    page=browser.new_page(viewport={'width':1440,'height':1100},reduced_motion='no-preference')
    page.set_content(DOC,wait_until='load'); page.click('[data-state-control="package"]')
    replay=page.locator('[data-motion-replay]'); replay.focus(); before=page.evaluate('({x:scrollX,y:scrollY,active:document.activeElement===document.querySelector("[data-motion-replay]")})')
    finals=[]; geoms=[]
    for _ in range(2):
      replay.click(); page.wait_for_function("document.querySelector('[data-delivery-line]').dataset.motionState==='complete'",timeout=3000)
      finals.append(page.eval_on_selector('.software-delivery-seal','e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return {opacity:s.opacity,transform:s.transform,w:Math.round(r.width),h:Math.round(r.height)}}'))
      geoms.append(page.eval_on_selector('[data-delivery-line]','e=>{const r=e.getBoundingClientRect();return {w:Math.round(r.width),h:Math.round(r.height)}}'))
    after=page.evaluate('({x:scrollX,y:scrollY,active:document.activeElement===document.querySelector("[data-motion-replay]")})')
    if finals[0]!=finals[1]: failures.append('motion:replay-style')
    if geoms[0]!=geoms[1]: failures.append('motion:geometry')
    if before!=after: failures.append(f'motion:focus-scroll:{before}!={after}')
    persistent=page.locator('.persistent-boundaries span:visible').all_text_contents()
    for label in ['FAILED CHECK','UNRESOLVED CONDITION','NOT MERGED','DEPLOYMENT READINESS — NOT DEPLOYED','HUMAN REVIEW REQUIRED']:
      if label not in persistent: failures.append(f'motion:persistent:{label}')
    page.close()

    page=browser.new_page(viewport={'width':1440,'height':1100},reduced_motion='no-preference')
    page.set_content(DOC,wait_until='load'); page.click('[data-state-control="package"]'); page.click('[data-motion-replay]')
    running=page.eval_on_selector('.software-delivery-seal','e=>{const s=getComputedStyle(e);return {delay:s.animationDelay,duration:s.animationDuration,name:s.animationName}}')
    def ms(v): return float(v.replace('ms','')) if 'ms' in v else float(v.replace('s',''))*1000
    computed=ms(running['delay'])+ms(running['duration'])
    if running['name']!='deliveryPackageComplete': failures.append(f'motion:name:{running}')
    if not 700<=computed<=800: failures.append(f'motion:timing:{computed}')
    page.wait_for_function("document.querySelector('[data-delivery-line]').dataset.motionState==='complete'",timeout=3000)
    page.close()

    page=browser.new_page(viewport={'width':1440,'height':1100},reduced_motion='reduce')
    page.set_content(DOC,wait_until='load'); page.click('[data-state-control="package"]'); page.click('[data-motion-replay]')
    if page.get_attribute('[data-delivery-line]','data-motion-state')!='complete': failures.append('reduced-motion:not-complete')
    if page.locator('.software-delivery-seal:visible').count()!=1: failures.append('reduced-motion:seal-hidden')
    page.close(); browser.close()

result={'status':'PASS' if not failures and not errors and not external else 'FAIL','combinations':21,'failures':failures,'errors':errors,'external_runtime_requests':len(external),'request_count':len(requests),'keyboard_navigation':not any('keyboard-nav' in x for x in failures),'motion':{'computed_end_ms':computed,'animation_name':running['name'],'replay_equal':finals[0]==finals[1],'focus_stable':before['active'] and after['active'],'scroll_stable':before['x']==after['x'] and before['y']==after['y'],'geometry_stable':geoms[0]==geoms[1],'finals':finals},'reduced_motion':not any('reduced-motion' in x for x in failures),'harness':'inline exact local HTML/CSS/JS/SVG bytes; no network'}
(ROOT/'evidence/browser-self-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
raise SystemExit(1 if result['status']!='PASS' else 0)
