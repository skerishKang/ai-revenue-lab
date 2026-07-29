from pathlib import Path
import asyncio, json, hashlib, sys, base64, mimetypes, re
from playwright.async_api import async_playwright
ROOT=Path(__file__).resolve().parents[1]
viewports=[(1440,1100),(768,1024),(390,844)]
states=['cover','brief','structure','variants','quality','kit','mobile']

def inline_document():
    html=(ROOT/'index.html').read_text(encoding='utf-8')
    css=(ROOT/'styles/main.css').read_text(encoding='utf-8')
    js=(ROOT/'scripts/review.js').read_text(encoding='utf-8')
    html=re.sub(r'<link rel="stylesheet"[^>]+>', '<style>'+css+'</style>', html)
    html=re.sub(r'<script src="scripts/review.js[^>]*></script>', '<script>'+js+'</script>', html)
    for path in (ROOT/'assets/images').iterdir():
        mime=mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        uri='data:'+mime+';base64,'+base64.b64encode(path.read_bytes()).decode('ascii')
        html=html.replace('assets/images/'+path.name+'?v=ace-v1', uri)
    return html

async def main():
    errors=[]; combos=[]; request_urls=[]; console_errors=[]; page_errors=[]
    document=inline_document()
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True, executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        context=await browser.new_context()
        page=await context.new_page()
        page.on('request',lambda req: request_urls.append(req.url))
        page.on('console',lambda msg: console_errors.append(msg.text) if msg.type=='error' else None)
        page.on('pageerror',lambda err: page_errors.append(str(err)))
        for width,height in viewports:
            await page.set_viewport_size({'width':width,'height':height})
            await page.set_content(document,wait_until='load')
            await page.wait_for_function('window.__ACE_REVIEW__ !== undefined')
            for state in states:
                await page.evaluate("s=>window.__ACE_REVIEW__.selectState(s,{updateHash:false})",state)
                await page.wait_for_timeout(30)
                data=await page.evaluate('''() => {
                  const panels=[...document.querySelectorAll('[data-state]')];
                  const tabs=[...document.querySelectorAll('[data-state-control]')];
                  const selected=tabs.filter(x=>x.getAttribute('aria-selected')==='true');
                  const visible=panels.filter(x=>!x.hidden);
                  const active=visible[0];
                  const overflow=Math.max(document.documentElement.scrollWidth,document.body.scrollWidth)-innerWidth;
                  const clipped=[...document.querySelectorAll('.visual-state:not([hidden]) h1,.visual-state:not([hidden]) h2,.visual-state:not([hidden]) h3,.visual-state:not([hidden]) p,.visual-state:not([hidden]) span,.visual-state:not([hidden]) dd')].filter(el=>{
                    const s=getComputedStyle(el); if(s.display==='none'||s.visibility==='hidden')return false;
                    return el.scrollWidth>el.clientWidth+3 && s.whiteSpace==='nowrap';
                  }).length;
                  const viewportClipped=active?[active,...active.querySelectorAll('*')].filter(el=>{
                    const s=getComputedStyle(el); if(s.display==='none'||s.visibility==='hidden')return false;
                    const r=el.getBoundingClientRect();
                    return r.left < -0.5 || r.right > innerWidth + 0.5;
                  }).length:0;
                  const mobileBrief=active?.querySelector('.mobile-brief');
                  const mobileStage=active?.querySelector('.mobile-stage');
                  const mobileBriefOverflow=mobileBrief?Math.max(0,mobileBrief.scrollWidth-mobileBrief.clientWidth):0;
                  const mobileStageOverflow=mobileStage?Math.max(0,mobileStage.scrollWidth-mobileStage.clientWidth):0;
                  return {selected:selected.length,visible:visible.length,key:selected[0]?.dataset.stateControl,tab0:tabs.filter(x=>x.tabIndex===0).length,overflow,clipped,viewportClipped,mobileBriefOverflow,mobileStageOverflow};
                }''')
                if data['selected']!=1 or data['visible']!=1 or data['key']!=state or data['tab0']!=1: errors.append(f'state sync {width}x{height} {state}: {data}')
                if data['overflow']>0: errors.append(f'overflow {width}x{height} {state}: {data["overflow"]}')
                if data['clipped']>0: errors.append(f'text clipping {width}x{height} {state}: {data["clipped"]}')
                if data['viewportClipped']>0: errors.append(f'viewport clipping {width}x{height} {state}: {data["viewportClipped"]}')
                if width==390 and state=='mobile' and (data['mobileBriefOverflow']>0 or data['mobileStageOverflow']>0):
                    errors.append(f'mobile container overflow {width}x{height}: brief={data["mobileBriefOverflow"]}, stage={data["mobileStageOverflow"]}')
                combos.append({'viewport':f'{width}x{height}','state':state,**data})
                if width==1440 and state=='cover':
                    await page.screenshot(path='/tmp/ace-cover-1440x1100.jpg',full_page=False,type='jpeg',quality=82)
                if width==390 and state=='mobile':
                    await page.screenshot(path='/tmp/ace-mobile-390x844.jpg',full_page=False,type='jpeg',quality=82)
        await page.set_viewport_size({'width':1440,'height':1100}); await page.set_content(document,wait_until='load')
        await page.locator('[data-state-control="cover"]').focus(); await page.keyboard.press('ArrowRight')
        if await page.locator('[data-state-control="brief"]').get_attribute('aria-selected')!='true': errors.append('ArrowRight navigation failed')
        await page.keyboard.press('End')
        if await page.locator('[data-state-control="mobile"]').get_attribute('aria-selected')!='true': errors.append('End navigation failed')
        await page.keyboard.press('Home')
        if await page.locator('[data-state-control="cover"]').get_attribute('aria-selected')!='true': errors.append('Home navigation failed')
        await page.evaluate("window.__ACE_REVIEW__.selectState('kit',{updateHash:false})")
        await page.locator('[data-motion-replay]').focus(); await page.evaluate('window.scrollTo(0,120)')
        before_focus=await page.evaluate('document.activeElement.matches("[data-motion-replay]")'); before_scroll=await page.evaluate('scrollY')
        async def replay_capture():
            await page.locator('[data-motion-replay]').click()
            running=await page.locator('[data-kit-motion]').get_attribute('data-motion-state')
            await page.wait_for_function("document.querySelector('[data-kit-motion]').dataset.motionState === 'complete'",timeout=3000)
            style=await page.locator('.final-element').evaluate("el=>{const s=getComputedStyle(el);return {opacity:s.opacity,transform:s.transform,display:s.display}}")
            rect=await page.locator('.final-element').bounding_box()
            shot=await page.locator('[data-kit-motion]').screenshot()
            return {'entered_running':running=='running','style':style,'rect':rect,'sha256':hashlib.sha256(shot).hexdigest()}
        r1=await replay_capture(); r2=await replay_capture()
        if not r1['entered_running'] or not r2['entered_running']: errors.append('motion did not enter running state')
        if r1!=r2: errors.append(f'replay equality failed: {r1} != {r2}')
        after_focus=await page.evaluate('document.activeElement.matches("[data-motion-replay]")'); after_scroll=await page.evaluate('scrollY')
        if not before_focus or not after_focus: errors.append('focus stability failed')
        if before_scroll!=after_scroll: errors.append(f'scroll stability failed {before_scroll}!={after_scroll}')
        await page.evaluate('window.scrollTo(0,0)')
        await page.screenshot(path='/tmp/ace-kit-1440x1100.jpg',full_page=False,type='jpeg',quality=82)
        reduced=await browser.new_context(reduced_motion='reduce',viewport={'width':390,'height':844})
        rp=await reduced.new_page(); await rp.set_content(document,wait_until='load'); await rp.evaluate("window.__ACE_REVIEW__.selectState('kit',{updateHash:false})")
        await rp.locator('[data-motion-replay]').click(); await rp.wait_for_timeout(20)
        rms=await rp.locator('[data-kit-motion]').get_attribute('data-motion-state')
        visible_text=await rp.locator('[data-kit-motion]').inner_text()
        if rms!='complete': errors.append('reduced motion not immediately complete')
        for label in ['FACT CHECK NOT PERFORMED','UNSUPPORTED CLAIM — HOLD','STYLE IMITATION PROHIBITED','NOT PUBLISHED']:
            if label not in visible_text: errors.append(f'reduced motion missing retained label: {label}')
        await reduced.close(); await browser.close()
    external=[u for u in request_urls if not (u.startswith('data:') or u.startswith('about:'))]
    result={'status':'PASS' if not errors and not console_errors and not page_errors and not external else 'FAIL','browser_limitation':'file:// and localhost blocked by ERR_BLOCKED_BY_ADMINISTRATOR; deterministic inline fallback used','url_mode':'inline local CSS/JS/assets as data URIs','viewports':[f'{w}x{h}' for w,h in viewports],'combinations':len(combos),'combination_records':combos,'console_errors':console_errors,'page_errors':page_errors,'external_requests':external,'request_count':len(request_urls),'replay_equal':r1==r2,'replay_1':r1,'replay_2':r2,'focus_stable':before_focus and after_focus,'scroll_stable':before_scroll==after_scroll,'reduced_motion_state':rms,'errors':errors,'independent_local_validation':False}
    (ROOT/'evidence/browser-self-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['status']=='PASS' else 1
if __name__=='__main__': sys.exit(asyncio.run(main()))
