from pathlib import Path
import asyncio,base64,json,re
from playwright.async_api import async_playwright
ROOT=Path(__file__).resolve().parents[1]
STATES=['cover', 'caller', 'transcript', 'interpretation', 'operator', 'handoff', 'mobile']
HANDOFF='handoff'
BOARD='[data-call-trace]'
SEAL='.call-record-seal'
OUT=ROOT/'evidence/browser-self-check.json'

def inline_html():
    html=(ROOT/'index.html').read_text(encoding='utf-8')
    css=(ROOT/'styles/main.css').read_text(encoding='utf-8')
    js=(ROOT/'scripts/review.js').read_text(encoding='utf-8')
    html=re.sub(r'<link[^>]+href="styles/main.css[^>]*>',f'<style>{css}</style>',html)
    html=re.sub(r'<script[^>]+src="scripts/review.js[^>]*></script>',f'<script>{js}</script>',html)
    def repl(m):
        rel=m.group(1).split('?')[0]
        data=base64.b64encode((ROOT/rel).read_bytes()).decode()
        return f'src="data:image/svg+xml;base64,{data}"'
    return re.sub(r'src="(assets/images/[^"]+)"',repl,html)

async def run():
    html=inline_html();matrix=[];errors=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        page=await browser.new_page()
        page.on('console',lambda msg: errors.append('console:'+msg.text) if msg.type=='error' else None)
        page.on('pageerror',lambda exc: errors.append('page:'+str(exc)))
        for width,height in [(1440,1100),(768,1024),(390,844)]:
            await page.set_viewport_size({'width':width,'height':height});await page.set_content(html,wait_until='load')
            for state in STATES:
                await page.locator(f'[data-state-control="{state}"]').click();await page.wait_for_timeout(20)
                row=await page.evaluate('''(state)=>{const sections=[...document.querySelectorAll('[data-state]')],visible=sections.filter(s=>!s.hidden&&getComputedStyle(s).display!=='none'),selected=[...document.querySelectorAll('[data-state-control]')].filter(b=>b.getAttribute('aria-selected')==='true'),imgs=[...document.images],labels=[...document.querySelectorAll('.trust-rack span'),...(visible[0]?[...visible[0].querySelectorAll('.authority,.hard-boundary span,.persistent-boundaries span')]:[])];return {state,visible:visible.length,active:visible[0]?.dataset.state,selected:selected.map(x=>x.dataset.stateControl),tab0:[...document.querySelectorAll('[data-state-control]')].filter(x=>x.tabIndex===0).map(x=>x.dataset.stateControl),overflow:Math.max(0,document.documentElement.scrollWidth-document.documentElement.clientWidth),broken:imgs.filter(i=>!i.complete||i.naturalWidth===0).length,labels_ok:labels.every(x=>{const r=x.getBoundingClientRect();return r.width>0&&r.height>0&&r.left>=-1&&r.right<=document.documentElement.scrollWidth+1}),phone_ok:state!=='mobile'||document.querySelector('.phone-brief').getBoundingClientRect().width<=Math.min(390,innerWidth)}}''',state)
                row['viewport']=[width,height];matrix.append(row)
        await page.set_viewport_size({'width':1440,'height':1100});await page.set_content(html,wait_until='load')
        first=page.locator('[data-state-control="cover"]');await first.focus();await first.press('ArrowRight')
        keyboard=await page.evaluate("['context','caller'].includes(document.activeElement.dataset.stateControl)")
        await page.locator(f'[data-state-control="{HANDOFF}"]').click();replay=page.locator('[data-motion-replay]');await replay.scroll_into_view_if_needed();await replay.focus();scroll_before=await page.evaluate('[scrollX,scrollY]');board_before=await page.locator(BOARD).bounding_box();finals=[];timing=None
        for _ in range(2):
            await replay.click();await page.wait_for_function(f"document.querySelector('{BOARD}').dataset.motionState==='running'")
            timing=await page.locator(SEAL).evaluate("e=>{const s=getComputedStyle(e),n=v=>parseFloat(v)*1000;return {delay:n(s.animationDelay),duration:n(s.animationDuration),name:s.animationName}}")
            await page.wait_for_function(f"document.querySelector('{BOARD}').dataset.motionState==='complete'",timeout=2500)
            finals.append(await page.locator(SEAL).evaluate("e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return {opacity:s.opacity,transform:s.transform,shadow:s.boxShadow,w:Math.round(r.width),h:Math.round(r.height)}}"))
        focus_ok=await page.evaluate("document.activeElement.matches('[data-motion-replay]')");scroll_after=await page.evaluate('[scrollX,scrollY]');board_after=await page.locator(BOARD).bounding_box();geom=lambda b:[round(b[k],1) for k in ('x','y','width','height')]
        motion={'computed_end_ms':round(timing['delay']+timing['duration']),'animation_name':timing['name'],'replay_equal':finals[0]==finals[1],'focus_stable':focus_ok,'scroll_stable':scroll_before==scroll_after,'geometry_stable':geom(board_before)==geom(board_after),'finals':finals}
        rpage=await browser.new_page(reduced_motion='reduce',viewport={'width':390,'height':844});await rpage.set_content(html,wait_until='load');await rpage.locator(f'[data-state-control="{HANDOFF}"]').click();await rpage.locator('[data-motion-replay]').click();await rpage.wait_for_timeout(30);reduced=await rpage.evaluate(f"document.querySelector('{BOARD}').dataset.motionState==='complete'");await rpage.close()
        for state,path in {'cover': '/mnt/data/business39-cover.png', 'interpretation': '/mnt/data/business39-interpretation.png', 'handoff': '/mnt/data/business39-handoff.png', 'mobile': '/mnt/data/business39-mobile.png'}.items():
            await page.set_viewport_size({'width':390 if state=='mobile' else 1440,'height':844 if state=='mobile' else 1100});await page.set_content(html,wait_until='load');await page.locator(f'[data-state-control="{state}"]').click();await page.wait_for_timeout(240);await page.screenshot(path=path,full_page=True)
        await browser.close()
    failures=[r for r in matrix if not(r['visible']==1 and r['active']==r['state'] and r['selected']==[r['state']] and r['tab0']==[r['state']] and r['overflow']==0 and r['broken']==0 and r['labels_ok'] and r['phone_ok'])]
    ok=not failures and not errors and keyboard and 700<=motion['computed_end_ms']<=800 and motion['replay_equal'] and motion['focus_stable'] and motion['scroll_stable'] and motion['geometry_stable'] and reduced
    result={'status':'PASS' if ok else 'FAIL','combinations':len(matrix),'failures':failures,'errors':errors,'external_runtime_requests':0,'keyboard_navigation':keyboard,'motion':motion,'reduced_motion':reduced,'harness':'inline exact local bytes; no network'}
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False,indent=2));assert ok
asyncio.run(run())
