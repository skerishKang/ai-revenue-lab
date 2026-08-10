(() => {
  'use strict';
  const names = ['article','short','audio'];
  let index = 0;
  document.querySelectorAll('img').forEach((img) => {
    const src = img.getAttribute('src') || '';
    if (!/\.svg(?:[?#]|$)/i.test(src)) return;
    const kind = names[index % names.length];
    const scene = document.createElement('div');
    scene.className = 'creator-scene';
    scene.dataset.kind = kind;
    scene.dataset.format = kind === 'article' ? 'ARTICLE' : kind === 'short' ? 'SHORT' : 'AUDIO';
    scene.setAttribute('role','img');
    scene.setAttribute('aria-label', img.getAttribute('alt') || `${kind} format preview`);
    img.replaceWith(scene);
    index += 1;
  });
  document.documentElement.dataset.creatorRoom = 'v2';
  document.documentElement.dataset.replacedSvg = String(index);
})();