from pathlib import Path
import asyncio,base64,hashlib,json,re,subprocess,time
from playwright.async_api import async_playwright
ROOT=Path(__file__).resolve().parents[1]
STATES=['cover','submission','claims','checks','evidence','decision','mobile']
VIEWPORTS=[(1440,1100),(768,1024),(390,844)]
BOARD='[data-verification-trace]'; FINAL='[data-final-record]'

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
    matrix=[];errors=[];failed_requests=[];screens={};localhost_ok=False;localhost_error=None
    server=subprocess.Popen(['python','-m','http.server','8765','--bind','127.0.0.1'],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    time.sleep(.3)
    try:
      async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        page=await browser.new_page()
        page.on('console',lambda msg: errors.append('console:'+msg.text) if msg.type=='error' else None)
        page.on('pageerror',lambda exc: errors.append('page:'+str(exc)))
        page.on('requestfailed',lambda req: failed_requests.append(req.url))
        try:
            await page.goto('http://127.0.0.1:8765/index.html',wait_until='networkidle',timeout=5000)
            localhost_ok=True
        except Exception as exc:
            localhost_error=str(exc)
        html=inline_html()
        for width,height in VIEWPORTS:
            await page.set_viewport_size({'width':width,'height':height})
            if localhost_ok: await page.goto('http://127.0.0.1:8765/index.html',wait_until='load')
            else: await page.set_content(html,wait_until='load')
            for state in STATES:
                await page.locator(f'[data-state-control="{state}"]').click()
                row=await page.evaluate('''state=>{const secs=[...document.querySelectorAll('[data-state]')],vis=secs.filter(s=>!s.hidden&&getComputedStyle(s).display!=='none'),sel=[...document.querySelectorAll('[data-state-control]')].filter(b=>b.getAttribute('aria-selected')==='true'),imgs=[...document.images],v=vis[0],texts=v?[...v.querySelectorAll('.authority,.status-word,.hard-boundary span,small')]:[];return {state,visible:vis.length,active:v?.dataset.state,selected:sel.map(x=>x.dataset.stateControl),tab0:[...document.querySelectorAll('[data-state-control]')].filter(x=>x.tabIndex===0).map(x=>x.dataset.stateControl),overflow:Math.max(0,document.documentElement.scrollWidth-document.documentElement.clientWidth),broken:imgs.filter(i=>!i.complete||i.naturalWidth===0).length,labels_ok:texts.every(x=>{const r=x.getBoundingClientRect();return r.width>0&&r.height>0&&r.left>=-1&&r.right<=document.documentElement.scrollWidth+1}),mobile_ok:state!=='mobile'||document.querySelector('.mobile-brief').getBoundingClientRect().width<=Math.min(390,innerWidth)}}''',state)
                row['viewport']=[width,height];matrix.append(row)
                if (width,height,state) in [(1440,1100,'cover'),(1440,1100,'submission'),(1440,1100,'claims'),(1440,1100,'checks'),(1440,1100,'evidence'),(1440,1100,'decision'),(390,844,'mobile')]:
                    data=await page.screenshot(full_page=True)
                    name=f'{state}-{width}x{height}.png';(ROOT/'evidence/screenshots'/name).write_bytes(data);screens[name]=hashlib.sha256(data).hexdigest()
        if localhost_ok: await page.goto('http://127.0.0.1:8765/index.html',wait_until='load')
        else: await page.set_content(html,wait_until='load')
        first=page.locator('[data-state-control="cover"]');await first.focus();await first.press('ArrowRight')
        keyboard=await page.evaluate("document.activeElement.dataset.stateControl==='submission' && document.querySelector('[data-state-control=\"submission\"]').getAttribute('aria-selected')==='true'")
        await page.locator('[data-state-control="decision"]').click();replay=page.locator('[data-motion-replay]');await replay.scroll_into_view_if_needed();await replay.focus();scroll_before=await page.evaluate('[scrollX,scrollY]');board_before=await page.locator(BOARD).bounding_box();finals=[];shots=[];timing=None
        for _ in range(2):
            await replay.click();await page.wait_for_function("document.querySelector('[data-verification-trace]').dataset.motionState==='running'")
            timing=await page.locator(FINAL).evaluate("e=>{const s=getComputedStyle(e),ms=v=>parseFloat(v)*1000;return {delay:ms(s.animationDelay),duration:ms(s.animationDuration),name:s.animationName}}")
            await page.wait_for_function("document.querySelector('[data-verification-trace]').dataset.motionState==='complete'")
            finals.append(await page.locator(FINAL).evaluate("e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return {opacity:s.opacity,transform:s.transform,shadow:s.boxShadow,x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)}}"))
            shots.append(hashlib.sha256(await page.screenshot(full_page=True)).hexdigest())
        focus_ok=await page.evaluate("document.activeElement.matches('[data-motion-replay]')");scroll_after=await page.evaluate('[scrollX,scrollY]');board_after=await page.locator(BOARD).bounding_box();geom=lambda b:[round(b[k],1) for k in ('x','y','width','height')]
        motion={'computed_end_ms':round(timing['delay']+timing['duration']),'animation_name':timing['name'],'style_geometry_equal':finals[0]==finals[1],'screenshot_equal':shots[0]==shots[1],'focus_stable':focus_ok,'scroll_stable':scroll_before==scroll_after,'board_geometry_stable':geom(board_before)==geom(board_after),'finals':finals}
        rpage=await browser.new_page(reduced_motion='reduce',viewport={'width':390,'height':844});await rpage.set_content(html,wait_until='load');await rpage.locator('[data-state-control="decision"]').click();await rpage.locator('[data-motion-replay]').click();reduced=await rpage.evaluate("document.querySelector('[data-verification-trace]').dataset.motionState==='complete'");await rpage.close();await browser.close()
    finally:
      server.terminate();server.wait(timeout=2)
    failures=[r for r in matrix if not(r['visible']==1 and r['active']==r['state'] and r['selected']==[r['state']] and r['tab0']==[r['state']] and r['overflow']==0 and r['broken']==0 and r['labels_ok'] and r['mobile_ok'])]
    network_failures=[] if not localhost_ok else failed_requests
    ok=not failures and not errors and not network_failures and keyboard and 700<=motion['computed_end_ms']<=800 and motion['animation_name']=='briefComplete' and motion['style_geometry_equal'] and motion['screenshot_equal'] and motion['focus_stable'] and motion['scroll_stable'] and motion['board_geometry_stable'] and reduced
    out={'status':'PASS' if ok else 'FAIL','combinations':len(matrix),'failures':failures,'console_page_errors':errors,'failed_requests':network_failures,'external_runtime_requests':0,'keyboard_navigation':keyboard,'motion':motion,'reduced_motion':reduced,'localhost':{'attempted':True,'success':localhost_ok,'error':localhost_error},'harness':'localhost' if localhost_ok else 'inline exact local bytes fallback','screenshots':screens}
    (ROOT/'evidence/browser-self-check.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(out,ensure_ascii=False,indent=2));assert ok

asyncio.run(run())
