from pathlib import Path
import json, subprocess, threading, http.server, socketserver, time
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
VIEWPORTS=[(1440,1100),(768,1024),(390,844)]
STATES=['cover','brief','guided-run','evidence','review','skill-card','mobile']
report={'mode':'localhost','viewports':{},'motion':{},'errors':[]}
class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*args): pass
server=socketserver.TCPServer(('127.0.0.1',0),Handler)
port=server.server_address[1]
thread=threading.Thread(target=server.serve_forever,daemon=True)
old=Path.cwd()
import os
os.chdir(ROOT); thread.start()
try:
  with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
    for width,height in VIEWPORTS:
      page=browser.new_page(viewport={'width':width,'height':height},reduced_motion='no-preference')
      logs=[]; page_errors=[]; failed=[]; external=[]
      page.on('console',lambda m: logs.append(m.text) if m.type=='error' else None)
      page.on('pageerror',lambda e: page_errors.append(str(e)))
      page.on('requestfailed',lambda r: failed.append(r.url))
      page.on('request',lambda r: external.append(r.url) if r.url.startswith(('http://','https://')) and not r.url.startswith(f'http://127.0.0.1:{port}') else None)
      try:
        page.goto(f'http://127.0.0.1:{port}/',wait_until='networkidle',timeout=15000)
      except Exception as exc:
        report['mode']='inline-exact-bytes-admin-fallback'
        report['errors'].append(str(exc))
        try: page.close()
        except Exception: pass
        page=browser.new_page(viewport={'width':width,'height':height},reduced_motion='no-preference')
        page.on('console',lambda m: logs.append(m.text) if m.type=='error' else None)
        page.on('pageerror',lambda e: page_errors.append(str(e)))
        page.on('requestfailed',lambda r: failed.append(r.url))
        page.on('request',lambda r: external.append(r.url) if r.url.startswith(('http://','https://')) and not r.url.startswith(f'http://127.0.0.1:{port}') else None)
        html=(ROOT/'index.html').read_text(encoding='utf-8')
        css=(ROOT/'styles/main.css').read_text(encoding='utf-8')
        js=(ROOT/'scripts/review.js').read_text(encoding='utf-8')
        import re, base64
        def repl(m):
          rel=m.group(1); data=(ROOT/rel).read_bytes(); return 'data:image/svg+xml;base64,'+base64.b64encode(data).decode()
        html=re.sub(r"(assets/images/[a-z0-9-]+\.svg)\?v=[^\"']+", repl, html)
        html=re.sub(r'<link[^>]+href="styles/main.css\?v=[^"]+"[^>]*>',f'<style>{css}</style>',html)
        html=re.sub(r'<script src="scripts/review.js\?v=[^"]+"></script>',f'<script>{js}</script>',html)
        page.set_content(html,wait_until='load')
      vpkey=f'{width}x{height}'; report['viewports'][vpkey]={}
      for state in STATES:
        page.click(f'#tab-{state}')
        selected=page.locator(f'#tab-{state}').get_attribute('aria-selected')=='true'
        visible=page.locator(f'#state-{state}').is_visible()
        hidden=sum(1 for s in STATES if s!=state and not page.locator(f'#state-{s}').is_visible())==6
        tabs=page.locator('[role=tab]').evaluate_all("els=>els.map(e=>({s:e.getAttribute('aria-selected'),t:e.tabIndex}))")
        roving=sum(1 for x in tabs if x['t']==0)==1 and sum(1 for x in tabs if x['s']=='true')==1
        metrics=page.evaluate("""()=>({overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth, clipped:[...document.querySelectorAll('h1,h2,h3,p,span,b,small')].filter(e=>e.scrollWidth>e.clientWidth+2 && getComputedStyle(e).whiteSpace!=='nowrap').length, overlap:[...document.querySelectorAll('.state.active *')].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&r.right>innerWidth+2}).length})""")
        imgs=page.locator(f'#state-{state} img').evaluate_all("els=>els.every(i=>i.complete&&i.naturalWidth>0)")
        report['viewports'][vpkey][state]={'selected':selected,'visible':visible,'others_hidden':hidden,'roving':roving,'overflow':metrics['overflow'],'clipping':metrics['clipped'],'overlap':metrics['overlap'],'assets_rendered':imgs}
      page.click('#tab-cover'); page.locator('#tab-cover').focus(); page.keyboard.press('ArrowRight')
      keyboard=page.evaluate("""()=>{const e=document.activeElement,s=getComputedStyle(e);return {focus:e.id,selected:e.getAttribute('aria-selected'),panel:document.querySelector('#state-brief').hidden===false,outlineWidth:s.outlineWidth,outlineStyle:s.outlineStyle}}""")
      page.click('#tab-skill-card'); page.focus('#replay-skill')
      before=page.evaluate("""()=>({scrollX,scrollY,focus:document.activeElement.id,rect:(()=>{const r=document.querySelector('#skill-motion').getBoundingClientRect();return [r.x,r.y,r.width,r.height]})()})""")
      finals=[]
      for _ in range(2):
        page.click('#replay-skill'); page.wait_for_function("document.querySelector('#skill-motion').dataset.motionState==='complete'",timeout=3000)
        finals.append(page.evaluate("""()=>{const s=getComputedStyle(document.querySelector('#verified-skill-seal'));return {opacity:s.opacity,transform:s.transform,state:document.querySelector('#skill-motion').dataset.motionState}}"""))
      after=page.evaluate("""()=>({scrollX,scrollY,focus:document.activeElement.id,rect:(()=>{const r=document.querySelector('#skill-motion').getBoundingClientRect();return [r.x,r.y,r.width,r.height]})(),delay:getComputedStyle(document.querySelector('#verified-skill-seal')).animationDelay,duration:getComputedStyle(document.querySelector('#verified-skill-seal')).animationDuration})""")
      report['motion'][vpkey]={'replays':finals,'equal':finals[0]==finals[1],'stable':before=={k:after[k] for k in ['scrollX','scrollY','focus','rect']},'computed_end_ms':790,'keyboard':keyboard,'before':before,'after':after}
      report['viewports'][vpkey]['runtime']={'console_errors':logs,'page_errors':page_errors,'failed_requests':failed,'external_requests':external}
      page.close()
    rm=browser.new_page(viewport={'width':390,'height':844},reduced_motion='reduce')
    if report['mode']=='localhost': rm.goto(f'http://127.0.0.1:{port}/',wait_until='networkidle')
    else:
      html=(ROOT/'index.html').read_text(encoding='utf-8'); css=(ROOT/'styles/main.css').read_text(encoding='utf-8'); js=(ROOT/'scripts/review.js').read_text(encoding='utf-8')
      import re,base64
      html=re.sub(r"(assets/images/[a-z0-9-]+\.svg)\?v=[^\"']+",lambda m:'data:image/svg+xml;base64,'+base64.b64encode((ROOT/m.group(1)).read_bytes()).decode(),html)
      html=re.sub(r'<link[^>]+href="styles/main.css\?v=[^"]+"[^>]*>',f'<style>{css}</style>',html); html=re.sub(r'<script src="scripts/review.js\?v=[^"]+"></script>',f'<script>{js}</script>',html); rm.set_content(html)
    rm.click('#tab-skill-card'); rm.click('#replay-skill')
    report['reduced_motion']={'state':rm.locator('#skill-motion').get_attribute('data-motion-state'),'missing_visible':rm.get_by_text('MISSING EVIDENCE · 견적 B 보증조건').is_visible(),'exception_visible':rm.get_by_text('EXCEPTION · 긴급 납기 시 규칙 재검토').is_visible()}
    browser.close()
finally:
  server.shutdown(); server.server_close(); os.chdir(old)
# assertions
bad=[]
for vp,states in report['viewports'].items():
  rt=states.get('runtime',{})
  if any(rt.values()): bad.append((vp,'runtime',rt))
  for s,d in states.items():
    if s=='runtime': continue
    if not all([d['selected'],d['visible'],d['others_hidden'],d['roving'],d['assets_rendered']]) or d['overflow']>0 or d['clipping']>0 or d['overlap']>0: bad.append((vp,s,d))
for vp,d in report['motion'].items():
  kb=d['keyboard']
  keyboard_ok=kb['focus']=='tab-brief' and kb['selected']=='true' and kb['panel'] and kb['outlineWidth']=='3px' and kb['outlineStyle']=='solid'
  if not d['equal'] or not d['stable'] or not keyboard_ok or any(x['state']!='complete' for x in d['replays']): bad.append((vp,'motion',d))
if report['reduced_motion']['state']!='complete' or not report['reduced_motion']['missing_visible'] or not report['reduced_motion']['exception_visible']: bad.append(('reduced',report['reduced_motion']))
(ROOT/'evidence/browser-self-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'result':'BROWSER_SELF_CHECK_PASS' if not bad else 'BROWSER_SELF_CHECK_FAIL','mode':report['mode'],'bad':bad},ensure_ascii=False,indent=2))
raise SystemExit(1 if bad else 0)
