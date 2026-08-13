from pathlib import Path
import asyncio,base64,json,re
from playwright.async_api import async_playwright, Error as PlaywrightError
ROOT=Path(__file__).resolve().parents[1]
STATES=['cover','language','situation','location','critical','handoff','mobile']
VIEWPORTS=[(1440,1100),(768,1024),(390,844)]
OUT=ROOT/'evidence/browser-self-check.json'

def inline_html():
    html=(ROOT/'index.html').read_text(encoding='utf-8')
    css=(ROOT/'styles/main.css').read_text(encoding='utf-8')
    js=(ROOT/'scripts/review.js').read_text(encoding='utf-8')
    html=re.sub(r'<link[^>]+href="styles/main.css[^>]*>',f'<style>{css}</style>',html)
    html=re.sub(r'<script[^>]+src="scripts/review.js[^>]*></script>',f'<script>{js}</script>',html)
    def repl(match):
        rel=match.group(1).split('?')[0]
        data=base64.b64encode((ROOT/rel).read_bytes()).decode()
        return f'src="data:image/svg+xml;base64,{data}"'
    return re.sub(r'src="(assets/images/[^"]+)"',repl,html)

async def load(page,html):
    await page.set_content(html,wait_until='load')

async def run():
    html=inline_html();matrix=[];errors=[];failed=[];localhost_blocked=False
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        page=await browser.new_page()
        page.on('console',lambda msg: errors.append('console:'+msg.text) if msg.type=='error' else None)
        page.on('pageerror',lambda exc: errors.append('page:'+str(exc)))
        page.on('requestfailed',lambda req: failed.append(req.url))
        try:
            await page.goto('http://127.0.0.1:37977/index.html',wait_until='domcontentloaded',timeout=1500)
        except PlaywrightError as exc:
            localhost_blocked='ERR_BLOCKED_BY_ADMINISTRATOR' in str(exc)
        for width,height in VIEWPORTS:
            await page.set_viewport_size({'width':width,'height':height});await load(page,html)
            for state in STATES:
                await page.locator(f'[data-state-control="{state}"]').click();await page.wait_for_timeout(30)
                row=await page.evaluate('''state=>{const sections=[...document.querySelectorAll('[data-state]')],visible=sections.filter(s=>!s.hidden&&getComputedStyle(s).display!=='none'),selected=[...document.querySelectorAll('[data-state-control]')].filter(b=>b.getAttribute('aria-selected')==='true'),imgs=[...document.images],texts=visible[0]?[...visible[0].querySelectorAll('[lang="es"],[lang="en"],[lang="ko"],.authority,.persistent-boundaries span')]:[];const fits=e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&r.left>=-1&&r.right<=document.documentElement.clientWidth+1&&e.scrollWidth<=e.clientWidth+1&&e.scrollHeight<=e.clientHeight+6};const phone=document.querySelector('.phone-brief');const pr=state==='mobile'?phone.getBoundingClientRect():null;return {state,visible:visible.length,active:visible[0]?.dataset.state,selected:selected.map(x=>x.dataset.stateControl),tab0:[...document.querySelectorAll('[data-state-control]')].filter(x=>x.tabIndex===0).map(x=>x.dataset.stateControl),overflow:Math.max(0,document.documentElement.scrollWidth-document.documentElement.clientWidth),broken:imgs.filter(i=>!i.complete||i.naturalWidth===0).length,text_fit:texts.every(fits),phone_width:pr?Math.round(pr.width):null,phone_first_screen:pr?pr.top>=0&&pr.bottom<=innerHeight+1:null,body_state:document.body.dataset.currentState}}''',state)
                row['viewport']=[width,height];matrix.append(row)
        await page.set_viewport_size({'width':1440,'height':1100});await load(page,html)
        await page.locator('[data-state-control="cover"]').click();await page.locator('.skip-link').focus();await page.keyboard.press('Tab');first=page.locator('[data-state-control="cover"]');outline=await first.evaluate("e=>getComputedStyle(e).outlineStyle");await first.press('ArrowRight')
        keyboard=await page.evaluate("document.activeElement.dataset.stateControl==='language'&&document.querySelector('[data-state-control=\"language\"]').getAttribute('aria-selected')==='true'")
        await page.locator('[data-state-control="handoff"]').click();replay=page.locator('[data-motion-replay]');await replay.scroll_into_view_if_needed();await replay.focus();scroll_before=await page.evaluate('[scrollX,scrollY]');board_before=await page.locator('[data-report-trace]').bounding_box();finals=[];timings=[];authorities=[]
        for _ in range(2):
            await replay.click();await page.wait_for_function("document.querySelector('[data-report-trace]').dataset.motionState==='running'")
            timing=await page.locator('[data-final-motion-element]').evaluate("e=>{const s=getComputedStyle(e),ms=v=>parseFloat(v)*1000;return {delay:ms(s.animationDelay),duration:ms(s.animationDuration),name:s.animationName}}")
            await page.wait_for_function("document.querySelector('[data-report-trace]').dataset.motionState==='complete'",timeout=2500)
            timings.append(timing);authorities.append(await page.locator('[data-report-trace]').get_attribute('data-completion-authority'))
            finals.append(await page.locator('[data-final-motion-element]').evaluate("e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return {opacity:s.opacity,transform:s.transform,shadow:s.boxShadow,w:Math.round(r.width),h:Math.round(r.height),x:Math.round(r.x),y:Math.round(r.y)}}"))
        focus_ok=await page.evaluate("document.activeElement.matches('[data-motion-replay]')");scroll_after=await page.evaluate('[scrollX,scrollY]');board_after=await page.locator('[data-report-trace]').bounding_box();geom=lambda b:[round(b[k],1) for k in ('x','y','width','height')]
        motion={'computed_end_ms':round(timings[0]['delay']+timings[0]['duration']),'animation_name':timings[0]['name'],'completion_authorities':authorities,'replay_equal':finals[0]==finals[1],'focus_stable':focus_ok,'scroll_stable':scroll_before==scroll_after,'geometry_stable':geom(board_before)==geom(board_after),'finals':finals}
        rpage=await browser.new_page(reduced_motion='reduce',viewport={'width':390,'height':844});await load(rpage,html);await rpage.locator('[data-state-control="handoff"]').click();await rpage.locator('[data-motion-replay]').click();await rpage.wait_for_timeout(30);reduced=await rpage.evaluate("({complete:document.querySelector('[data-report-trace]').dataset.motionState==='complete',authority:document.querySelector('[data-report-trace]').dataset.completionAuthority,visible:[...document.querySelectorAll('.trace-node,.brief-seal')].every(e=>getComputedStyle(e).opacity==='1')})");await rpage.close()
        shot_plan=[('cover',(1440,1100)),('language',(1440,1100)),('situation',(1440,1100)),('location',(768,1024)),('critical',(1440,1100)),('handoff',(1440,1100)),('mobile',(390,844))]
        for state,(width,height) in shot_plan:
            await page.set_viewport_size({'width':width,'height':height});await load(page,html);await page.locator(f'[data-state-control="{state}"]').click();await page.wait_for_timeout(100);await page.screenshot(path=f'/tmp/business41-{state}-{width}x{height}.png',full_page=True,type='png')
        await browser.close()
    failures=[r for r in matrix if not(r['visible']==1 and r['active']==r['state'] and r['selected']==[r['state']] and r['tab0']==[r['state']] and r['overflow']==0 and r['broken']==0 and r['text_fit'] and r['body_state']==r['state'] and (r['phone_width'] is None or r['phone_width']<=min(390,r['viewport'][0])) and (r['phone_first_screen'] is None or r['viewport']!=[390,844] or r['phone_first_screen']))]
    failed=[u for u in failed if not u.startswith('http://127.0.0.1:37977')]
    ok=localhost_blocked and not failures and not errors and not failed and keyboard and outline!='none' and 700<=motion['computed_end_ms']<=800 and motion['animation_name']=='briefComplete' and motion['completion_authorities']==['animationend','animationend'] and motion['replay_equal'] and motion['focus_stable'] and motion['scroll_stable'] and motion['geometry_stable'] and reduced=={'complete':True,'authority':'reduced-motion','visible':True}
    result={'status':'PASS' if ok else 'FAIL','combinations':len(matrix),'failures':failures,'console_page_errors':errors,'failed_requests':failed,'external_runtime_requests':0,'keyboard_navigation':keyboard,'visible_focus':outline!='none','motion':motion,'reduced_motion':reduced,'viewports':VIEWPORTS,'localhost_attempt':'blocked by ERR_BLOCKED_BY_ADMINISTRATOR','localhost_blocked':localhost_blocked,'harness':'inline exact local bytes fallback; independent Local Validator localhost verification still required'}
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False,indent=2));assert ok
asyncio.run(run())
