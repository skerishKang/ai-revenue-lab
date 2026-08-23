(() => {
  const cinematic = document.getElementById('cinematic');
  const stage = document.getElementById('stage');
  const connect = document.getElementById('connect');
  const cue = document.querySelector('.scroll-cue');
  if (!cinematic || !stage || !connect) return;

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const hashTargetsLaterSection = location.hash && location.hash !== '#top';
  if (reduceMotion || hashTargetsLaterSection) return;

  let raf = 0;
  let cancelled = false;
  let started = false;
  const duration = 5200;
  const startDelay = 650;
  const targetProgress = 0.335;

  const ease = (t) => 1 - Math.pow(1 - t, 3);
  const span = () => Math.max(0, cinematic.offsetHeight - innerHeight);
  const targetY = () => cinematic.offsetTop + span() * targetProgress;

  function setCue(text) {
    if (!cue) return;
    const line = cue.querySelector('i');
    cue.textContent = text + ' ';
    if (line) cue.appendChild(line);
  }

  function stop(reason = 'user') {
    if (cancelled) return;
    cancelled = true;
    if (raf) cancelAnimationFrame(raf);
    stage.classList.remove('autoplay-active');
    if (reason === 'complete') setCue('TOUCH CONNECT');
    else if (cue) setCue('SCROLL');
  }

  function cancelFromUser() {
    if (!started || cancelled) return;
    stop('user');
  }

  ['wheel', 'touchstart', 'pointerdown'].forEach((type) => {
    addEventListener(type, cancelFromUser, { passive: true, capture: true });
  });

  addEventListener('keydown', (event) => {
    if (['ArrowDown', 'ArrowUp', 'PageDown', 'PageUp', 'Home', 'End', ' ', 'Spacebar'].includes(event.key)) {
      cancelFromUser();
    }
  }, { capture: true });

  connect.addEventListener('click', () => stop('complete'), { once: true });

  function begin() {
    if (cancelled || scrollY > 24) return;
    started = true;
    stage.classList.add('autoplay-active');
    setCue('APPROACHING');

    const from = scrollY;
    const startedAt = performance.now();

    function frame(now) {
      if (cancelled) return;
      const t = Math.min(1, (now - startedAt) / duration);
      const y = from + (targetY() - from) * ease(t);
      scrollTo(0, y);
      if (t < 1) raf = requestAnimationFrame(frame);
      else stop('complete');
    }

    raf = requestAnimationFrame(frame);
  }

  if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
  setTimeout(begin, startDelay);
})();
