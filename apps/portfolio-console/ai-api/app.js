(() => {
  const root = document.documentElement;
  const stage = document.getElementById('stage');
  const cinematic = document.getElementById('cinematic');
  const connect = document.getElementById('connect');
  const connectNote = document.getElementById('connect-note');
  const alone = document.querySelector('.shot-alone');
  const connection = document.querySelector('.shot-connection');
  const close = document.querySelector('.shot-close');
  const field = document.querySelector('.shot-field');
  const vision = document.querySelector('.vision-ring');
  const beam = document.querySelector('.scan-beam');
  const spatial = document.getElementById('spatial');
  const voice = document.getElementById('voice');
  const title = document.getElementById('cinema-title');
  const code = document.querySelector('#code code');
  const deal = (window.B60_DEALS || [])[0];
  let connected = false;
  let typed = false;

  const clamp = (v, a=0, b=1) => Math.max(a, Math.min(b, v));
  const mix = (a,b,t) => a + (b-a)*t;
  const range = (p,a,b) => clamp((p-a)/(b-a));
  const opacity = (el, value) => { el.style.opacity = String(clamp(value)); };

  function localProgress(){
    const top = cinematic.offsetTop;
    const span = cinematic.offsetHeight - innerHeight;
    return span > 0 ? clamp((scrollY - top) / span) : 0;
  }

  function render(){
    const p = localProgress();
    root.style.setProperty('--progress', p.toFixed(4));

    const approach = range(p, 0, .27);
    opacity(alone, 1 - range(p,.25,.38));
    alone.style.transform = `scale(${mix(.92,1.46,approach)}) translate3d(${mix(0,-2.5,approach)}vw,${mix(0,1,approach)}vh,0)`;
    alone.style.filter = `brightness(${mix(.18,.26,approach)}) saturate(${mix(.55,.7,approach)}) contrast(1.17) hue-rotate(180deg)`;

    const coreIn = range(p,.22,.31);
    if (!connected) {
      connect.style.opacity = String(coreIn * (1-range(p,.41,.46)));
      connect.style.transform = `translate(-50%,-50%) scale(${mix(.7,1,coreIn)})`;
      connectNote.style.opacity = String(coreIn*.9);
    }

    if (!connected && p > .36) {
      connect.style.opacity = '1';
      connect.style.transform = 'translate(-50%,-50%) scale(1)';
      connectNote.style.opacity = '1';
      opacity(connection,0); opacity(close,0); opacity(field,0);
      vision.classList.remove('on'); beam.classList.remove('on'); spatial.classList.remove('on'); voice.classList.remove('on'); title.classList.remove('on');
      return;
    }

    if (connected) {
      const active = range(p,.33,.48);
      opacity(connection, active * (1-range(p,.5,.61)));
      connection.style.transform = `scale(${mix(1.07,1.16,active)})`;

      const eye = range(p,.49,.63);
      opacity(close, eye * (1-range(p,.66,.73)));
      close.style.transform = `scale(${mix(1.5,2.35,eye)}) translate3d(${mix(0,-1.5,eye)}vw,0,0)`;
      vision.classList.toggle('on', p>.56 && p<.75);
      beam.classList.toggle('on', p>.6 && p<.75);

      const world = range(p,.69,.8);
      opacity(field, world);
      field.style.transform = `scale(${mix(1.08,1.01,world)})`;
      spatial.classList.toggle('on', p>.72 && p<.91);
      voice.classList.toggle('on', p>.8 && p<.94);
      title.classList.toggle('on', p>.9);
      if (p>.81 && !typed) typeCode();
    }
  }

  connect.addEventListener('click', () => {
    connected = true;
    stage.classList.add('connected');
    connect.style.opacity = '0';
    connect.style.pointerEvents = 'none';
    connectNote.style.opacity = '0';
    flashParticles(innerWidth*.64, innerHeight*.48, 180);
    if (navigator.vibrate) navigator.vibrate([20,28,45]);
    const target = cinematic.offsetTop + (cinematic.offsetHeight-innerHeight)*.39;
    setTimeout(() => scrollTo({top:target,behavior:'smooth'}), 350);
  });

  addEventListener('pointermove', (e) => {
    const mx = (e.clientX/innerWidth-.5)*2;
    const my = (e.clientY/innerHeight-.5)*2;
    root.style.setProperty('--mx',mx.toFixed(3)); root.style.setProperty('--my',my.toFixed(3));
    document.querySelectorAll('.surface').forEach((el) => {
      if (el.dataset.dragging === 'true') return;
      const d = Number(el.dataset.depth || 0);
      const x = mx * 23 * d, y = my * 14 * d;
      const base = el.classList.contains('surface-model') ? 'rotateY(13deg) rotateZ(-2deg)' : el.classList.contains('surface-route') ? 'rotateY(-12deg) rotateZ(2deg)' : 'rotateY(-9deg) rotateZ(-3deg)';
      el.style.transform = `${base} translate3d(${x}px,${y}px,${d*38}px)`;
    });
  }, {passive:true});

  document.querySelectorAll('.surface').forEach((surface) => {
    let startX=0,startY=0,baseX=0,baseY=0;
    surface.addEventListener('pointerdown', (e) => {
      surface.dataset.dragging='true'; surface.setPointerCapture(e.pointerId);
      startX=e.clientX; startY=e.clientY; baseX=Number(surface.dataset.x||0); baseY=Number(surface.dataset.y||0);
    });
    surface.addEventListener('pointermove', (e) => {
      if(surface.dataset.dragging!=='true') return;
      const x=baseX+e.clientX-startX, y=baseY+e.clientY-startY;
      surface.dataset.x=x; surface.dataset.y=y;
      surface.style.transform=`translate3d(${x}px,${y}px,70px) scale(1.03)`;
    });
    const stop=()=>surface.dataset.dragging='false';
    surface.addEventListener('pointerup',stop); surface.addEventListener('pointercancel',stop);
  });

  function typeCode(){
    typed=true;
    const text = `intent = "build secure login API"\nroute = ai_api.find_access(strategy="lowest_cost")\nmodel = route.model\n\nresult = model.generate(intent)\nverify(result)\n\n✓ access discovered\n✓ route selected\n✓ code ready`;
    let i=0; code.textContent='';
    const tick=()=>{ if(i<=text.length){ code.textContent=text.slice(0,i++); setTimeout(tick,i<55?18:9); } };
    tick();
  }

  addEventListener('scroll', render, {passive:true});
  addEventListener('resize', render, {passive:true});

  if (deal) {
    document.getElementById('deal-headline').textContent=deal.headline;
    document.getElementById('deal-claim').textContent=deal.promoClaim;
    const facts=document.getElementById('verified-facts');
    const labels=['VERIFIED','MODEL ID','CONTEXT','PRICE','FREE CREDIT'];
    deal.verifiedFacts.forEach((fact,index)=>{
      const row=document.createElement('div'); const dt=document.createElement('dt'); const dd=document.createElement('dd');
      dt.textContent=labels[index] || 'FACT'; dd.textContent=fact; row.append(dt,dd); facts.appendChild(row);
    });
    document.getElementById('source-note').textContent=deal.note;
    const modelLink=document.getElementById('official-link'); modelLink.href=deal.officialModelUrl;
    const fxLink=document.getElementById('fx-link'); fxLink.href=deal.officialFxUrl;
  }
  document.getElementById('reveal-source').addEventListener('click',()=>document.getElementById('source').scrollIntoView({behavior:'smooth'}));

  const canvas=document.getElementById('particles'); const ctx=canvas.getContext('2d'); let W=0,H=0,dpr=1; const sparks=[]; const stars=[];
  function resizeCanvas(){ dpr=Math.min(devicePixelRatio||1,2); W=innerWidth; H=innerHeight; canvas.width=W*dpr; canvas.height=H*dpr; canvas.style.width=W+'px'; canvas.style.height=H+'px'; ctx.setTransform(dpr,0,0,dpr,0,0); if(!stars.length){ for(let i=0;i<150;i++) stars.push({x:Math.random(),y:Math.random(),z:.2+Math.random()*.8}); } }
  function flashParticles(x,y,count){ for(let i=0;i<count;i++){ const a=Math.random()*Math.PI*2, s=1+Math.random()*5.5; sparks.push({x,y,vx:Math.cos(a)*s,vy:Math.sin(a)*s,life:1,r:.5+Math.random()*1.8}); } }
  function animate(){ ctx.clearRect(0,0,W,H); stars.forEach(s=>{ctx.globalAlpha=.12+s.z*.55;ctx.fillStyle='#dffcff';ctx.beginPath();ctx.arc(s.x*W,s.y*H,.45+s.z*1.1,0,Math.PI*2);ctx.fill()}); ctx.globalCompositeOperation='lighter'; for(let i=sparks.length-1;i>=0;i--){const q=sparks[i];q.x+=q.vx;q.y+=q.vy;q.vx*=.986;q.vy*=.986;q.life-=.018;if(q.life<=0){sparks.splice(i,1);continue}ctx.globalAlpha=q.life;ctx.fillStyle='#91f7ff';ctx.shadowColor='#79eaff';ctx.shadowBlur=12;ctx.beginPath();ctx.arc(q.x,q.y,q.r,0,Math.PI*2);ctx.fill()}ctx.shadowBlur=0;ctx.globalCompositeOperation='source-over';ctx.globalAlpha=1;requestAnimationFrame(animate)}
  resizeCanvas(); addEventListener('resize',resizeCanvas); animate(); render();
})();
