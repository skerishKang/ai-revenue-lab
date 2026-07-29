from __future__ import annotations
import base64,json,re
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
STATES=['cover','work-order','roles','evidence','gates','decision','mobile']
VIEWS=[(1440,1100),(768,1024),(390,844)]
TOKEN='20260729-b42-1'
BEFORE={'cover@768x1024':175,'work-order@768x1024':15,'cover@390x844':538,'work-order@390x844':378}

def inline():
 h=(ROOT/'index.html').read_text(); m=(ROOT/'styles/main.css').read_text(); m=re.sub(r'@import[^;]+;','',m)
 css=''.join((ROOT/'styles'/n).read_text() for n in ('layout.css','responsive.css'))+m
 h=re.sub(r'<link rel="stylesheet" href="styles/main\.css\?v=[^"]+">',f'<style>{css}</style>',h,1)
 h=re.sub(r'<script src="scripts/review\.js\?v=[^"]+"></script>',f'<script>{(ROOT/"scripts/review.js").read_text()}</script>',h,1)
 for p in (ROOT/'assets/images').glob('*.svg'):
  h=h.replace(f'assets/images/{p.name}?v={TOKEN}','data:image/svg+xml;base64,'+base64.b64encode(p.read_bytes()).decode())
 return h

def metric(page,state):
 return page.evaluate("""s=>{const p=document.querySelector('#state-'+s),tabs=[...document.querySelectorAll('[role=tab]')],panels=[...document.querySelectorAll('[role=tabpanel]')],vis=e=>{const c=getComputedStyle(e),r=e.getBoundingClientRect();return c.display!='none'&&c.visibility!='hidden'&&r.width>0&&r.height>0},texts=[...document.querySelectorAll('h1,h2,h3,p,span,strong,b,small,code,dt,dd,li,time,output')].filter(vis).filter(e=>!e.closest('.state-tabs')),clip=texts.filter(e=>{const c=getComputedStyle(e),hide=['hidden','clip'].includes(c.overflowX)||['hidden','clip'].includes(c.overflowY);return hide&&(e.scrollWidth>e.clientWidth+3||e.scrollHeight>e.clientHeight+3)}),ls=[...document.querySelectorAll('.section-label,.authority-ribbon span,.persistent-stack span,.runtime-boundary strong,.runtime-boundary span')].filter(vis);let ov=0;for(let i=0;i<ls.length;i++)for(let j=i+1;j<ls.length;j++){let a=ls[i],b=ls[j];if(a.contains(b)||b.contains(a))continue;let x=a.getBoundingClientRect(),y=b.getBoundingClientRect();if(Math.min(x.right,y.right)-Math.max(x.left,y.left)>2&&Math.min(x.bottom,y.bottom)-Math.max(x.top,y.top)>2)ov++}let t=tabs.find(x=>x.dataset.state==s);return{selected:t.getAttribute('aria-selected')=='true',one:panels.filter(x=>!x.hidden).length==1,roving:tabs.filter(x=>x.tabIndex==0).length==1&&t.tabIndex==0,overflow:Math.max(document.documentElement.scrollWidth,document.body.scrollWidth)-innerWidth,clipping:clip.length,overlap:ov,assets:[...p.querySelectorAll('img')].every(i=>i.complete&&i.naturalWidth>0)}}""",state)

def motion(page):
 page.click('#tab-decision');page.focus('#replay-control-record');before=page.evaluate("""()=>{let r=document.querySelector('#control-motion').getBoundingClientRect();return[document.activeElement.id,scrollX,scrollY,r.x,r.y,r.width,r.height]}""")
 page.evaluate("""()=>{window.__seal=[];document.querySelector('#control-record-seal').addEventListener('animationend',e=>window.__seal.push(e.animationName))}""")
 reps=[];timing=None
 for _ in range(2):
  page.click('#replay-control-record');timing=timing or page.eval_on_selector('#control-record-seal',"e=>{let a=e.getAnimations()[0],t=a.effect.getTiming();return t.delay+t.duration}")
  page.wait_for_function("document.querySelector('#control-motion').dataset.motionState=='complete'",timeout=3000)
  reps.append(page.eval_on_selector('#control-record-seal',"e=>{let s=getComputedStyle(e);return[s.opacity,s.transform,s.backgroundColor]}"))
 after=page.evaluate("""()=>{let r=document.querySelector('#control-motion').getBoundingClientRect();return[document.activeElement.id,scrollX,scrollY,r.x,r.y,r.width,r.height]}""")
 return {'equal':reps[0]==reps[1],'stable':all(abs(a-b)<.1 if isinstance(a,(int,float)) else a==b for a,b in zip(before,after)),'animationend':page.evaluate("window.__seal.filter(x=>x=='controlSeal').length>=2"),'ms':round(timing)}

def main():
 out={'result':'RESPONSIVE_FIX_SELF_CHECK_PASS','mode':'inline-exact-bytes-fallback','previous_exact_head':'b5e78827dd87ff78aca4ac4a65565c6c2b2aff76','before_overflow_px':BEFORE,'matrix':{},'targeted':{},'failed':[]}
 with sync_playwright() as pw:
  b=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
  for w,h in VIEWS:
   p=b.new_page(viewport={'width':w,'height':h});errs=[];req=[];p.on('console',lambda m:errs.append(m.text) if m.type=='error' else None);p.on('pageerror',lambda e:errs.append(str(e)));p.on('requestfailed',lambda r:req.append(r.url));p.set_content(inline(),wait_until='load');k=f'{w}x{h}';out['matrix'][k]={}
   for s in STATES:
    p.click('#tab-'+s);m=metric(p,s);out['matrix'][k][s]=m
    if s in ('cover','work-order') and w in (768,390):out['targeted'][f'{s}@{k}']={x:m[x] for x in ('overflow','clipping','overlap')}
    if not(m['selected'] and m['one'] and m['roving'] and m['overflow']==m['clipping']==m['overlap']==0 and m['assets']):out['failed'].append(f'{k}:{s}')
   p.click('#tab-cover');p.focus('#tab-cover');p.keyboard.press('ArrowRight');f=p.evaluate("""()=>{let e=document.activeElement,s=getComputedStyle(e);return[e.id,e.getAttribute('aria-selected'),s.outlineStyle,s.outlineWidth]}""");out['matrix'][k]['focus']=f
   if not(f[0]=='tab-work-order' and f[1]=='true' and f[2]!='none' and float(f[3][:-2])>=3):out['failed'].append(f'{k}:focus')
   mm=motion(p);out['matrix'][k]['motion']=mm
   if not(mm['equal'] and mm['stable'] and mm['animationend'] and mm['ms']==790):out['failed'].append(f'{k}:motion')
   if errs or req:out['failed'].append(f'{k}:errors')
   p.close()
  r=b.new_page(viewport={'width':390,'height':844},reduced_motion='reduce');r.set_content(inline());r.click('#tab-decision');r.click('#replay-control-record');txt=r.locator('body').inner_text();out['reduced']={'complete':r.locator('#control-motion').get_attribute('data-motion-state')=='complete','boundaries':all(x in txt for x in ['STALE EVIDENCE — DO NOT USE','BLOCKER','UX NOT AUTHORIZED','BACKEND FROZEN','MERGEABLE ≠ MERGE AUTHORIZED','DEPLOYMENT AUTHORIZED — NOT EXECUTED'])};b.close()
 if out['failed'] or not all(out['reduced'].values()):out['result']='RESPONSIVE_FIX_SELF_CHECK_FAIL'
 (ROOT/'evidence/responsive-fix-self-check.json').write_text(json.dumps(out,ensure_ascii=False,indent=2));print(json.dumps({'result':out['result'],'failed':out['failed'],'targeted':out['targeted']},ensure_ascii=False,indent=2));raise SystemExit(out['result'].endswith('FAIL'))
if __name__=='__main__':main()
