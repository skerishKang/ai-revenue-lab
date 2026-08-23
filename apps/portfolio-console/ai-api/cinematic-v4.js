(() => {
  const stage = document.getElementById('stage');
  const cinematic = document.getElementById('cinematic');
  const connect = document.getElementById('connect');
  if (!stage || !cinematic || !connect) return;

  const split = document.createElement('div');
  split.className = 'world-split';
  split.setAttribute('aria-hidden', 'true');
  split.innerHTML = `
    <section class="world-slice slice-code" data-slice="code"><small>CAPABILITY / 01</small><strong>CODE</strong><span>route · generate · verify</span><i></i><i></i><i></i></section>
    <section class="world-slice slice-vision" data-slice="vision"><small>CAPABILITY / 02</small><strong>VISION</strong><span>see · locate · compare</span><i></i><i></i><i></i></section>
    <section class="world-slice slice-voice" data-slice="voice"><small>CAPABILITY / 03</small><strong>VOICE</strong><span>speak · intent · build</span><i></i><i></i><i></i></section>`;
  stage.appendChild(split);

  const tether = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  tether.setAttribute('class', 'api-tether');
  tether.setAttribute('viewBox', '0 0 1000 1000');
  tether.setAttribute('preserveAspectRatio', 'none');
  tether.setAttribute('aria-hidden', 'true');
  tether.innerHTML = `
    <defs>
      <linearGradient id="tetherPulse" x1="0" x2="1"><stop offset="0" stop-color="#ecffff"/><stop offset=".45" stop-color="#77f7ff"/><stop offset="1" stop-color="#766eff"/></linearGradient>
      <filter id="tetherGlow"><feGaussianBlur stdDeviation="5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    </defs>
    <path class="tether-main" d="M640 480 C615 500 596 522 610 555 C625 588 642 609 632 650"/>
    <path class="tether-echo" d="M642 480 C600 512 580 541 596 573 C610 603 625 626 618 670"/>`;
  stage.appendChild(tether);

  const wash = document.createElement('div');
  wash.className = 'world-transition-wash';
  wash.setAttribute('aria-hidden', 'true');
  stage.appendChild(wash);

  let connected = stage.classList.contains('connected');
  const clamp = (v, a=0, b=1) => Math.max(a, Math.min(b, v));
  const range = (p, a, b) => clamp((p-a)/(b-a));
  const smooth = t => t*t*(3-2*t);
  const localProgress = () => {
    const span = cinematic.offsetHeight - innerHeight;
    return span > 0 ? clamp((scrollY-cinematic.offsetTop)/span) : 0;
  };

  function render(){
    const p = localProgress();
    const charge = connected ? smooth(range(p,.345,.545)) * (1-range(p,.62,.69)) : 0;
    const splitIn = connected ? smooth(range(p,.625,.685)) : 0;
    const splitOut = connected ? smooth(range(p,.755,.815)) : 0;
    const splitAmount = clamp(splitIn * (1-splitOut));

    stage.style.setProperty('--bio-charge', charge.toFixed(4));
    stage.style.setProperty('--split-open', splitAmount.toFixed(4));
    stage.style.setProperty('--split-depth', `${Math.round(splitAmount*120)}px`);

    stage.classList.toggle('neural-sequence', connected && p>.34 && p<.69);
    stage.classList.toggle('world-split-on', splitAmount>.02);
    stage.classList.toggle('world-split-collapse', connected && p>.755 && p<.825);
    stage.classList.toggle('post-split', connected && p>.81);

    const world = stage.dataset.world || '';
    split.querySelectorAll('.world-slice').forEach(el => el.classList.toggle('active', el.dataset.slice === world));

    const roll = splitAmount * Math.sin((p-.625)*Math.PI*7) * .35;
    stage.style.setProperty('--world-roll', `${roll.toFixed(3)}deg`);
  }

  connect.addEventListener('click', () => {
    connected = true;
    stage.classList.add('neural-sequence');
    requestAnimationFrame(render);
  });

  addEventListener('scroll', render, {passive:true});
  addEventListener('resize', render, {passive:true});
  render();
})();
