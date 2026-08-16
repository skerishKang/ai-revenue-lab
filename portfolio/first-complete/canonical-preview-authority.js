(() => {
  /*
   * High-resolution portfolio authority bridge.
   * Source of truth: latest approved Drive/master evidence or B05 live DanjiOn.
   * Preserve the existing portfolio row/cell geometry. No transform upscaling.
   */
  const AUTHORITIES = {
    b01: { asset: 'canonical-previews/highres/b01.png', authority: 'V4 FOCUSED REFINEMENT', sourceUrl: 'https://drive.google.com/file/d/1kj4v10cvarR13jSSowszfrA9FQ8kzLGs/view', position: 'center top' },
    b02: { asset: 'canonical-previews/highres/b02.png', authority: 'IMAGE MATERIAL AUTHORITY', sourceUrl: 'https://drive.google.com/file/d/1MKU3xRACFclsOIMEeXJx5hqPbPKLfUYk/view', position: 'center top' },
    b03: { asset: 'canonical-previews/highres/b03.png', authority: 'IMAGE MATERIAL AUTHORITY', sourceUrl: 'https://drive.google.com/file/d/1xMgYvSVeaWcDOMcm0-C-jf3BdstB_aWq/view', position: 'center top' },
    b04: { asset: 'canonical-previews/highres/b04.png', authority: 'LIVING LEARNING IMAGE MATERIAL AUTHORITY', sourceUrl: 'https://drive.google.com/file/d/1hT9YckjAyvcskdyZQXFyR85HyQu63DKh/view', position: 'center top' },
    b05: { asset: 'canonical-previews/highres/b05.png', authority: 'LIVE DANJION PRODUCT', sourceUrl: 'https://danjion.pages.dev', position: 'center top', preservePublicLink: true },
    b06: { asset: 'canonical-previews/highres/b06.png', authority: 'KEEP CANONICAL', sourceUrl: 'https://drive.google.com/file/d/1ArVTzlAg8w48Tu17eg3Tt0l8_QBm9L4w/view', position: 'center top' },
    b07: { asset: 'canonical-previews/highres/b07.png', authority: 'KEEP CANONICAL', sourceUrl: 'https://drive.google.com/file/d/1scpn2nLg-aHHt6ofGlTNVYIB-gmhWwYX/view', position: 'center top' },
    b08: { asset: 'canonical-previews/highres/b08.png', authority: 'FAMILY NEWSPAPER KEEP CANONICAL', sourceUrl: 'https://drive.google.com/file/d/16iB0HUcZHuQF4l9jvr0PDQULz2a7eg3Y/view', position: 'center top' },
    b09: { asset: 'canonical-previews/highres/b09.png', authority: 'FINAL RASTER AUTHORITY', sourceUrl: 'https://drive.google.com/drive/folders/1Edq_9-jlVwxUfdYUaekr-zLfAVRDippj', position: 'center top', statusLabel: 'INTEGRATION BLOCKED', statusBadge: 'CLEAN-MASTER ASSETS VERIFIED · INTEGRATION BLOCKED' },
    b10: { asset: 'canonical-previews/highres/b10.png', authority: 'FAN MAGAZINE MATERIAL AUTHORITY', sourceUrl: 'https://drive.google.com/file/d/1SYxSccdA0SIEXwq4cjTwxay_3hfNz-nN/view', position: '64% top' },
    b11: { asset: 'canonical-previews/highres/b11.png', authority: 'LANGUAGE LEARNING MAGAZINE · KEEP CANONICAL', sourceUrl: 'https://drive.google.com/file/d/1wa-m9gzYpNTR8JcAW43MuTcvdbjjB2j7/view', position: '58% top' },
    b12: { asset: 'canonical-previews/highres/b12.png', authority: 'CREATOR RELEASE ROOM · KEEP CANONICAL', sourceUrl: 'https://drive.google.com/file/d/1YjLf8TJ63vwHZv5G8YMwkEZeEN7CQFky/view', position: '58% top' },
    b13: { asset: 'canonical-previews/highres/b13.png', authority: 'PRODUCTION MATERIAL PASS', sourceUrl: 'https://drive.google.com/file/d/1mEaX3MTVOgPTR0bx68lmy6Js_KaQFr70/view', position: 'center top' },
    b14: { asset: 'canonical-previews/highres/b14.png', authority: 'V4 MASTER PRODUCT', sourceUrl: 'https://drive.google.com/file/d/16uzeP3KKtoxFUqv5nTxpShu0yzSrWE2j/view', position: 'center top' },
    b15: { asset: 'canonical-previews/highres/b15.png', authority: 'PRODUCTION MATERIAL PASS', sourceUrl: 'https://drive.google.com/file/d/1zAWo-75Cn-4rNHx18XNF3xGglBBCwpc5/view', position: 'center top', statusLabel: 'PASS / FREEZE', forceReady: true }
  };

  const staleLinkPattern = /(?:pages\.dev|workers\.dev)/i;

  function ensureModal() {
    let modal = document.getElementById('canonical-preview-modal');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'canonical-preview-modal';
    modal.hidden = true;
    modal.innerHTML = `
      <div class="canonical-modal-backdrop" data-close="1"></div>
      <div class="canonical-modal-panel" role="dialog" aria-modal="true" aria-label="최신 승인본 고해상도 미리보기">
        <button class="canonical-modal-close" type="button" data-close="1" aria-label="닫기">×</button>
        <div class="canonical-modal-meta"><span></span><a class="canonical-modal-original" target="_blank" rel="noopener">원본 승인본 열기 ↗</a></div>
        <div class="canonical-modal-stage"><img class="canonical-modal-image" alt="최신 승인본 고해상도 미리보기" /></div>
      </div>`;

    const style = document.createElement('style');
    style.textContent = `
      #canonical-preview-modal[hidden]{display:none!important}
      #canonical-preview-modal{position:fixed;inset:0;z-index:99999;display:grid;place-items:center;padding:28px}
      .canonical-modal-backdrop{position:absolute;inset:0;background:rgba(0,0,0,.9);backdrop-filter:blur(8px)}
      .canonical-modal-panel{position:relative;z-index:1;width:min(1500px,96vw);max-height:94vh;background:#0b0b0b;border:1px solid rgba(255,255,255,.16);border-radius:14px;overflow:auto;box-shadow:0 30px 100px rgba(0,0,0,.55)}
      .canonical-modal-stage{display:block;min-width:100%;min-height:240px;overflow:auto;background:#111}
      .canonical-modal-image{display:block;width:auto;height:auto;max-width:none;max-height:none;margin:0 auto;background:#111;image-rendering:auto;transform:none}
      .canonical-modal-meta{position:sticky;top:0;z-index:3;padding:14px 54px 12px 18px;font:600 11px/1.4 system-ui,sans-serif;letter-spacing:.10em;text-transform:uppercase;color:#b9b9b9;background:#0b0b0b;border-bottom:1px solid rgba(255,255,255,.1);display:flex;align-items:center;justify-content:space-between;gap:20px}
      .canonical-modal-original{font-size:10px;color:#f1eee7;border-bottom:1px solid #777;white-space:nowrap}
      .canonical-modal-close{position:absolute;right:12px;top:8px;z-index:5;border:0;background:transparent;color:#fff;font:300 32px/1 system-ui;cursor:pointer}
      .canonical-authority-badge{position:absolute;left:10px;bottom:10px;z-index:3;padding:6px 8px;border:1px solid rgba(255,255,255,.18);border-radius:999px;background:rgba(5,5,5,.84);backdrop-filter:blur(8px);font:700 9px/1 system-ui,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:#f0eee8;pointer-events:none}
      .canonical-preview-image{position:absolute;inset:0;width:100%;height:100%;max-width:none;max-height:none;margin:0;padding:0;display:block;object-fit:cover;background:#0e0e0e;cursor:zoom-in;transform:none}
      .evidence.canonical-evidence-host{position:relative;padding:0;overflow:hidden;background:#0e0e0e}
      #b09 .preview.blocked:after{display:none!important}
    `;
    document.head.appendChild(style);
    document.body.appendChild(modal);

    modal.addEventListener('click', (event) => {
      if (event.target.closest('[data-close="1"]')) modal.hidden = true;
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') modal.hidden = true;
    });
    return modal;
  }

  function openCanonical(id, assetSrc, config) {
    const modal = ensureModal();
    const image = modal.querySelector('.canonical-modal-image');
    const original = modal.querySelector('.canonical-modal-original');
    const status = config.statusBadge ? ` · ${config.statusBadge}` : '';
    modal.querySelector('.canonical-modal-meta span').textContent =
      `${id.toUpperCase()} · LATEST APPROVED · ${config.authority}${status} · HIGH-RES EVIDENCE`;
    original.href = config.sourceUrl;
    image.onerror = () => {
      image.onerror = null;
      modal.querySelector('.canonical-modal-meta span').textContent =
        `${id.toUpperCase()} · HIGH-RES ASSET LOAD ERROR · 원본 승인본 링크를 확인하세요`;
    };
    image.src = assetSrc;
    modal.hidden = false;
  }

  function previewHost(article) {
    const viewport = article.querySelector('.preview .viewport') || article.querySelector('.viewport');
    if (viewport) return { host: viewport, type: 'viewport' };
    const evidence = article.querySelector('.evidence');
    if (evidence) return { host: evidence, type: 'evidence' };
    const preview = article.querySelector('.preview');
    if (preview) return { host: preview, type: 'preview' };
    return null;
  }

  function setStatus(article, config) {
    if (config.forceReady) article.dataset.kind = 'ready';
    if (!config.statusLabel) return;
    const status = article.querySelector('.status');
    if (!status) return;
    status.innerHTML = `<i class="dot"></i>${config.statusLabel}`;
  }

  function installCanonicalPreview(id, config) {
    const article = document.getElementById(id);
    if (!article) return;
    const target = previewHost(article);
    if (!target) return;

    const { host, type } = target;
    const resolved = new URL(config.asset, document.baseURI).href;

    // Never change .viewport positioning. It is absolute in the frozen layout.
    if (type === 'evidence') host.classList.add('canonical-evidence-host');

    if (id === 'b09') {
      article.querySelector('.preview')?.classList.remove('blocked');
    }

    const img = document.createElement('img');
    img.className = 'canonical-preview-image';
    img.src = resolved;
    img.alt = `${id.toUpperCase()} 최신 승인 디자인`;
    img.loading = 'eager';
    img.decoding = 'async';
    img.style.objectPosition = config.position || 'center top';
    img.addEventListener('click', () => openCanonical(id, resolved, config));
    host.replaceChildren(img);

    const badge = document.createElement('div');
    badge.className = 'canonical-authority-badge';
    badge.textContent = config.statusBadge
      ? `LATEST APPROVED · ${config.authority} · ${config.statusBadge}`
      : `LATEST APPROVED · ${config.authority}`;
    host.appendChild(badge);

    article.dataset.previewAuthority = 'local-highres-approved';
    article.querySelectorAll('.preview-loading, .preview-note').forEach((node) => node.remove());
    const previewLabel = article.querySelector('.preview-label');
    if (previewLabel && id !== 'b05') previewLabel.textContent = 'Latest approved';
    setStatus(article, config);

    if (!config.preservePublicLink) {
      article.querySelectorAll('a[href]').forEach((link) => {
        const href = link.getAttribute('href') || '';
        if (!/^https?:/i.test(href) || !staleLinkPattern.test(href)) return;
        link.dataset.staleDeployment = href;
        link.removeAttribute('target');
        link.removeAttribute('rel');
        link.setAttribute('href', '#');
        link.textContent = '승인본 크게 보기';
        link.addEventListener('click', (event) => {
          event.preventDefault();
          openCanonical(id, resolved, config);
        });
      });
    }
  }

  function updatePortfolioStatusSummary() {
    const ready = document.querySelector('.metric.ready strong');
    const candidate = document.querySelector('.metric.candidate strong');
    if (ready) ready.textContent = '13';
    if (candidate) candidate.textContent = '00';
  }

  function boot() {
    Object.entries(AUTHORITIES).forEach(([id, config]) => installCanonicalPreview(id, config));
    updatePortfolioStatusSummary();
    document.documentElement.dataset.portfolioPreviewAuthority = 'local-highres-approved-20260817';
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
})();
