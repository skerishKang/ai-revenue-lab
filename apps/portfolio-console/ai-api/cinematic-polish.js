(() => {
  const stage=document.getElementById('stage');
  const cinematic=document.getElementById('cinematic');
  const alone=document.querySelector('.shot-alone');
  const connection=document.querySelector('.shot-connection');
  const close=document.querySelector('.shot-close');
  const field=document.querySelector('.shot-field');
  if(!stage||!cinematic||!alone||!connection||!close||!field)return;

  const clamp=(v,a=0,b=1)=>Math.max(a,Math.min(b,v));
  const range=(p,a,b)=>clamp((p-a)/(b-a));
  const mix=(a,b,t)=>a+(b-a)*t;
  const progress=()=>{
    const span=cinematic.offsetHeight-innerHeight;
    return span>0?clamp((scrollY-cinematic.offsetTop)/span):0;
  };

  function sync(){
    const p=progress();
    const connected=stage.classList.contains('connected');
    stage.classList.toggle('identity-clean', connected && p>.905);

    if(!connected){
      const b=mix(.30,.35,range(p,0,.27));
      alone.style.filter=`brightness(${b.toFixed(3)}) saturate(.64) contrast(1.13) hue-rotate(180deg)`;
      return;
    }

    connection.style.opacity='0';
    field.style.opacity='0';

    const fadeOut=1-range(p,.895,.95);
    close.style.opacity=String(clamp(fadeOut));

    let scale,tx,ty;
    if(p<.56){
      const t=range(p,.33,.56);
      scale=mix(1.12,1.34,t); tx=mix(2,-1,t); ty=mix(1,0,t);
    }else{
      const t=range(p,.56,.82);
      scale=mix(1.34,1.08,t); tx=mix(-1,1.5,t); ty=mix(0,1,t);
    }
    close.style.transform=`scale(${scale.toFixed(3)}) translate3d(${tx.toFixed(2)}vw,${ty.toFixed(2)}vh,0)`;
    close.style.filter=`brightness(${mix(.34,.40,range(p,.33,.76)).toFixed(3)}) saturate(.56) contrast(1.13) hue-rotate(180deg)`;
  }

  addEventListener('scroll',()=>requestAnimationFrame(sync),{passive:true});
  addEventListener('resize',()=>requestAnimationFrame(sync),{passive:true});
  document.getElementById('connect')?.addEventListener('click',()=>setTimeout(sync,0));
  sync();
})();
