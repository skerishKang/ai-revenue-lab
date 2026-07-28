from pathlib import Path
import asyncio,base64,json,re
from playwright.async_api import async_playwright
ROOT=Path(__file__).resolve().parents[1]
STATES=['cover','question','literature','notes','equation','review','mobile']
VPS=[(1440,1100),(768,1024),(390,844)]

def inline_document():
    html=(ROOT/'index.html').read_text(encoding='utf-8')
    css=(ROOT/'styles/main.css').read_text(encoding='utf-8')
    js=(ROOT/'scripts/review.js').read_text(encoding='utf-8')
    html=re.sub(r'<link rel="stylesheet"[^>]+>',f'<style>{css}</style>',html)
    html=re.sub(r'<script src="scripts/review\.js[^>]*></script>',f'<script>{js}</script>',html)
    def repl(m):
        raw=m.group(1).split('?')[0]
        data=(ROOT/raw).read_bytes()
        return 'src="data:image/svg+xml;base64,'+base64.b64encode(data).decode()+'"'
    html=re.sub(r'src="(assets/images/[^"]+\.svg(?:\?[^\"]*)?)"',repl,html)
    return html

async def main():
    doc=inline_document()
    report={'status':'PASS','matrix':[],'console_errors':0,'page_errors':0,'failed_requests':0,'external_runtime_requests':0}
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
        for width,height in VPS:
            page=await browser.new_page(viewport={'width':width,'height':height})
            console=[];page_errors=[];failed=[];external=[]
            page.on('console',lambda msg: console.append(msg.text) if msg.type=='error' else None)
            page.on('pageerror',lambda exc: page_errors.append(str(exc)))
            page.on('requestfailed',lambda req: failed.append(req.url))
            page.on('request',lambda req: external.append(req.url) if not req.url.startswith('data:') else None)
            await page.set_content(doc,wait_until='load')
            await page.wait_for_timeout(80)
            for state in STATES:
                await page.click(f'[data-state-control="{state}"]')
                await page.wait_for_timeout(25)
                item=await page.evaluate("""(state)=>{const visible=[...document.querySelectorAll('[data-state]')].filter(x=>!x.hidden),selected=document.querySelector('[data-state-control][aria-selected="true"]'),doc=document.documentElement,imgs=[...document.images],bad=imgs.filter(i=>!i.complete||i.naturalWidth===0).length,labels=[...document.querySelectorAll('.authority')],labelsOk=!labels.some(el=>{const r=el.getBoundingClientRect();return r.right>innerWidth+1||r.left<-1}),eq=document.querySelector('[data-state="equation"]');let eqOk=true;if(state==='equation'){const r=eq.getBoundingClientRect();eqOk=r.left>=-1&&r.right<=innerWidth+1}return{visible:visible.length,selected:selected?.dataset.stateControl,overflow:Math.max(0,doc.scrollWidth-innerWidth),broken:bad,labels_ok:labelsOk,equation_contained:eqOk}}""",state)
                item.update({'viewport':[width,height],'state':state})
                report['matrix'].append(item)
            await page.focus('[data-state-control="cover"]')
            await page.keyboard.press('ArrowRight')
            keyboard=await page.get_attribute('[data-state-control="question"]','aria-selected')
            await page.click('[data-state-control="review"]')
            await page.evaluate('window.scrollTo(0,220)')
            await page.focus('[data-motion-replay]')
            before=await page.evaluate("""()=>{const b=document.querySelector('[data-memory-trace]').getBoundingClientRect();return{scrollY,active:document.activeElement?.hasAttribute('data-motion-replay'),rect:[b.x,b.y,b.width,b.height]}}""")
            async def run_once():
                await page.evaluate("document.querySelector('[data-motion-replay]').click()")
                running_timing=await page.evaluate("""()=>{const s=getComputedStyle(document.querySelector('.memory-seal')),ms=v=>v.endsWith('ms')?parseFloat(v):parseFloat(v)*1000;return{d:ms(s.animationDelay),u:ms(s.animationDuration)}}""")
                await page.wait_for_function("document.querySelector('[data-memory-trace]').dataset.motionState==='complete'",timeout=2000)
                styles=await page.evaluate("""()=>{const get=s=>{const c=getComputedStyle(document.querySelector(s));return[c.opacity,c.transform]};return{seal:get('.memory-seal'),objection:get('.node-objection'),unresolved:get('.node-unresolved')}}""")
                return styles,running_timing
            one,timing=await run_once();two,_=await run_once()
            after=await page.evaluate("""()=>{const b=document.querySelector('[data-memory-trace]').getBoundingClientRect();return{scrollY,active:document.activeElement?.hasAttribute('data-motion-replay'),rect:[b.x,b.y,b.width,b.height]}}""")
            await page.emulate_media(reduced_motion='reduce')
            await page.evaluate("document.querySelector('[data-motion-replay]').click()")
            await page.wait_for_timeout(25)
            reduced=await page.evaluate("""()=>({state:document.querySelector('[data-memory-trace]').dataset.motionState,seal:getComputedStyle(document.querySelector('.memory-seal')).opacity,objection:getComputedStyle(document.querySelector('.node-objection')).opacity,unresolved:getComputedStyle(document.querySelector('.node-unresolved')).opacity})""")
            report.setdefault('keyboard_navigation',keyboard=='true')
            report.setdefault('motion',{'computed_end_ms':timing['d']+timing['u'],'replay_equal':one==two,'focus_scroll_geometry_stable':before==after})
            report.setdefault('reduced_motion',{'state':reduced['state'],'complete':all(float(reduced[k])>.99 for k in ('seal','objection','unresolved'))})
            report['console_errors']+=len(console);report['page_errors']+=len(page_errors);report['failed_requests']+=len(failed);report['external_runtime_requests']+=len(external)
            await page.close()
        await browser.close()
    ok=all(x['visible']==1 and x['selected']==x['state'] and x['overflow']==0 and x['broken']==0 and x['labels_ok'] and x['equation_contained'] for x in report['matrix'])
    report['status']='PASS' if ok and not any(report[k] for k in ('console_errors','page_errors','failed_requests','external_runtime_requests')) and report['keyboard_navigation'] and 700<=report['motion']['computed_end_ms']<=800 and report['motion']['replay_equal'] and report['motion']['focus_scroll_geometry_stable'] and report['reduced_motion']['state']=='complete' and report['reduced_motion']['complete'] else 'FAIL'
    (ROOT/'evidence/browser-self-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(asyncio.run(main()))
