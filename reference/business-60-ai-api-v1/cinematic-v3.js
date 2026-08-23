(() => {
  const stage = document.getElementById('stage');
  const cinematic = document.getElementById('cinematic');
  const connect = document.getElementById('connect');
  const hand = document.getElementById('gesture-hand');
  if (!stage || !cinematic || !connect || !hand) return;

  const controlHand = document.createElement('figure');
  controlHand.className = 'gesture-control-hand';
  controlHand.setAttribute('aria-hidden','true');
  const controlImage = hand.querySelector('img')?.cloneNode(true);
  if (controlImage) controlHand.appendChild(controlImage);
  stage.appendChild(controlHand);

  let connected = stage.classList.contains('connected');
  const clamp=(v,a=0,b=1)=>Math.max(a,Math.min(b,v));
  const localProgress=()=>{
    const span=cinematic.offsetHeight-innerHeight;
    return span>0?clamp((scrollY-cinematic.offsetTop)/span):0;
  };

  function syncHand(){
    const p=localProgress();
    const ready=!connected && p>.235 && p<.445;
    const control=connected && p>.715 && p<.915;
    stage.classList.toggle('hand-ready',ready);
    stage.classList.toggle('physical-control',control);
    if(!ready){
      stage.style.setProperty('--hand-dx','0px');
      stage.style.setProperty('--hand-dy','0px');
    }
  }

  addEventListener('pointermove',e=>{
    stage.style.setProperty('--control-x',`${e.clientX}px`);
    stage.style.setProperty('--control-y',`${e.clientY}px`);
    if(!stage.classList.contains('hand-ready')) return;
    const dx=(e.clientX/innerWidth-.64)*9;
    const dy=(e.clientY/innerHeight-.48)*7;
    stage.style.setProperty('--hand-dx',`${clamp(dx,-4.5,4.5)}px`);
    stage.style.setProperty('--hand-dy',`${clamp(dy,-3.5,3.5)}px`);
  },{passive:true});

  connect.addEventListener('pointerdown',()=>{
    if(connected) return;
    stage.classList.add('hand-touching');
  });
  const releaseContact=()=>{
    if(!connected) stage.classList.remove('hand-touching');
  };
  connect.addEventListener('pointerup',releaseContact);
  connect.addEventListener('pointercancel',releaseContact);
  connect.addEventListener('pointerleave',()=>{
    if(!connected) stage.classList.remove('hand-touching');
  });
  connect.addEventListener('click',()=>{
    connected=true;
    stage.classList.add('hand-touching');
    stage.classList.remove('hand-ready');
    setTimeout(()=>stage.classList.remove('hand-touching'),740);
  });

  document.querySelectorAll('.surface').forEach(surface=>{
    surface.addEventListener('pointerdown',()=>stage.classList.add('physical-grab'));
    const release=()=>stage.classList.remove('physical-grab');
    surface.addEventListener('pointerup',release);
    surface.addEventListener('pointercancel',release);
  });

  addEventListener('scroll',syncHand,{passive:true});
  addEventListener('resize',syncHand,{passive:true});
  stage.style.setProperty('--control-x',`${innerWidth*.5}px`);
  stage.style.setProperty('--control-y',`${innerHeight*.55}px`);
  syncHand();
})();
