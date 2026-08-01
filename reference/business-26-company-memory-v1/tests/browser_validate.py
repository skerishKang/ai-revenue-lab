from __future__ import annotations
import base64, json, re
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/'evidence'; EVIDENCE.mkdir(exist_ok=True)
STATES=['cover','chronology','thread','lineage','witnesses','reconstruction','mobile']
VIEWPORTS=[(1440,1100),(768,1024),(390,844)]

def document():
    html=(ROOT/'index.html').read_text(encoding='utf-8')
    css=(ROOT/'styles.css').read_text(encoding='utf-8')
    js=(ROOT/'app.js').read_text(encoding='utf-8')
    html=re.sub(r'<link rel="stylesheet"[^>]+>',f'<style>{css}</style>',html,count=1)
    html=re.sub(r'<script src="app\.js\?[^\"]+"></script>',f'<script>history.replaceState=()=>{{}};</script><script>{js}</script>',html,count=1)
    for path in (ROOT/'assets/images').glob('*.svg'):
        data=base64.b64encode(path.read_bytes()).decode()
        html=html.replace(f'assets/images/{path.name}',f'data:image/svg+xml;base64,{data}')
    return html

def ms(value:str)->float:
    return float(value[:-2]) if value.endswith('ms') else float(value[:-1])*1000

def rect(page,selector):
    return page.locator(selector).bounding_box()

def close(a,b,tol=.2):
    return all(abs(a[k]-b[k])<=tol for k in ('x','y','width','height'))

def main():
    console=[]; errors=[]; requests=[]; captures=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1440,'height':1100})
        page.on('console',lambda msg: console.append(msg.text) if msg.type=='error' else None)
        page.on('pageerror',lambda exc: errors.append(str(exc)))
        page.on('request',lambda req: requests.append(req.url))
        doc=document()
        def load(state,reduced=False):
            page.set_viewport_size({'width':1440,'height':1100})
            page.emulate_media(reduced_motion='reduce' if reduced else 'no-preference')
            page.set_content(doc,wait_until='load')
            page.evaluate("s=>window.__companyMemoryReview.setState(s,{updateUrl:false})",state)
        for width,height in VIEWPORTS:
            for state in STATES:
                page.set_viewport_size({'width':width,'height':height}); page.emulate_media(reduced_motion='no-preference')
                page.set_content(doc,wait_until='load'); page.evaluate("s=>window.__companyMemoryReview.setState(s,{updateUrl:false})",state)
                if state=='reconstruction': page.wait_for_timeout(760)
                captures.append({'state':state,'viewport':[width,height],'overflow':page.evaluate('document.documentElement.scrollWidth-document.documentElement.clientWidth'),'reduced':False})
        page.set_viewport_size({'width':1440,'height':1100}); load('cover')
        page.locator('[data-state-target="cover"]').focus(); page.keyboard.press('ArrowRight')
        arrow=page.locator('[data-state-target="chronology"]').get_attribute('aria-selected')=='true'
        page.keyboard.press('End'); end=page.locator('[data-state-target="mobile"]').get_attribute('aria-selected')=='true'
        focus=page.evaluate("getComputedStyle(document.activeElement).outlineStyle!='none'")
        load('reconstruction'); button=page.locator('[data-motion-replay]'); button.focus()
        before_anchor=rect(page,'[data-anchor]'); before_box=rect(page,'[data-reconstruction]'); before_scroll=page.evaluate('[scrollX,scrollY]')
        page.evaluate('window.__companyMemoryReview.replayReconstruction()')
        running=page.locator('[data-reconstruction]').get_attribute('data-motion-state')=='running'
        removed=not page.locator('[data-reconstruction]').evaluate("e=>e.classList.contains('is-complete')")
        timing=page.eval_on_selector_all('[data-motion-step]',"els=>els.map(e=>{const s=getComputedStyle(e);const cv=v=>v.endsWith('ms')?parseFloat(v):parseFloat(v)*1000;const d=cv(s.animationDelay),u=cv(s.animationDuration);return {step:e.dataset.motionStep,delay:d,duration:u,end:d+u}})")
        final_end=max(x['end'] for x in timing); page.wait_for_timeout(final_end+80)
        final_state=page.locator('[data-reconstruction]').get_attribute('data-motion-state')
        stability={'anchor':close(before_anchor,rect(page,'[data-anchor]')),'container':close(before_box,rect(page,'[data-reconstruction]')),'scroll':before_scroll==page.evaluate('[scrollX,scrollY]'),'focus':page.evaluate("document.activeElement.matches('[data-motion-replay]')")}
        visible={'source_ids':page.locator('[data-motion-step="source-a"]').is_visible(),'contradiction':page.locator('[data-motion-step="contradiction"]').is_visible(),'missing_evidence':page.locator('[data-motion-step="missing"]').is_visible()}
        load('reconstruction',True); button=page.locator('[data-motion-replay]'); button.focus(); page.evaluate('window.__companyMemoryReview.replayReconstruction()')
        reduced={'state':page.locator('[data-reconstruction]').get_attribute('data-motion-state'),'focus':page.evaluate("document.activeElement.matches('[data-motion-replay]')"),'visible':all(page.locator(f'[data-motion-step="{s}"]').is_visible() for s in ['source-a','contradiction','missing','human-review'])}
        images=page.evaluate("[...document.images].filter(i=>!i.complete||!i.naturalWidth).map(i=>i.alt)")
        labels=all(t in page.locator('body').inner_text() for t in ['당시 기록','나중 회고','확인된 사실','편집상 추론','충돌 설명','누락 증거','이후 결과'])
        synthetic='합성' in page.locator('body').inner_text(); version=page.evaluate('window.__companyMemoryReview.version'); browser.close()
    failures=[]
    if any(c['overflow'] for c in captures): failures.append('horizontal overflow')
    if console: failures.append('console errors')
    if errors: failures.append('page errors')
    if requests: failures.append('external runtime requests')
    if images: failures.append('broken images')
    if not all([arrow,end,focus,labels,synthetic]): failures.append('keyboard/focus/labels')
    if not (680<=final_end<=760 and running and removed and final_state=='complete'): failures.append('motion contract')
    if not all(stability.values()) or not all(visible.values()) or reduced!={'state':'complete','focus':True,'visible':True}: failures.append('stability/reduced motion')
    result={'status':'pass' if not failures else 'fail','version':version,'states':STATES,'captures':captures,'console_errors':console,'page_errors':errors,'external_runtime_requests':requests,'local_image_failures':images,'keyboard':{'arrow_right':arrow,'end':end,'visible_focus':focus},'motion':{'computed_final_end_ms':final_end,'steps':timing,'running':running,'complete_removed_on_replay':removed,'final_state':final_state},'stability':stability,'final_visibility':visible,'reduced_motion':reduced,'labels_visible':labels,'synthetic_visible':synthetic,'failures':failures}
    (EVIDENCE/'motion-timing.json').write_text(json.dumps({'steps':timing,'finalEnd':final_end},ensure_ascii=False,indent=2),encoding='utf-8')
    (EVIDENCE/'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if failures: raise SystemExit(1)
if __name__=='__main__': main()
