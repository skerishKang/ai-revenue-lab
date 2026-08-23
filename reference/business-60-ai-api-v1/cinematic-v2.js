(() => {
  const stage = document.getElementById('stage');
  const connect = document.getElementById('connect');
  const cinematic = document.getElementById('cinematic');
  const cursor = document.getElementById('gesture-cursor');
  if (!stage || !connect || !cinematic || !cursor) return;

  let connected = false;
  let px = innerWidth * .5, py = innerHeight * .5;
  let lastX = px, lastY = py, lastT = performance.now();
  const velocity = {x:0,y:0};

  const clamp=(v,a=0,b=1)=>Math.max(a,Math.min(b,v));
  const localProgress=()=>{
    const span=cinematic.offsetHeight-innerHeight;
    return span>0?clamp((scrollY-cinematic.offsetTop)/span):0;
  };

  const armContact=()=>{
    if (connected) return;
    stage.classList.add('contact-armed');
  };
  const disarmContact=()=>{
    if (connected) return;
    stage.classList.remove('contact-armed');
  };
  connect.addEventListener('pointerenter', armContact);
  connect.addEventListener('pointerleave', disarmContact);
  connect.addEventListener('focus', armContact);
  connect.addEventListener('blur', disarmContact);

  connect.addEventListener('pointerdown',()=>{
    if (connected) return;
    stage.classList.add('contact-strike','camera-impact');
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

    const gesture = connected && p > .715 && p < .915;
    stage.classList.toggle('gesture-mode', gesture);
  }
  addEventListener('scroll',updateWorld,{passive:true});
  addEventListener('resize',updateWorld,{passive:true});

  addEventListener('pointermove',(e)=>{
    px=e.clientX; py=e.clientY;
    cursor.style.left=px+'px'; cursor.style.top=py+'px';
    const now=performance.now(), dt=Math.max(8,now-lastT);
    velocity.x=(px-lastX)/dt*16.67;
    velocity.y=(py-lastY)/dt*16.67;
    lastX=px; lastY=py; lastT=now;

    if (stage.classList.contains('gesture-mode')) {
      stage.style.setProperty('--world-y', `${(px/innerWidth-.5)*3.8}deg`);
      stage.style.setProperty('--world-x', `${-(py/innerHeight-.5)*2.6}deg`);
    }
  },{passive:true});

  document.querySelectorAll('.surface').forEach(surface=>{
    let sx=0,sy=0,tx=0,ty=0,drag=false,raf=0,vx=0,vy=0,lx=0,ly=0,lt=0;

    const apply=()=>{
      surface.style.transform=`translate3d(${tx}px,${ty}px,90px) rotateY(${clamp(vx*.05,-8,8)}deg) rotateX(${clamp(-vy*.035,-6,6)}deg) scale(1.035)`;
    };
    const coast=()=>{
      tx+=vx; ty+=vy; vx*=.92; vy*=.92; apply();
      if(Math.abs(vx)+Math.abs(vy)>.45){raf=requestAnimationFrame(coast)}
      else{surface.classList.remove('inertia')}
    };

    surface.addEventListener('pointerdown',e=>{
      cancelAnimationFrame(raf); drag=true;
      stage.classList.add('gesture-push');
      surface.classList.add('inertia');
      surface.setPointerCapture(e.pointerId);
      sx=e.clientX-tx; sy=e.clientY-ty; lx=e.clientX; ly=e.clientY; lt=performance.now();
    });
    surface.addEventListener('pointermove',e=>{
      if(!drag)return;
      const now=performance.now(),dt=Math.max(8,now-lt);
      tx=e.clientX-sx; ty=e.clientY-sy;
      vx=(e.clientX-lx)/dt*16.67; vy=(e.clientY-ly)/dt*16.67;
      lx=e.clientX;ly=e.clientY;lt=now;apply();
    });
    const release=()=>{
      if(!drag)return; drag=false; stage.classList.remove('gesture-push');
      vx=clamp(vx,-28,28);vy=clamp(vy,-22,22);coast();
    };
    surface.addEventListener('pointerup',release);
    surface.addEventListener('pointercancel',release);
  });

  updateWorld();
})();
