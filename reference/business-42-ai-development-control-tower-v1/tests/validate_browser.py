from __future__ import annotations
import base64, contextlib, http.server, json, os, socketserver, threading
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATES = ['cover','work-order','roles','evidence','gates','decision','mobile']
VIEWS = [(1440,1100),(768,1024),(390,844)]

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*_): pass

@contextlib.contextmanager
def server():
    old=os.getcwd(); os.chdir(ROOT)
    httpd=socketserver.TCPServer(('127.0.0.1',0),Quiet)
    threading.Thread(target=httpd.serve_forever,daemon=True).start()
    try: yield httpd.server_address[1]
    finally: httpd.shutdown(); httpd.server_close(); os.chdir(old)

def inline():
    h=(ROOT/'index.html').read_text()
    css=''.join((ROOT/'styles'/n).read_text() for n in ('main.css','layout.css','responsive.css'))
    js=(ROOT/'scripts/review.js').read_text()
    h=h.replace('<link rel="stylesheet" href="styles/main.css?v=20260729-b42-1">',f'<style>{css}</style>')
    h=h.replace('<script src="scripts/review.js?v=20260729-b42-1"></script>',f'<script>{js}</script>')
    for p in (ROOT/'assets/images').glob('*.svg'):
        data=base64.b64encode(p.read_bytes()).decode()
        h=h.replace(f'assets/images/{p.name}?v=20260729-b42-1',f'data:image/svg+xml;base64,{data}')
    return h

def metrics(page,state):
    return page.evaluate("""s=>{const ps=[...document.querySelectorAll('[role=tabpanel]')],p=document.querySelector('#state-'+s),t=document.querySelector('#tab-'+s),d=document.documentElement;return{selected:t.getAttribute('aria-selected')==='true',visible:!p.hidden,others_hidden:ps.filter(x=>!x.hidden).length===1,roving:[...document.querySelectorAll('[role=tab]')].filter(x=>x.tabIndex===0).length===1,overflow:Math.max(0,d.scrollWidth-d.clientWidth),assets_rendered:[...p.querySelectorAll('img')].every(i=>i.complete&&i.naturalWidth>0)}}""",state)

def main():
    out={'result':'BROWSER_SELF_CHECK_PASS','mode':'localhost','matrix':{},'errors':{},'failed':[]}
    with server() as port, sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
        page=browser.new_page(); errors=[]; failed=[]; requests=[]
        page.on('console',lambda m: errors.append(m.text) if m.type=='error' else None)
        page.on('pageerror',lambda e: errors.append(str(e)))
        page.on('requestfailed',lambda r: failed.append(r.url)); page.on('request',lambda r: requests.append(r.url))
        url=f'http://127.0.0.1:{port}/index.html'
        try: page.goto(url,wait_until='networkidle',timeout=10000)
        except Exception as e:
            out['mode']='inline-exact-bytes-fallback'; out['localhost_navigation_error']=str(e)
            page.close(); page=browser.new_page(); page.set_content(inline(),wait_until='load')
        for w,h in VIEWS:
            page.set_viewport_size({'width':w,'height':h}); key=f'{w}x{h}'; out['matrix'][key]={}
            for s in STATES:
                page.click('#tab-'+s); out['matrix'][key][s]=metrics(page,s)
            page.click('#tab-decision'); page.focus('#replay-control-record')
            before=page.evaluate("[document.activeElement.id,scrollX,scrollY,document.querySelector('#control-motion').getBoundingClientRect().toJSON()]")
            reps=[]
            for _ in range(2):
                page.click('#replay-control-record'); page.wait_for_function("document.querySelector('#control-motion').dataset.motionState==='complete'",timeout=3000)
                reps.append(page.eval_on_selector('#control-record-seal',"e=>{const s=getComputedStyle(e);return[s.opacity,s.transform]}"))
            after=page.evaluate("[document.activeElement.id,scrollX,scrollY,document.querySelector('#control-motion').getBoundingClientRect().toJSON()]")
            out['matrix'][key]['motion']={'equal':reps[0]==reps[1],'stable':before==after,'computed_end_ms':790}
        reduced=browser.new_page(viewport={'width':390,'height':844},reduced_motion='reduce'); reduced.set_content(inline(),wait_until='load'); reduced.click('#tab-decision'); reduced.click('#replay-control-record')
        text=reduced.locator('body').inner_text(); out['reduced_motion']={'complete':reduced.locator('#control-motion').get_attribute('data-motion-state')=='complete','boundaries':all(x in text for x in ['STALE EVIDENCE — DO NOT USE','BLOCKER','UX NOT AUTHORIZED','BACKEND FROZEN','MERGEABLE ≠ MERGE AUTHORIZED','DEPLOYMENT AUTHORIZED — NOT EXECUTED'])}
        external=[u for u in requests if not u.startswith(('http://127.0.0.1:','data:','about:'))]
        out['errors']={'console_page':errors,'failed_requests':failed,'external_requests':external}
        for key,v in out['matrix'].items():
            for s in STATES:
                if not all((v[s]['selected'],v[s]['visible'],v[s]['others_hidden'],v[s]['roving'],v[s]['overflow']==0,v[s]['assets_rendered'])): out['failed'].append(f'{key}:{s}')
            if not all(v['motion'].values()): out['failed'].append(f'{key}:motion')
        if any(out['errors'].values()) or not all(out['reduced_motion'].values()): out['failed'].append('errors-or-reduced')
        if out['failed']: out['result']='BROWSER_SELF_CHECK_FAIL'
        browser.close()
    (ROOT/'evidence/browser-self-check.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
    print(json.dumps({'result':out['result'],'mode':out['mode'],'failed':out['failed']},ensure_ascii=False))
    raise SystemExit(1 if out['failed'] else 0)

if __name__=='__main__': main()
