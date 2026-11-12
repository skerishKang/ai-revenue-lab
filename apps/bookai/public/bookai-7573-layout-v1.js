/* #7573 · reading-screen panel state and paper light (2026-11-12 owner check).
   Two owner-visible blockers, both runtime-only:
     1  the reader no longer opens with a panel already open. storymemory-b61-ui-
        polish-v1.js adds body.memory-open on every desktop width and body.ai-open
        from 1440 px up; this file clears exactly that entry default and leaves
        every user toggle alone.
     8  the desk light stops chasing the pointer. --desk-x/--desk-y are pinned at
        0, --lamp-x/--lamp-y ease toward the pointer by ~0.08 per frame at half
        the previous contrast, and the animation loop ends once the lamp has
        settled, so a still mouse costs no frames. The page-hover edge colour
        change the owner likes is not touched. prefers-reduced-motion keeps the
        lamp centred and never starts the loop.
   No packet, prompt, corpus, route or storage change: presentation only. */
(function () {
  'use strict';

  var doc = document;
  var body = doc.body;

  /* ---- 1: no panel opens by itself on reader entry ---------------------- */
  function clearEntryDefaults() {
    if (!body.classList.contains('reader-mode')) return;
    body.classList.remove('memory-open');
    body.classList.remove('ai-open');
    var memoryTab = doc.getElementById('memoryRailTab');
    var aiTab = doc.getElementById('aiRailTab');
    if (memoryTab) {
      memoryTab.setAttribute('aria-expanded', 'false');
      memoryTab.setAttribute('aria-label', 'Memory 패널 열기');
    }
    if (aiTab) {
      aiTab.setAttribute('aria-expanded', 'false');
      aiTab.setAttribute('aria-label', 'AI Companion 패널 열기');
    }
  }

  /* The polish runtime sets its defaults from a MutationObserver on the same
     class, so the clear has to run after that observer, never before it. */
  var clearQueued = false;
  function queueClear() {
    if (clearQueued) return;
    clearQueued = true;
    /* Two microtask hops: one lands after the observer that just fired, the
       second after any observer that observer scheduled. */
    Promise.resolve().then(function () {
      Promise.resolve().then(function () {
        clearQueued = false;
        clearEntryDefaults();
      });
    });
  }

  var wasReader = body.classList.contains('reader-mode');
  new MutationObserver(function () {
    var isReader = body.classList.contains('reader-mode');
    if (isReader && !wasReader) queueClear();
    wasReader = isReader;
  }).observe(body, { attributes: true, attributeFilter: ['class'] });
  if (wasReader) queueClear();

  /* A user click is the only thing allowed to open a panel: remember that a
     panel was opened by hand so the entry clear never fights it. */
  var userOpened = false;
  ['memoryRailTab', 'aiRailTab'].forEach(function (id) {
    var tab = doc.getElementById(id);
    if (tab) tab.addEventListener('click', function () { userOpened = true; }, true);
  });
  doc.addEventListener('click', function (event) {
    var target = event.target;
    if (target && target.closest && target.closest('.panel-rail-tab, .smal-dock, .mobile-dock')) {
      userOpened = true;
    }
  }, true);
  var originalClear = clearEntryDefaults;
  clearEntryDefaults = function () {
    var opened = body.classList.contains('memory-open') || body.classList.contains('ai-open');
    /* An entry default is the only state this file clears; a panel the user
       opened in this session is theirs. */
    if (opened && userOpened) return;
    originalClear();
  };

  /* ---- 8: eased paper light, pinned desk offsets ----------------------- */
  var LAMP_STEP = 0.08;          /* fraction of the remaining distance per frame */
  var LAMP_CONTRAST = 0.5;       /* half the travel the owner called flicker */
  var LAMP_SETTLED = 0.05;       /* percent; below this the loop stops */
  var LAMP_CENTRE = { x: 50, y: 50 };

  function reducedMotion() {
    return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }

  function createLight(stage, paper) {
    var current = { x: LAMP_CENTRE.x, y: LAMP_CENTRE.y };
    var target = { x: LAMP_CENTRE.x, y: LAMP_CENTRE.y };
    var frame = 0;

    function paint() {
      paper.style.setProperty('--lamp-x', current.x.toFixed(2) + '%');
      paper.style.setProperty('--lamp-y', current.y.toFixed(2) + '%');
    }

    function pinDesk() {
      stage.style.setProperty('--desk-x', '0px');
      stage.style.setProperty('--desk-y', '0px');
    }

    function settle() {
      frame = 0;
      paint();
    }

    function step() {
      frame = 0;
      var dx = target.x - current.x;
      var dy = target.y - current.y;
      if (Math.abs(dx) < LAMP_SETTLED && Math.abs(dy) < LAMP_SETTLED) {
        current.x = target.x;
        current.y = target.y;
        settle();
        return;
      }
      current.x += dx * LAMP_STEP;
      current.y += dy * LAMP_STEP;
      paint();
      frame = window.requestAnimationFrame(step);
    }

    function schedule() {
      if (frame || reducedMotion()) return;
      frame = window.requestAnimationFrame(step);
    }

    function aim(event, stageRect, paperRect) {
      if (!paperRect.width || !paperRect.height) return;
      var px = (event.clientX - paperRect.left) / paperRect.width * 100;
      var py = (event.clientY - paperRect.top) / paperRect.height * 100;
      px = Math.max(0, Math.min(100, px));
      py = Math.max(0, Math.min(100, py));
      /* Half the distance to the centre: the lamp drifts instead of swinging,
         and the two light bands stop strobing on every pointer event. */
      target.x = LAMP_CENTRE.x + (px - LAMP_CENTRE.x) * LAMP_CONTRAST;
      target.y = LAMP_CENTRE.y + (py - LAMP_CENTRE.y) * LAMP_CONTRAST;
      schedule();
      void stageRect;
    }

    return {
      aim: aim,
      pinDesk: pinDesk,
      recentre: function () {
        target.x = LAMP_CENTRE.x;
        target.y = LAMP_CENTRE.y;
        if (reducedMotion()) {
          current.x = target.x;
          current.y = target.y;
          paint();
          return;
        }
        schedule();
      },
      reset: function () {
        if (frame) {
          window.cancelAnimationFrame(frame);
          frame = 0;
        }
        current.x = LAMP_CENTRE.x;
        current.y = LAMP_CENTRE.y;
        target.x = LAMP_CENTRE.x;
        target.y = LAMP_CENTRE.y;
        pinDesk();
        paint();
      },
      syncReducedMotion: function () {
        if (reducedMotion()) {
          if (frame) {
            window.cancelAnimationFrame(frame);
            frame = 0;
          }
          current.x = LAMP_CENTRE.x;
          current.y = LAMP_CENTRE.y;
          target.x = LAMP_CENTRE.x;
          target.y = LAMP_CENTRE.y;
          paint();
        }
      }
    };
  }

  function boot() {
    var stage = doc.querySelector('.reader-stage');
    var paper = doc.getElementById('paper');
    if (!stage || !paper) return;
    var light = createLight(stage, paper);

    /* The desk offsets never move again: the room is still, only the lamp
       drifts. Pinned before any pointer event so a first move cannot shift it. */
    light.pinDesk();

    stage.addEventListener('pointermove', function (event) {
      if (window.innerWidth <= 720) return;
      light.pinDesk();
      var stageRect = stage.getBoundingClientRect();
      var paperRect = paper.getBoundingClientRect();
      light.aim(event, stageRect, paperRect);
    }, { passive: true });

    stage.addEventListener('pointerleave', function () {
      light.recentre();
    });

    /* The reader is rebuilt on every chapter change; restore the paused state
       where the old inline handlers left the light. */
    doc.addEventListener('sm-reader-entry', function () { light.reset(); });

    if (window.matchMedia) {
      var query = window.matchMedia('(prefers-reduced-motion: reduce)');
      var onChange = function () { light.syncReducedMotion(); };
      if (query.addEventListener) query.addEventListener('change', onChange);
      else if (query.addListener) query.addListener(onChange);
    }
    light.syncReducedMotion();
  }

  if (doc.readyState === 'loading') {
    doc.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  window.__bookai7573LayoutV1 = { version: 'v1', panelEntry: 'user-only', lamp: 'eased' };
})();
