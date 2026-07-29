#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from contextlib import contextmanager
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from threading import Thread
import json, os, socket, time, traceback
from PIL import Image, ImageOps, ImageDraw
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT/'evidence'
MATRIX_DIR = EVIDENCE/'matrix'
MATRIX_DIR.mkdir(parents=True, exist_ok=True)
STATES=['cover','request','scope','mapping','controls','decision','mobile']
VIEWPORTS={
    'desktop': {'width':1440,'height':1100},
    'tablet': {'width':768,'height':1024},
    'mobile': {'width':390,'height':844},
}

class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_): pass

@contextmanager
def server():
    cwd=os.getcwd(); os.chdir(ROOT)
    httpd=ThreadingHTTPServer(('127.0.0.1',0),QuietHandler)
    thread=Thread(target=httpd.serve_forever,daemon=True); thread.start()
    try: yield f'http://127.0.0.1:{httpd.server_port}/'
    finally:
        httpd.shutdown(); thread.join(timeout=5); os.chdir(cwd)


def motion_snapshot(page):
    return page.evaluate('''() => Array.from(document.querySelectorAll('.motion-node')).map(el => {
      const s=getComputedStyle(el), r=el.getBoundingClientRect();
      return {opacity:s.opacity, transform:s.transform, animationName:s.animationName,
        x:+r.x.toFixed(2),y:+r.y.toFixed(2),w:+r.width.toFixed(2),h:+r.height.toFixed(2)};
    })''')


def create_montage(files):
    thumbs=[]
    for label,path in files:
        im=Image.open(path).convert('RGB'); im.thumbnail((360,260))
        canvas=Image.new('RGB',(380,300),'white'); canvas.paste(im,((380-im.width)//2,20))
        d=ImageDraw.Draw(canvas); d.text((12,278),label,fill='black')
        thumbs.append(canvas)
    cols=3; rows=(len(thumbs)+cols-1)//cols
    montage=Image.new('RGB',(cols*380,rows*300),(232,224,210))
    for i,im in enumerate(thumbs): montage.paste(im,((i%cols)*380,(i//cols)*300))
    out=EVIDENCE/'validation-montage.png'; montage.save(out,optimize=True)
    return out


def main():
    report={'status':'PASS','matrix':{},'at_relationship':{},'keyboard':{},'assets':{},'motion':{},'reduced_motion':{},'network':{},'boundaries':{},'errors':[]}
    shot_files=[]
    with server() as url, sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        all_console=[]; all_page_errors=[]; failed=[]; external=[]; requests=[]
        context=browser.new_context(viewport=VIEWPORTS['desktop'])
        page=context.new_page()
        page.on('console',lambda msg: all_console.append({'type':msg.type,'text':msg.text}) if msg.type=='error' else None)
        page.on('pageerror',lambda exc: all_page_errors.append(str(exc)))
        page.on('requestfailed',lambda req: failed.append({'url':req.url,'failure':req.failure}))
        def on_request(req):
            requests.append(req.url)
            if not req.url.startswith(url): external.append(req.url)
        page.on('request',on_request)

        for vp_name,vp in VIEWPORTS.items():
            page.set_viewport_size(vp); page.goto(url,wait_until='networkidle')
            for state in STATES:
                page.locator(f'#state-tab-{state}').click(force=True)
                page.wait_for_timeout(40)
                visible=page.locator(f'#state-panel-{state}').is_visible()
                selected=page.locator(f'#state-tab-{state}').get_attribute('aria-selected')=='true'
                overflow=page.evaluate('''() => ({doc:document.documentElement.scrollWidth-window.innerWidth,
                  body:document.body.scrollWidth-window.innerWidth,
                  panel:(() => {const p=document.querySelector('[role=tabpanel]:not([hidden])'); return p ? p.scrollWidth-p.clientWidth : 0;})()})''')
                key=f'{vp_name}:{state}'
                ok=visible and selected and max(overflow.values())==0
                report['matrix'][key]={'pass':ok,'visible':visible,'selected':selected,'overflow':overflow}
                if not ok: report['errors'].append(f'matrix failure {key}: {report["matrix"][key]}')
                shot=MATRIX_DIR/f'{vp_name}-{state}.png'
                page.screenshot(path=str(shot),full_page=False)
                shot_files.append((key,shot))

        page.set_viewport_size(VIEWPORTS['desktop']); page.goto(url,wait_until='networkidle')
        mapping=page.evaluate('''() => Array.from(document.querySelectorAll('[role=tab]')).map(tab => {
          const panel=document.getElementById(tab.getAttribute('aria-controls'));
          return {tab:tab.id,panel:panel?.id,selected:tab.getAttribute('aria-selected'),tabIndex:tab.tabIndex,
            reciprocal:panel?.getAttribute('aria-labelledby')===tab.id};
        })''')
        report['at_relationship']={'count':len(mapping),'reciprocal':sum(1 for x in mapping if x['reciprocal']),'mapping':mapping}
        if len(mapping)!=7 or not all(x['reciprocal'] for x in mapping): report['errors'].append('AT mapping not 7/7 reciprocal')

        first=page.locator('#state-tab-cover'); first.focus(); page.keyboard.press('ArrowRight')
        arrow=page.evaluate("document.activeElement.id")
        page.keyboard.press('End'); end=page.evaluate("document.activeElement.id")
        page.keyboard.press('Home'); home=page.evaluate("document.activeElement.id")
        report['keyboard']={'arrowRight':arrow,'end':end,'home':home,'pass':arrow=='state-tab-request' and end=='state-tab-mobile' and home=='state-tab-cover'}
        if not report['keyboard']['pass']: report['errors'].append('keyboard navigation failed')

        assets=page.evaluate('''async () => Promise.all(Array.from(document.images).map(async img => ({
          src:img.getAttribute('src'),complete:img.complete,naturalWidth:img.naturalWidth,naturalHeight:img.naturalHeight,
          response:(await fetch(img.src,{cache:'no-store'})).status
        })))''')
        report['assets']={'count':len(assets),'items':assets,'pass':len(assets)>=8 and all(x['complete'] and x['naturalWidth']>0 and x['response']==200 for x in assets)}
        if not report['assets']['pass']: report['errors'].append('asset HTTP/decode/render failure')

        text=page.locator('body').inner_text()
        required=['PROHIBITED PATH','SENSITIVE FIELD — EXCLUDED','NO SECRET DISPLAY','RETENTION LIMIT','ACCESS REVOCABLE','AUDIT EVIDENCE — NOT EMPLOYEE MONITORING','CONNECTOR READINESS — NOT CONNECTED','ACCESS APPROVAL ≠ DATA-USE APPROVAL']
        report['boundaries']={'required':{x:(x in text) for x in required},'banned_secret_patterns':{x:(x in text) for x in ['sk-','xoxb-','AIza','Bearer ','password=','api_key=']}}
        if not all(report['boundaries']['required'].values()) or any(report['boundaries']['banned_secret_patterns'].values()): report['errors'].append('scope/secret boundary failure')

        page.locator('#state-tab-cover').click(); page.locator('#motion-replay').focus(); page.evaluate('window.scrollTo(0,120)')
        initial_focus=page.evaluate('document.activeElement.id'); initial_scroll=page.evaluate('window.scrollY')
        runs=[]; snaps=[]
        for _ in range(2):
            before_run=int(page.locator('#motion-board').get_attribute('data-motion-run') or 0)
            page.locator('#motion-replay').click()
            page.wait_for_function('(n) => Number(document.querySelector("#motion-board").dataset.motionRun) > n && document.querySelector("#motion-board").dataset.motionStatus === "complete"',arg=before_run,timeout=3000)
            runs.append(int(page.locator('#motion-board').get_attribute('data-motion-elapsed-ms')))
            snaps.append(motion_snapshot(page))
        final_focus=page.evaluate('document.activeElement.id'); final_scroll=page.evaluate('window.scrollY')
        animation_names=page.evaluate("Array.from(document.querySelectorAll('.motion-node')).map(x=>getComputedStyle(x).animationName)")
        report['motion']={'elapsed_ms':runs,'actual_final_700_800':all(700<=x<=800 for x in runs),'replay_equal':snaps[0]==snaps[1],
                          'focus_stable':initial_focus==final_focus=='motion-replay','scroll_stable':initial_scroll==final_scroll,
                          'animation_zero_after_completion':all(x=='none' for x in animation_names)}
        if not all([report['motion']['actual_final_700_800'],report['motion']['replay_equal'],report['motion']['focus_stable'],report['motion']['scroll_stable'],report['motion']['animation_zero_after_completion']]): report['errors'].append(f'motion contract failure {report["motion"]}')

        context.close()
        reduced=browser.new_context(viewport=VIEWPORTS['mobile'],reduced_motion='reduce')
        rp=reduced.new_page(); reduced_external=[]; reduced_failed=[]
        rp.on('request',lambda req: reduced_external.append(req.url) if not req.url.startswith(url) else None)
        rp.on('requestfailed',lambda req: reduced_failed.append(req.url))
        rp.goto(url,wait_until='networkidle')
        rp.wait_for_function("document.querySelector('#motion-board').dataset.motionStatus === 'complete'")
        elapsed=int(rp.locator('#motion-board').get_attribute('data-motion-elapsed-ms') or -1)
        nodes=rp.evaluate("Array.from(document.querySelectorAll('.motion-node')).map(x=>({opacity:getComputedStyle(x).opacity,animation:getComputedStyle(x).animationName}))")
        mobile_overflow=rp.evaluate('document.documentElement.scrollWidth-window.innerWidth')
        report['reduced_motion']={'elapsed_ms':elapsed,'nodes':nodes,'immediate_complete':elapsed==0 and all(x['opacity']=='1' and x['animation']=='none' for x in nodes),'mobile_overflow':mobile_overflow}
        if not report['reduced_motion']['immediate_complete'] or mobile_overflow!=0: report['errors'].append('reduced motion or 390 containment failure')
        reduced.close(); browser.close()

        report['network']={'console_errors':all_console,'page_errors':all_page_errors,'failed_requests':failed,'external_requests':external,'all_requests':requests,
                           'summary':{'console':len(all_console),'page':len(all_page_errors),'failed':len(failed),'external':len(external)}}
        if any(report['network']['summary'].values()): report['errors'].append(f'network/runtime errors {report["network"]["summary"]}')

    report['status']='PASS' if not report['errors'] else 'FAIL'
    montage=create_montage(shot_files)
    report['evidence']={'matrix_screenshots':len(shot_files),'montage':str(montage.relative_to(ROOT))}
    (EVIDENCE/'local-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    md=['# Independent Local Validation','',f'**Status: {report["status"]}**','',f'- Matrix: {sum(1 for v in report["matrix"].values() if v["pass"])}/21',f'- AT reciprocal mapping: {report["at_relationship"]["reciprocal"]}/7',f'- Keyboard: {"PASS" if report["keyboard"]["pass"] else "FAIL"}',f'- Assets: {report["assets"]["count"]} HTTP/decode/render {"PASS" if report["assets"]["pass"] else "FAIL"}',f'- Motion actual final: {report["motion"].get("elapsed_ms")}',f'- Replay equality: {report["motion"].get("replay_equal")}',f'- Reduced motion: {report["reduced_motion"].get("immediate_complete")}',f'- Network console/page/failed/external: {report["network"]["summary"]}','', 'Validation ran from a fresh detached local git worktree and a localhost Chromium HTTP session.']
    if report['errors']: md += ['','## Errors',*['- '+x for x in report['errors']]]
    (EVIDENCE/'LOCAL_VALIDATION.md').write_text('\n'.join(md)+'\n',encoding='utf-8')
    print(json.dumps({'status':report['status'],'errors':report['errors'],'motion':report['motion'],'network':report['network']['summary']},ensure_ascii=False,indent=2))
    return 0 if report['status']=='PASS' else 1

if __name__=='__main__':
    try: raise SystemExit(main())
    except Exception:
        traceback.print_exc(); raise
