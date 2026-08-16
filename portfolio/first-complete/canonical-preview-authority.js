(() => {
  /*
   * Portfolio preview authority correction.
   * - Preserve the original portfolio layout and viewport geometry.
   * - Card previews use the already-deployed approved raster as a lightweight cover.
   * - Click view asks Drive for the existing high-resolution approval evidence.
   * - No new imagery is generated here.
   */
  const AUTHORITIES = {
    b01: { card: 'canonical-previews/b01.jpg', authority: 'Drive V4 Focused Refinement', driveId: '1kj4v10cvarR13jSSowszfrA9FQ8kzLGs' },
    b02: { card: 'canonical-previews/b02.jpg', authority: 'Drive Image Material Authority', driveId: '1MKU3xRACFclsOIMEeXJx5hqPbPKLfUYk' },
    b04: { card: 'canonical-previews/b04.jpg', authority: 'Drive Image Material Authority', driveId: '1hT9YckjAyvcskdyZQXFyR85HyQu63DKh' },
    b06: { card: 'canonical-previews/b06.jpg', authority: 'Drive KEEP Canonical', driveId: '1ArVTzlAg8w48Tu17eg3Tt0l8_QBm9L4w' },
    b07: { card: 'canonical-previews/b07.jpg', authority: 'Drive KEEP Canonical', driveId: '1scpn2nLg-aHHt6ofGlTNVYIB-gmhWwYX' },
    b08: { card: 'canonical-previews/b08.jpg', authority: 'Drive KEEP Canonical', driveId: '16iB0HUcZHuQF4l9jvr0PDQULz2a7eg3Y' },
    b10: { card: 'canonical-previews/b10.jpg', authority: 'Drive Material Authority', driveId: '1NbQauk3LX5ycXClG65R6Weo1_vqPSTjv' },
    b11: { card: 'canonical-previews/b11.jpg', authority: 'Drive KEEP Canonical', driveId: '1vjJ4I-SAFG-LOEumdj34Qk434CWJG0Qr' },
    b12: { card: 'canonical-previews/b12.jpg', authority: 'Drive KEEP Canonical', driveId: '1eK75xj9lzOu86DWaBcbD9LS7gtMNG3dv' },
    b13: { card: 'canonical-previews/b13.jpg', authority: 'Drive Production Material Pass', driveId: '1KV2_Z_vxJOWCR65Onib6CwgOSYZqHzAm' },
    b15: { card: 'canonical-previews/b15.jpg', authority: 'Drive Production Material Pass', driveId: '1lWxUJ039pjF1JZ0J5_zPQDmbM5H4r9hC' }
  };

  const staleLinkPattern = /(?:pages\.dev|workers\.dev)/i;

  function driveViewUrl(driveId) {
    return `https://drive.google.com/file/d/${driveId}/view`;
  }

  function driveHighResUrl(driveId) {
    return `https://drive.google.com/thumbnail?id=${driveId}&sz=w1600`;
  }

  function ensureModal() {
    let modal = document.getElementById('canonical-preview-modal');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'canonical-preview-modal';
    modal.hidden = true;
    modal.innerHTML = `
      <div class="canonical-modal-backdrop" data-close="1"></div>
      <div class="canonical-modal-panel" role="dialog" aria-modal="true" aria-label="최신 승인본 미리보기">
        <button class="canonical-modal-close" type="button" data-close="1" aria-label="닫기">×</button>
        <div class="canonical-modal-meta"><span></span><a class="canonical-modal-original" target="_blank" rel="noopener">원본 승인본 열기 ↗</a></div>
        <div class="canonical-modal-stage"><img class="canonical-modal-image" alt="최신 승인본 고해상도 미리보기" /></div>
      </div>`;
    const style = document.createElement('style');
    style.textContent = `
      #canonical-preview-modal[hidden]{display:none!important}
      #canonical-preview-modal{position:fixed;inset:0;z-index:99999;display:grid;place-items:center;padding:28px}
      .canonical-modal-backdrop{position:absolute;inset:0;background:rgba(0,0,0,.88);backdrop-filter:blur(8px)}
      .canonical-modal-panel{position:relative;z-index:1;width:min(1440px,96vw);max-height:94vh;background:#0b0b0b;border:1px solid rgba(255,255,255,.16);border-radius:14px;overflow:auto;box-shadow:0 30px 100px rgba(0,0,0,.55)}
      .canonical-modal-stage{width:100%;background:#111;display:grid;place-items:center;min-height:240px}
      .canonical-modal-image{width:100%;height:auto;display:block;background:#111;image-rendering:auto}
      .canonical-modal-meta{padding:14px 54px 12px 18px;font:600 11px/1.4 system-ui,sans-serif;letter-spacing:.10em;text-transform:uppercase;color:#b9b9b9;border-bottom:1px solid rgba(255,255,255,.1);display:flex;align-items:center;justify-content:space-between;gap:20px}
      .canonical-modal-original{font-size:10px;color:#f1eee7;border-bottom:1px solid #777;white-space:nowrap}
      .canonical-modal-close{position:absolute;right:12px;top:8px;z-index:2;border:0;background:transparent;color:#fff;font:300 32px/1 system-ui;cursor:pointer}
      .canonical-authority-badge{position:absolute;left:10px;bottom:10px;z-index:3;padding:6px 8px;border:1px solid rgba(255,255,255,.18);border-radius:999px;background:rgba(5,5,5,.82);backdrop-filter:blur(8px);font:700 9px/1 system-ui,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:#f0eee8;pointer-events:none}
      .canonical-preview-image{position:absolute;inset:0;width:100%;height:100%;max-width:none;max-height:none;margin:0;padding:0;display:block;object-fit:cover;object-position:center top;background:#0e0e0e;cursor:zoom-in;transform:none}
      .canonical-b09-blocker{height:100%;min-height:250px;display:flex;flex-direction:column;justify-content:center;padding:30px;background:radial-gradient(circle at 72% 28%,rgba(235,116,73,.16),transparent 34%),#0d0d0d;color:#f4f0e8}
      .canonical-b09-kicker{font:700 10px/1 system-ui,sans-serif;letter-spacing:.16em;color:#e88b69;margin-bottom:14px}
      .canonical-b09-title{font:650 clamp(20px,2.3vw,28px)/1.12 system-ui,sans-serif;max-width:560px}
      .canonical-b09-copy{font:400 12px/1.65 system-ui,sans-serif;color:#aaa;margin-top:16px;max-width:600px}
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

  function openCanonical(id, cardSrc, authority, driveId) {
    const modal = ensureModal();
    const image = modal.querySelector('.canonical-modal-image');
    const original = modal.querySelector('.canonical-modal-original');
    modal.querySelector('.canonical-modal-meta span').textContent = `${id.toUpperCase()} · LATEST APPROVED · ${authority} · HIGH-RES EVIDENCE`;
    original.href = driveViewUrl(driveId);

    image.onerror = () => {
      image.onerror = null;
      image.src = cardSrc;
      modal.querySelector('.canonical-modal-meta span').textContent = `${id.toUpperCase()} · LATEST APPROVED · ${authority} · 원본은 우측 링크에서 확인`;
    };
    image.src = driveHighResUrl(driveId);
    modal.hidden = false;
  }

  function previewHost(article) {
    return article.querySelector('.preview .viewport') || article.querySelector('.viewport') || article.querySelector('.preview');
  }

  function installCanonicalPreview(id, config) {
    const article = document.getElementById(id);
    if (!article) return;
    const host = previewHost(article);
    if (!host) return;

    const resolved = new URL(config.card, document.baseURI).href;

    // Do NOT change .viewport position. The original stylesheet makes it absolute
    // and stretches it from top:42px to bottom:0. Changing it to relative collapsed
    // the preview area and produced the black-cell/thin-strip failure.
    const img = document.createElement('img');
    img.className = 'canonical-preview-image';
    img.src = resolved;
    img.alt = `${id.toUpperCase()} 최신 승인본 화면`;
    img.loading = 'eager';
    img.decoding = 'async';
    img.addEventListener('click', () => openCanonical(id, resolved, config.authority, config.driveId));
    host.replaceChildren(img);

    const badge = document.createElement('div');
    badge.className = 'canonical-authority-badge';
    badge.textContent = `LATEST APPROVED · ${config.authority}`;
    host.appendChild(badge);

    article.dataset.previewAuthority = 'drive-canonical';
    article.querySelectorAll('.preview-loading').forEach((node) => node.remove());

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
        openCanonical(id, resolved, config.authority, config.driveId);
      });
    });
  }

  function installB09Blocker() {
    const article = document.getElementById('b09');
    if (!article) return;
    const host = previewHost(article);
    if (host) {
      host.replaceChildren();
      const panel = document.createElement('div');
      panel.className = 'canonical-b09-blocker';
      panel.innerHTML = `
        <div class="canonical-b09-kicker">B09 · INTEGRATION BLOCKER</div>
        <div class="canonical-b09-title">clean-master assets는 존재하지만 최종 site integration은 미완료입니다.</div>
        <div class="canonical-b09-copy">구형 SVG/story public surface를 최종 디자인처럼 표시하지 않습니다. clean-master byte integration과 검증이 끝난 뒤 최신 승인 화면으로 교체합니다.</div>`;
      host.appendChild(panel);
    }
    article.dataset.previewAuthority = 'blocked-no-stale-preview';
    article.querySelectorAll('.preview-loading').forEach((node) => node.remove());
    article.querySelectorAll('a[href]').forEach((link) => {
      const href = link.getAttribute('href') || '';
      if (/^https?:/i.test(href)) {
        link.dataset.staleDeployment = href;
        link.removeAttribute('href');
        link.removeAttribute('target');
        link.style.pointerEvents = 'none';
        link.textContent = 'BLOCKED · 최신 통합 대기';
      }
    });
  }

  function boot() {
    Object.entries(AUTHORITIES).forEach(([id, config]) => installCanonicalPreview(id, config));
    installB09Blocker();
    document.documentElement.dataset.portfolioPreviewAuthority = 'drive-canonical-highres-20260816';
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
})();
