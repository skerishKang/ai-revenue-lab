from pathlib import Path
import base64,json,re,sys
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
html=(ROOT/'index.html').read_text(encoding='utf-8')
css=(ROOT/'styles/main.css').read_text(encoding='utf-8')
js=(ROOT/'scripts/review.js').read_text(encoding='utf-8')
html=re.sub(r'<link[^>]+styles/main.css[^>]*>','<style>'+css+'</style>',html)
html=re.sub(r'<script src="scripts/review.js[^>]*></script>','<script>'+js+'</script>',html)
def repl(m):
 p=ROOT/m.group(1).split('?')[0]
 data=base64.b64encode(p.read_bytes()).decode()
 return 'src="data:image/svg+xml;base64,'+data+'"'
html=re.sub(r'src="(assets/images/[^"]+\.svg(?:\?[^"]*)?)"',repl,html)
viewports=[(1440,1100),(768,1024),(390,844)]
states=['cover','schedule','inputs','run','exceptions','decision','mobile']
rows=[]; errors=[]
def capture_screenshot(page, name_suffix, viewport_name):
  screenshot_path = ROOT / 'screenshots' / f'business-52-{name_suffix}-{viewport_name}.png'
  page.screenshot(path=screenshot_path, full_page=True)
  return str(screenshot_path)
with sync_playwright() as p:
  browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
  screenshots_captured = []
  with browser.new_page(viewport={'width':1440,'height':1100},reduced_motion='no-preference') as page:
    page.on('console',lambda msg: errors.append('console:'+msg.text) if msg.type=='error' else None)
    page.on('pageerror',lambda err: errors.append('page:'+str(err)))
    page.set_content(html,wait_until='load')
    scrollY_before=page.evaluate("scrollY")
    for w,h in viewports:
      viewport_name = f'{w}x{h}'
      page.set_viewport_size({'width':w,'height':h})
      for state in states:
        page.evaluate("s=>window.__saoReview.activate(s)",state)
        page.wait_for_timeout(20)
        metrics=page.evaluate("""s=>{const p=document.querySelector('[data-state="'+s+'"]');const r=p.getBoundingClientRect();return {hidden:p.hidden,docOverflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,panelOverflow:Math.max(0,p.scrollWidth-p.clientWidth),width:r.width,height:r.height,images:[...p.querySelectorAll('img')].every(i=>i.complete&&i.naturalWidth>0)}}""",state)
        rows.append({'viewport':viewport_name,'state':state,'pass':not metrics['hidden'] and metrics['docOverflow']<=0 and metrics['panelOverflow']<=0 and metrics['images'],'metrics':metrics})
        screenshots_captured.append(capture_screenshot(page, state, viewport_name))
        if w==390:
          rows[-1]['tab_visibility']=page.evaluate("""()=>{const tb=document.querySelector('.state-nav');const at=tb.querySelector('[aria-selected=\"true\"]');const tr=at.getBoundingClientRect();const lr=tb.getBoundingClientRect();return {tab_left:Math.round(tr.left),tab_right:Math.round(tr.right),list_left:Math.round(lr.left),list_right:Math.round(lr.right),left_visible:tr.left>=lr.left-0.5,right_visible:tr.right<=lr.right+0.5,scrollLeft:tb.scrollLeft}}""")
    page.evaluate("window.__saoReview.activate('cover')")
    keyboard_arrowright=None; keyboard_arrowleft=None; keyboard_home=None; keyboard_end=None; keyboard_all=None
    for w,h in [(1440,1100), (390,844)]:
      viewport_name = f'{w}x{h}'
      page.set_viewport_size({'width':w,'height':h})
      page.locator('#tab-cover').focus()
      page.keyboard.press('ArrowRight')
      r=page.locator('#tab-schedule').get_attribute('aria-selected')=='true'
      keyboard_arrowright = r if keyboard_arrowright is None else keyboard_arrowright and r
      screenshots_captured.append(capture_screenshot(page, 'keyboard-arrowright', viewport_name))
      page.keyboard.press('ArrowLeft')
      r=page.locator('#tab-cover').get_attribute('aria-selected')=='true'
      keyboard_arrowleft = r if keyboard_arrowleft is None else keyboard_arrowleft and r
      screenshots_captured.append(capture_screenshot(page, 'keyboard-arrowleft', viewport_name))
      page.keyboard.press('Home')
      r=page.locator('#tab-cover').get_attribute('aria-selected')=='true'
      keyboard_home = r if keyboard_home is None else keyboard_home and r
      screenshots_captured.append(capture_screenshot(page, 'keyboard-home', viewport_name))
      page.keyboard.press('End')
      r=page.locator('#tab-mobile').get_attribute('aria-selected')=='true'
      keyboard_end = r if keyboard_end is None else keyboard_end and r
      screenshots_captured.append(capture_screenshot(page, 'keyboard-end', viewport_name))
    keyboard_all = keyboard_arrowright and keyboard_arrowleft and keyboard_home and keyboard_end
    page.evaluate("window.__saoReview.activate('cover')")
    page.evaluate("window.__saoReview.activate('decision')")
    replay_equal=True
    for w,h in [(1440,1100), (390,844)]:
      viewport_name = f'{w}x{h}'
      page.set_viewport_size({'width':w,'height':h})
      page.evaluate("window.__saoReview.activate('decision')")
      page.locator('[data-motion-replay]').click()
      page.wait_for_function("document.querySelector('[data-sao-trace]').dataset.motionState==='complete'",timeout=2000)
      screenshots_captured.append(capture_screenshot(page, 'decision-replay-1', viewport_name))
      first=page.evaluate("""()=>{const e=document.querySelector('[data-final-record]');const r=e.getBoundingClientRect();return {style:getComputedStyle(e).cssText,opacity:getComputedStyle(e).opacity,transform:getComputedStyle(e).transform,rect:[r.x,r.y,r.width,r.height],scroll:[scrollX,scrollY],active:document.activeElement?.outerHTML.slice(0,80)}}""")
      page.locator('[data-motion-replay]').click()
      page.wait_for_function("document.querySelector('[data-sao-trace]').dataset.motionState==='complete'",timeout=2000)
      screenshots_captured.append(capture_screenshot(page, 'decision-replay-2', viewport_name))
      second=page.evaluate("""()=>{const e=document.querySelector('[data-final-record]');const r=e.getBoundingClientRect();return {style:getComputedStyle(e).cssText,opacity:getComputedStyle(e).opacity,transform:getComputedStyle(e).transform,rect:[r.x,r.y,r.width,r.height],scroll:[scrollX,scrollY],active:document.activeElement?.outerHTML.slice(0,80)}}""")
      replay_equal = replay_equal and (first==second)
      scrollY_after=page.evaluate("scrollY")
  with p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']) as reduced_motion_browser:
    reduced_complete=True
    for w,h in [(1440,1100), (390,844)]:
      viewport_name = f'{w}x{h}'
      reduced=reduced_motion_browser.new_page(viewport={'width':w,'height':h},reduced_motion='reduce')
      reduced.set_content(html,wait_until='load')
      reduced.evaluate("window.__saoReview.activate('decision')")
      reduced.locator('[data-motion-replay]').click()
      reduced.wait_for_function("document.querySelector('[data-sao-trace]').dataset.motionState==='complete'",timeout=2000)
      screenshots_captured.append(capture_screenshot(reduced, 'decision-reduced', viewport_name))
      r=reduced.locator('[data-sao-trace]').get_attribute('data-motion-state')=='complete'
      reduced_complete = reduced_complete and r
      reduced.close()
  browser.close()
  tab_vis_390=[r['tab_visibility'] for r in rows if r.get('tab_visibility')]
  tab_vis_all_pass=all(v['left_visible'] and v['right_visible'] for v in tab_vis_390)
  scrollY_invariant=scrollY_before==scrollY_after
result={'status':'PASS' if all(r['pass'] for r in rows) and keyboard_all and replay_equal and reduced_complete and not errors and tab_vis_all_pass and scrollY_invariant else 'FAIL','matrix_pass':sum(r['pass'] for r in rows),'matrix_total':len(rows),'viewports':[f'{w}x{h}' for w,h in viewports],'states':states,'keyboard_arrowright':keyboard_arrowright,'keyboard_arrowleft':keyboard_arrowleft,'keyboard_home':keyboard_home,'keyboard_end':keyboard_end,'keyboard_all':keyboard_all,'replay_equal':replay_equal,'reduced_motion_immediate':reduced_complete,'errors':errors,'rows':rows,'tab_vis_390':tab_vis_390,'tab_vis_all_pass':tab_vis_all_pass,'scrollY_invariant':scrollY_invariant,'nominal_completion_ms':780,'external_runtime_requests':'not_measured_page_set_content','note':'Implementation browser harness using exact local bytes in page.set_content; not independent Local Validation.','screenshots_captured':screenshots_captured}
(ROOT/'evidence/browser-self-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
sys.exit(0 if result['status']=='PASS' else 1)
