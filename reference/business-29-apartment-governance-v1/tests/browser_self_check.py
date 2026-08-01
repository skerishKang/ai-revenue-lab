from pathlib import Path
import base64, json, re
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
states=['cover','meeting','rules','spending','election','complaint','mobile']
viewports=[(1440,1100),(768,1024),(390,844)]

def inline_document():
    html=(ROOT/'index.html').read_text(encoding='utf-8')
    css=(ROOT/'styles/main.css').read_text(encoding='utf-8')
    js=(ROOT/'scripts/review.js').read_text(encoding='utf-8')
    html=re.sub(r'<link rel="stylesheet"[^>]+>',f'<style>{css}</style>',html,count=1)
    html=re.sub(r'<script src="scripts/review\.js\?[^\"]+"></script>',f'<script>history.replaceState=()=>{{}};</script><script>{js}</script>',html,count=1)
    for path in (ROOT/'assets/images').glob('*.svg'):
        encoded=base64.b64encode(path.read_bytes()).decode('ascii')
        html=html.replace(f'assets/images/{path.name}',f'data:image/svg+xml;base64,{encoded}')
    return html

def ms(value):
    value=value.strip()
    return float(value[:-2]) if value.endswith('ms') else float(value[:-1])*1000 if value.endswith('s') else 0

DOC=inline_document()
result={'status':'pass','captures':[],'console_errors':[],'page_errors':[],'runtime_requests':[],'errors':[]}
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
    page=browser.new_page()
    page.on('console',lambda msg: result['console_errors'].append(msg.text) if msg.type=='error' else None)
    page.on('pageerror',lambda exc: result['page_errors'].append(str(exc)))
    page.on('request',lambda req: result['runtime_requests'].append(req.url))
    for w,h in viewports:
        page.set_viewport_size({'width':w,'height':h})
        for state in states:
            page.set_content(DOC,wait_until='load')
            page.evaluate("([state])=>window.__apartmentGovernanceReview.setState(state,{updateUrl:false})",[state])
            page.wait_for_timeout(30)
            overflow=page.evaluate('document.documentElement.scrollWidth-document.documentElement.clientWidth')
            visible=page.locator(f'[data-state="{state}"]').is_visible()
            selected=page.locator(f'[data-state-target="{state}"]').get_attribute('aria-selected')=='true'
            broken=page.evaluate("[...document.images].filter(i=>!i.complete||i.naturalWidth===0).length")
            labels_readable=page.evaluate("""() => [...document.querySelectorAll('[data-state]:not([hidden]) .status')].every(e => {const r=e.getBoundingClientRect(); return r.width>20 && r.height>10 && r.left>=-1 && r.right<=innerWidth+1})""")
            word_split=[]
            if state=='cover':
                for sel,words in [['#cover-title',['방림명지로드힐','결정은','후속','공개']],['.identity h1',['방림명지로드힐','우리단지','운영실']]]:
                    word_split += page.evaluate("""(pairs) => {
                      const out = [];
                      for (const [sel, word] of pairs) {
                        const el = document.querySelector(sel);
                        if (!el) { out.push({sel, word, error:'missing element'}); continue; }
                        const idx = el.textContent.indexOf(word);
                        if (idx < 0) { out.push({sel, word, error:'word not found'}); continue; }
                        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
                        let n, acc = 0, found = null;
                        while ((n = walker.nextNode())) {
                          const len = n.textContent.length;
                          if (idx >= acc && idx < acc + len) { found = {node: n, offset: idx - acc}; break; }
                          acc += len;
                        }
                        if (!found) { out.push({sel, word, error:'text node not found'}); continue; }
                        const range = document.createRange();
                        range.setStart(found.node, found.offset);
                        range.setEnd(found.node, found.offset + word.length);
                        const rects = range.getClientRects();
                        const tops = new Set([...rects].map(r => Math.round(r.top)));
                        out.push({sel, word, rects: rects.length, split: tops.size > 1});
                      }
                      return out;
                    }""", [[sel, w] for w in words])
            result['captures'].append({'state':state,'viewport':[w,h],'overflow':overflow,'visible':visible,'selected':selected,'broken':broken,'labels_readable':labels_readable,'word_split':word_split})
    page.set_viewport_size({'width':1440,'height':1100})
    page.emulate_media(reduced_motion='no-preference')
    page.set_content(DOC,wait_until='load')
    page.evaluate("window.__apartmentGovernanceReview.setState('meeting',{updateUrl:false})")
    page.wait_for_function("document.querySelector('[data-agenda-resolution]').dataset.motionState==='complete'")
    page.wait_for_timeout(320)
    replay=page.locator('[data-motion-replay]'); replay.focus()
    focus_before=page.evaluate('document.activeElement.matches("[data-motion-replay]")')
    scroll_before=page.evaluate('scrollY')
    geometry_before=page.evaluate("""() => {const a=document.querySelector('[data-agenda-resolution]').getBoundingClientRect(); const b=document.querySelector('.public-notice-complete').getBoundingClientRect(); return [a.x,a.y,a.width,a.height,b.x,b.y,b.width,b.height]}""")
    replay.click()
    timing=page.evaluate("""() => {const e=document.querySelector('.public-notice-complete');const c=getComputedStyle(e);return {delay:c.animationDelay,duration:c.animationDuration,name:c.animationName}}""")
    page.wait_for_function("document.querySelector('[data-agenda-resolution]').dataset.motionState==='complete'")
    final1=page.evaluate("""() => ['.rule-piece','.disclosure-split','.budget-piece','.dissent-piece','.quorum-piece','.resolution-seal','.public-notice-complete'].map(s=>{const c=getComputedStyle(document.querySelector(s));return [s,c.opacity,c.transform,c.clipPath]})""")
    geometry_after1=page.evaluate("""() => {const a=document.querySelector('[data-agenda-resolution]').getBoundingClientRect(); const b=document.querySelector('.public-notice-complete').getBoundingClientRect(); return [a.x,a.y,a.width,a.height,b.x,b.y,b.width,b.height]}""")
    focus_after1=page.evaluate('document.activeElement.matches("[data-motion-replay]")'); scroll_after1=page.evaluate('scrollY')
    replay.click();page.wait_for_function("document.querySelector('[data-agenda-resolution]').dataset.motionState==='complete'")
    final2=page.evaluate("""() => ['.rule-piece','.disclosure-split','.budget-piece','.dissent-piece','.quorum-piece','.resolution-seal','.public-notice-complete'].map(s=>{const c=getComputedStyle(document.querySelector(s));return [s,c.opacity,c.transform,c.clipPath]})""")
    geometry_after2=page.evaluate("""() => {const a=document.querySelector('[data-agenda-resolution]').getBoundingClientRect(); const b=document.querySelector('.public-notice-complete').getBoundingClientRect(); return [a.x,a.y,a.width,a.height,b.x,b.y,b.width,b.height]}""")
    focus_after2=page.evaluate('document.activeElement.matches("[data-motion-replay]")');scroll_after2=page.evaluate('scrollY')
    page.emulate_media(reduced_motion='reduce');replay.click()
    reduced_complete=page.locator('[data-agenda-resolution]').get_attribute('data-motion-state')=='complete'
    reduced_visible=page.evaluate("""() => ['.rule-piece','.disclosure-split','.budget-piece','.dissent-piece','.quorum-piece','.resolution-seal','.public-notice-complete'].every(s=>getComputedStyle(document.querySelector(s)).opacity==='1')""")
    page.emulate_media(reduced_motion='no-preference')
    page.locator('[data-state-target="cover"]').focus();page.keyboard.press('ArrowRight')
    keyboard=page.locator('[data-state-target="meeting"]').get_attribute('aria-selected')=='true'
    browser.close()
end_ms=ms(timing['delay'])+ms(timing['duration'])
geometry_stable=geometry_before==geometry_after1==geometry_after2
replay_equivalent=final1==final2
focus_stable=focus_before and focus_after1 and focus_after2
scroll_stable=scroll_before==scroll_after1==scroll_after2
failures=[]
for c in result['captures']:
    if c['overflow']!=0 or not c['visible'] or not c['selected'] or c['broken']!=0 or not c['labels_readable']: failures.append(c)
    if any(x.get('split') for x in c.get('word_split',[])): failures.append({'state':c['state'],'viewport':c['viewport'],'word_split':c.get('word_split')})
if result['console_errors'] or result['page_errors'] or result['runtime_requests']: failures.append('runtime')
if not (focus_stable and scroll_stable and geometry_stable and replay_equivalent and reduced_complete and reduced_visible and keyboard and 680<=end_ms<=780): failures.append('interaction')
result['motion']={'computed':timing,'computed_end_ms':end_ms,'focus_stable':focus_stable,'scroll_stable':scroll_stable,'geometry_stable':geometry_stable,'replay_equivalent':replay_equivalent,'reduced_complete':reduced_complete,'reduced_visible':reduced_visible,'keyboard':keyboard,'geometry_before':geometry_before,'geometry_after1':geometry_after1,'geometry_after2':geometry_after2}
result['errors']=failures;result['status']='pass' if not failures else 'fail'
(ROOT/'evidence/browser-self-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
raise SystemExit(1 if failures else 0)
