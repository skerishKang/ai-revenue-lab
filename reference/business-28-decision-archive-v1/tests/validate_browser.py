from pathlib import Path
import base64
import json
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright, Error as PlaywrightError

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'evidence'
SHOTS = EVIDENCE / 'screenshots'
SHOTS.mkdir(parents=True, exist_ok=True)
PORT = 8765
keys = ['cover','index','dossier','rationale','dissent','followup','mobile']
viewports = [(1440,1100),(768,1024),(390,844)]

def exact_inline_document():
    html = (ROOT / 'index.html').read_text(encoding='utf-8')
    css = (ROOT / 'styles/main.css').read_text(encoding='utf-8')
    js = (ROOT / 'scripts/review.js').read_text(encoding='utf-8')
    html = html.replace('<link rel="stylesheet" href="styles/main.css?v=decision-archive-20260728-1">', f'<style>{css}</style>')
    html = html.replace('<script src="scripts/review.js?v=decision-archive-20260728-1"></script>', f'<script>{js}</script>')
    for asset in (ROOT / 'assets/images').glob('*.svg'):
        uri = 'data:image/svg+xml;base64,' + base64.b64encode(asset.read_bytes()).decode('ascii')
        html = html.replace(f'assets/images/{asset.name}', uri)
    return html

inline_html = exact_inline_document()
server = subprocess.Popen([sys.executable, '-m', 'http.server', str(PORT), '--bind', '127.0.0.1'], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(.6)
http_readback = {}
for rel in ['index.html','styles/main.css','scripts/review.js','assets/images/decision-seal.svg']:
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{PORT}/{rel}', timeout=3) as response:
            http_readback[rel] = response.status
    except Exception as exc:
        http_readback[rel] = f'ERROR:{exc}'

report = {
    'kind':'implementation-browser-self-check',
    'independent_local_validation':False,
    'navigation_mode':None,
    'http_readback':http_readback,
    'viewports':{},
    'motion':{},
    'reduced_motion':{}
}

def load(page):
    try:
        page.goto(f'http://127.0.0.1:{PORT}/', wait_until='networkidle', timeout=8000)
        report['navigation_mode'] = 'localhost-http'
    except PlaywrightError as exc:
        if 'ERR_BLOCKED_BY_ADMINISTRATOR' not in str(exc):
            raise
        page = page.context.new_page()
        page.set_content(inline_html, wait_until='load')
        report['navigation_mode'] = 'inline-exact-bytes-admin-fallback'
    return page

try:
  with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path='/usr/bin/chromium', args=['--no-sandbox'])
    for width,height in viewports:
      context = browser.new_context(viewport={'width':width,'height':height})
      page = context.new_page()
      errors=[]; failed=[]; external=[]
      page.on('console', lambda msg: errors.append(f'console:{msg.type}:{msg.text}') if msg.type=='error' else None)
      page.on('pageerror', lambda exc: errors.append(f'page:{exc}'))
      page.on('requestfailed', lambda req: failed.append(req.url))
      page.on('request', lambda req: external.append(req.url) if req.url.startswith(('http://','https://')) and not req.url.startswith(f'http://127.0.0.1:{PORT}') else None)
      page = load(page)
      states={}
      for key in keys:
        page.click(f'[data-state="{key}"]')
        page.wait_for_timeout(40)
        data=page.evaluate("""(key)=>{const panel=document.querySelector(`[data-state-key="${key}"]`);const text=[...panel.querySelectorAll('h1,h2,h3,p,strong,span,li,dd')];return {overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,hidden:panel.hidden,clipped:text.filter(el=>el.scrollWidth>el.clientWidth+2 && getComputedStyle(el).whiteSpace!=='nowrap').length,active:document.querySelector('[role=tab][aria-selected=true]').dataset.state}}""", key)
        states[key]=data
        page.screenshot(path=str(SHOTS/f'{width}x{height}-{key}.png'), full_page=True)
      page.click('[data-state="cover"]'); page.focus('[data-state="cover"]'); page.keyboard.press('ArrowRight')
      keyboard=page.get_attribute('[role=tab][aria-selected=true]','data-state')=='index'
      page.focus('#tab-rationale')
      focus_outline=page.evaluate("""()=>{const s=getComputedStyle(document.activeElement);return {width:s.outlineWidth,style:s.outlineStyle,color:s.outlineColor}}""")
      report['viewports'][f'{width}x{height}']={'states':states,'errors':errors,'failed_requests':failed,'external_requests':external,'keyboard':keyboard,'focus_outline':focus_outline}
      context.close()
    context=browser.new_context(viewport={'width':1440,'height':1100})
    page=load(context.new_page()); page.click('[data-state="rationale"]')
    final=[]
    for replay in range(2):
      page.click('#replay-reason')
      page.wait_for_function("document.querySelector('#reason-chain').dataset.motionState==='running'")
      start=page.get_attribute('#reason-chain','data-motion-state')
      timings=page.evaluate("""()=>[...document.querySelectorAll('#reason-chain *')].map(e=>{const c=getComputedStyle(e);return {selector:e.id?`#${e.id}`:e.className,duration:c.animationDuration,delay:c.animationDelay,name:c.animationName}}).filter(x=>x.name&&x.name!=='none')""")
      page.wait_for_function("document.querySelector('#reason-chain').dataset.motionState==='complete'")
      styles=page.evaluate("""()=>{const ids=['.option-a','.option-b','.option-c','.reason.accepted','.reason.rejected','.assumption','.dissent-margin','.accountability','.revisit-trigger','#decision-seal'];return ids.map(s=>{const e=document.querySelector(s),c=getComputedStyle(e);return [s,c.opacity,c.transform,c.clipPath,c.display]})}""")
      final.append(styles)
      report['motion'][f'replay_{replay+1}_start']=start
      if replay == 0:
          report['motion']['computed_animations']=timings
    report['motion']['final_equivalent']=final[0]==final[1]
    report['motion']['final_state']=page.get_attribute('#reason-chain','data-motion-state')
    report['motion']['completion_authority']='decision-seal animationend: reasonSeal'
    context.close()
    context=browser.new_context(viewport={'width':390,'height':844}, reduced_motion='reduce')
    page=load(context.new_page()); page.click('[data-state="rationale"]'); page.click('#replay-reason')
    report['reduced_motion']={'state':page.get_attribute('#reason-chain','data-motion-state'),'seal_opacity':page.evaluate("getComputedStyle(document.querySelector('#decision-seal')).opacity"),'overflow':page.evaluate('document.documentElement.scrollWidth-document.documentElement.clientWidth')}
    page.screenshot(path=str(SHOTS/'390x844-rationale-reduced-motion.png'), full_page=True)
    context.close(); browser.close()
finally:
  server.terminate(); server.wait(timeout=5)
EVIDENCE.mkdir(exist_ok=True)
(EVIDENCE/'browser-self-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
problems=[]
if not all(value == 200 for value in report['http_readback'].values()): problems.append('http_readback')
for vp,data in report['viewports'].items():
  if data['errors'] or data['failed_requests'] or data['external_requests'] or not data['keyboard']: problems.append(vp)
  if data['focus_outline']['style'] in ('none','hidden') or data['focus_outline']['width'] in ('0px','0'): problems.append(f'{vp}:focus')
  for state,detail in data['states'].items():
    if detail['overflow']!=0 or detail['hidden'] or detail['active']!=state or detail['clipped']!=0: problems.append(f'{vp}:{state}')
if report['motion'].get('final_state')!='complete' or not report['motion'].get('final_equivalent'): problems.append('motion')
if report['reduced_motion'].get('state')!='complete' or report['reduced_motion'].get('overflow')!=0 or report['reduced_motion'].get('seal_opacity')!='1': problems.append('reduced_motion')
print('BROWSER_SELF_CHECK_PASS' if not problems else 'BROWSER_SELF_CHECK_FAIL '+','.join(problems))
raise SystemExit(1 if problems else 0)
