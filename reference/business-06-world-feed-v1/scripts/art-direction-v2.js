(() => {
  'use strict';

  const sceneNames = {
    'hero-harbor': ['harbor', 'Harbor / Dusk'],
    'neighborhood-bookshop': ['bookshop', 'Neighborhood / Late light'],
    'night-market': ['market', 'Market / 00:14'],
    'sea-train': ['coast', 'Coastline / Slow rail'],
    'maker-studio': ['maker', 'Maker / After hours'],
    'stadium-culture': ['stadium', 'Stadium / Local chorus'],
    'small-cinema': ['cinema', 'Cinema / Night block'],
    'market-studio': ['maker', 'Market / Workshop'],
    'story-harbor': ['harbor', 'Harbor / Context'],
    'why-harbor': ['harbor', 'Why / Your signal']
  };

  function sceneFor(img, index) {
    const src = img.getAttribute('src') || '';
    const base = (src.split('/').pop() || '').replace(/\.svg(?:[?#].*)?$/i, '');
    const pair = sceneNames[base] || ['generic', base.replace(/[-_]+/g, ' ') || 'World signal'];
    const scene = document.createElement('div');
    scene.className = `wf-scene wf-scene--${pair[0]}`;
    scene.setAttribute('role', 'img');
    scene.setAttribute('aria-label', img.getAttribute('alt') || pair[1]);
    scene.dataset.replacesSvg = base;
    scene.innerHTML = [
      `<span class="wf-scene-code">WF / ${String(index + 1).padStart(2, '0')} / SIGNAL</span>`,
      '<i class="wf-scene-point p1" aria-hidden="true"></i>',
      '<i class="wf-scene-point p2" aria-hidden="true"></i>',
      '<i class="wf-scene-point p3" aria-hidden="true"></i>',
      `<strong class="wf-scene-title">${pair[1]}</strong>`
    ].join('');
    return scene;
  }

  function replaceVisibleSvgArtwork() {
    const images = [...document.querySelectorAll('img')].filter((img) => /\.svg(?:[?#]|$)/i.test(img.getAttribute('src') || ''));
    images.forEach((img, index) => {
      if (img.closest('.brand, .verified-authority')) return;
      img.replaceWith(sceneFor(img, index));
    });
    document.documentElement.dataset.worldFeedArt = 'product-v2';
    document.documentElement.dataset.svgArtworkReplaced = String(images.length);
  }

  function markCurrentNavigation() {
    const route = (location.hash || '#feed').slice(1).split('?')[0];
    document.querySelectorAll('.product-nav [data-route-link]').forEach((link) => {
      const key = link.getAttribute('data-route-link');
      if (key === route || (route === 'story' && key === 'feed') || (route === 'why' && key === 'feed') || (route === 'preferences' && key === 'feed')) {
        link.setAttribute('aria-current', 'page');
      } else {
        link.removeAttribute('aria-current');
      }
    });
  }

  replaceVisibleSvgArtwork();
  markCurrentNavigation();
  window.addEventListener('hashchange', markCurrentNavigation);
})();
