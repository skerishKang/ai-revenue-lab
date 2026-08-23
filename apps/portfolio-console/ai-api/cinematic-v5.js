(() => {
  const stage=document.getElementById('stage');
  const cinematic=document.getElementById('cinematic');
  const connect=document.getElementById('connect');
  if(!stage||!cinematic||!connect)return;

  const root=document.createElement('div');
  root.className='voice-build';
  root.setAttribute('aria-hidden','true');

  const listen=document.createElement('div');
  listen.className='voice-listen';
  for(let i=0;i<32;i++){
    const bar=document.createElement('i');
    bar.style.setProperty('--amp',(0.25+Math.sin((i/31)*Math.PI)*.75).toFixed(2));
    listen.appendChild(bar);
  }

  const transcript=document.createElement('div');
  transcript.className='voice-transcript';
  ['SECURE LOGIN','LOWEST COST','AVAILABLE MODEL','TEST','DEPLOY'].forEach(t=>{
    const chip=document.createElement('b');chip.textContent=t;transcript.appendChild(chip);
  });

  const route=document.createElement('div');
  route.className='voice-route';
  const nodes=[
    ['route-intent','INTENT','LOGIN API'],
    ['route-access','ACCESS','LOWEST COST'],
    ['route-model','MODEL','GLM 5.2'],
    ['route-api','OUTPUT','API']
  ];
  nodes.forEach(([cls,k,v])=>{
    const n=document.createElement('div');n.className=`route-node ${cls}`;n.innerHTML=`${k}<strong>${v}</strong>`;route.appendChild(n);
  });

  const codeField=document.createElement('div');
  codeField.className='voice-code-field';
  [
    'intent = "secure login API"',
    'route = ai_api.find_access(strategy="lowest_cost")',
    'result = route.model.generate(intent)',
    'verify(result); deploy(result)'
  ].forEach(line=>{const s=document.createElement('div');s.className='code-strip';s.textContent=line;codeField.appendChild(s)});

  const api=document.createElement('div');
  api.className='api-construct';
  api.innerHTML='<div><small>CONSTRUCTED CAPABILITY</small><strong>API</strong><em>ROUTE VERIFIED · CODE READY</em></div>';

  const status=document.createElement('div');
  status.className='voice-build-status';
  status.textContent='VOICE → INTENT → ROUTE → CODE → API';

  root.append(listen,transcript,route,codeField,api,status);
  stage.appendChild(root);

  let connected=stage.classList.contains('connected');
  const clamp=(v,a=0,b=1)=>Math.max(a,Math.min(b,v));
  const localProgress=()=>{
    const span=cinematic.offsetHeight-innerHeight;
    return span>0?clamp((scrollY-cinematic.offsetTop)/span):0;
  };

  connect.addEventListener('click',()=>{connected=true;sync()});

  const clear=()=>{
    ['voice-build-on','vb-listen','vb-capture','vb-route','vb-code','vb-ready'].forEach(c=>stage.classList.remove(c));
  };

  function sync(){
    const p=localProgress();
    clear();
    if(!connected||p<.785||p>.955)return;
    stage.classList.add('voice-build-on');
    if(p<.82)stage.classList.add('vb-listen');
    else if(p<.85)stage.classList.add('vb-capture');
    else if(p<.885)stage.classList.add('vb-route');
    else if(p<.925)stage.classList.add('vb-code');
    else stage.classList.add('vb-ready');
  }

  addEventListener('pointermove',e=>{
    if(!stage.classList.contains('voice-build-on'))return;
    const x=(e.clientX/innerWidth-.5)*2;
    const y=(e.clientY/innerHeight-.5)*2;
    stage.style.setProperty('--vb-y',`${(x*4.5).toFixed(2)}deg`);
    stage.style.setProperty('--vb-x',`${(-y*3.2).toFixed(2)}deg`);
  },{passive:true});
  addEventListener('scroll',sync,{passive:true});
  addEventListener('resize',sync,{passive:true});
  sync();
})();
