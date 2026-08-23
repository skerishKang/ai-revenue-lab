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
  let timer = 0;
  let cancelled = false;
  let started = false;
  let previousInlineScrollBehavior = '';
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

  function restoreScrollBehavior() {
    if (!started) return;
    document.documentElement.style.scrollBehavior = previousInlineScrollBehavior;
  }

  function stop(reason = 'user') {
    if (cancelled) return;
    cancelled = true;
    if (timer) clearTimeout(timer);
    if (raf) cancelAnimationFrame(raf);
    restoreScrollBehavior();
    stage.classList.remove('autoplay-active');
    if (reason === 'complete') setCue('TOUCH CONNECT');
    else setCue('SCROLL');
  }

  function cancelFromUser() {
    if (cancelled) return;
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
    if (cancelled) return;

    started = true;
    previousInlineScrollBehavior = document.documentElement.style.scrollBehavior;
    // The base stylesheet intentionally uses smooth scrolling for navigation.
    // Autoplay is frame-driven, so smooth scrolling must be disabled while
    // requestAnimationFrame owns the scroll position; otherwise every frame
    // restarts a new smooth-scroll animation and the cinematic can appear stuck.
    document.documentElement.style.scrollBehavior = 'auto';
    window.scrollTo(0, cinematic.offsetTop);

    stage.classList.add('autoplay-active');
    setCue('APPROACHING');

    const from = cinematic.offsetTop;
    const startedAt = performance.now();

    function frame(now) {
      if (cancelled) return;
      const t = Math.min(1, (now - startedAt) / duration);
      const y = from + (targetY() - from) * ease(t);
      window.scrollTo(0, y);
      if (t < 1) raf = requestAnimationFrame(frame);
      else stop('complete');
    }

    raf = requestAnimationFrame(frame);
  }

  if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
  timer = setTimeout(begin, startDelay);
})();
