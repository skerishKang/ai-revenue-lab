(() => {
  const stage = document.getElementById('stage');
  const connect = document.getElementById('connect');
  const cinematic = document.getElementById('cinematic');
  const cursor = document.getElementById('gesture-cursor');
  if (!stage || !connect || !cinematic || !cursor) return;

  let connected = false;
  const clamp=(v,a=0,b=1)=>Math.max(a,Math.min(b,v));
  const localProgress=()=>{
    const span=cinematic.offsetHeight-innerHeight;
    return span>0?clamp((scrollY-cinematic.offsetTop)/span):0;
  };

  const armContact=()=>{ if (!connected) stage.classList.add('contact-armed'); };
  const disarmContact=()=>{ if (!connected) stage.classList.remove('contact-armed'); };
  connect.addEventListener('pointerenter', armContact);
  connect.addEventListener('pointerleave', disarmContact);
  connect.addEventListener('focus', armContact);
  connect.addEventListener('blur', disarmContact);

  connect.addEventListener('pointerdown',()=>{
    if (!connected) stage.classList.add('contact-strike','camera-impact');
  });
  connect.addEventListener('click',()=>{
    connected=true;
    stage.classList.remove('contact-armed');
    stage.classList.add('contact-strike','camera-impact','world-awake');
    setTimeout(()=>stage.classList.remove('contact-strike'),760);
    setTimeout(()=>stage.classList.remove('camera-impact'),680);
  });

  function updateWorld(){
    const p=localProgress();
    if (p < .70) stage.dataset.world='';
    else if (p < .78) stage.dataset.world='code';
    else if (p < .86) stage.dataset.world='vision';
    else stage.dataset.world='voice';

    stage.classList.toggle('gesture-mode', connected && p > .715 && p < .915);
  }
  addEventListener('scroll',updateWorld,{passive:true});
  addEventListener('resize',updateWorld,{passive:true});

  addEventListener('pointermove',(e)=>{
    cursor.style.left=e.clientX+'px';
    cursor.style.top=e.clientY+'px';
    if (stage.classList.contains('gesture-mode')) {
      stage.style.setProperty('--world-y', `${(e.clientX/innerWidth-.5)*3.8}deg`);
      stage.style.setProperty('--world-x', `${-(e.clientY/innerHeight-.5)*2.6}deg`);
    }
  },{passive:true});

  // app.js remains the sole drag owner. This layer only samples its drag velocity
  // and continues the surface with inertia after app.js releases pointer capture.
  document.querySelectorAll('.surface').forEach(surface=>{
    let lx=0,ly=0,lt=0,vx=0,vy=0,raf=0;

    const apply=(x,y)=>{
      surface.dataset.x=String(x);
      surface.dataset.y=String(y);
      surface.style.transform=`translate3d(${x}px,${y}px,90px) rotateY(${clamp(vx*.05,-8,8)}deg) rotateX(${clamp(-vy*.035,-6,6)}deg) scale(1.035)`;
    };
    const coast=()=>{
      let x=Number(surface.dataset.x||0);
      let y=Number(surface.dataset.y||0);
      x+=vx; y+=vy; vx*=.92; vy*=.92;
      apply(x,y);
      if(Math.abs(vx)+Math.abs(vy)>.45){
        raf=requestAnimationFrame(coast);
      } else {
        surface.classList.remove('inertia');
        surface.dataset.dragging='false';
      }
    };

    surface.addEventListener('pointerdown',e=>{
      cancelAnimationFrame(raf);
      stage.classList.add('gesture-push');
      surface.classList.remove('inertia');
      lx=e.clientX;ly=e.clientY;lt=performance.now();vx=0;vy=0;
    });

    surface.addEventListener('pointermove',e=>{
      if(surface.dataset.dragging!=='true') return;
      const now=performance.now(),dt=Math.max(8,now-lt);
      vx=(e.clientX-lx)/dt*16.67;
      vy=(e.clientY-ly)/dt*16.67;
      lx=e.clientX;ly=e.clientY;lt=now;
    });

    const release=()=>{
      stage.classList.remove('gesture-push');
      if(Math.abs(vx)+Math.abs(vy)<1.5) return;
      vx=clamp(vx,-28,28);vy=clamp(vy,-22,22);
      surface.classList.add('inertia');
      surface.dataset.dragging='true';
      coast();
    };
    surface.addEventListener('pointerup',release);
    surface.addEventListener('pointercancel',release);
  });

  updateWorld();
})();
