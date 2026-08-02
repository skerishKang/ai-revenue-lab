(() => {
  const load = (src) => new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = src;
    script.onload = resolve;
    script.onerror = reject;
    document.body.append(script);
  });

  window.B14CatalogReady = load('scripts/catalog-rows-a.js')
    .then(() => load('scripts/catalog-rows-b.js'))
    .then(() => load('scripts/catalog-shell-v31.js'))
    .then(() => load('scripts/layout-v32.js'));
})();