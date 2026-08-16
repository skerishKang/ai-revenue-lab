(() => {
  const AUTHORITIES = {
    b01: ['canonical-previews/b01.jpg', 'Drive V4 Focused Refinement'],
    b02: ['canonical-previews/b02.jpg', 'Drive Image Material Authority'],
    b03: ['canonical-previews/b03.jpg', 'Drive Image Material Authority'],
    b04: ['canonical-previews/b04.jpg', 'Drive Image Material Authority'],
    b06: ['canonical-previews/b06.jpg', 'Drive KEEP Canonical'],
    b07: ['canonical-previews/b07.jpg', 'Drive KEEP Canonical'],
    b08: ['canonical-previews/b08.jpg', 'Drive KEEP Canonical'],
    b10: ['canonical-previews/b10.jpg', 'Drive Material Authority'],
    b11: ['canonical-previews/b11.jpg', 'Drive KEEP Canonical'],
    b12: ['canonical-previews/b12.jpg', 'Drive KEEP Canonical'],
    b13: ['canonical-previews/b13.jpg', 'Drive Production Material Pass'],
    b14: ['canonical-previews/b14.jpg', 'Drive V4 Master Product'],
    b15: ['canonical-previews/b15.jpg', 'Drive Production Material Pass']
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
      <div class="canonical-modal-panel" role="dialog" aria-modal="true" aria-label="최신 승인본 미리보기">
        <button class="canonical-modal-close" type="button" data-close="1" aria-label="닫기">×</button>
        <div class="canonical-modal-meta"></div>
        <img class="canonical-modal-image" alt="최신 승인본 미리보기" />
      </div>`;
    const style = document.createElement('style');
    style.textContent = `
      #canonical-preview-modal[hidden]{display:none!important}
      #canonical-preview-modal{position:fixed;inset:0;z-index:99999;display:grid;place-items:center;padding:28px}
      .canonical-modal-backdrop{position:absolute;inset:0;background:rgba(0,0,0,.86);backdrop-filter:blur(8px)}
      .canonical-modal-panel{position:relative;z-index:1;width:min(1180px,96vw);max-height:92vh;background:#0b0b0b;border:1px solid rgba(255,255,255,.16);border-radius:14px;overflow:auto;box-shadow:0 30px 100px rgba(0,0,0,.55)}
      .canonical-modal-image{width:100%;height:auto;display:block;background:#111}
      .canonical-modal-meta{padding:14px 54px 12px 18px;font:600 11px/1.4 system-ui,sans-serif;letter-spacing:.12em;text-transform:uppercase;color:#b9b9b9;border-bottom:1px solid rgba(255,255,255,.1)}
      .canonical-modal-close{position:absolute;right:12px;top:8px;z-index:2;border:0;background:transparent;color:#fff;font:300 32px/1 system-ui;cursor:pointer}
      .canonical-authority-badge{position:absolute;left:10px;bottom:10px;z-index:3;padding:6px 8px;border:1px solid rgba(255,255,255,.18);border-radius:999px;background:rgba(5,5,5,.82);backdrop-filter:blur(8px);font:700 9px/1 system-ui,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:#f0eee8;pointer-events:none}
      .canonical-preview-image{width:100%;height:100%;display:block;object-fit:cover;object-position:top;background:#0e0e0e;cursor:zoom-in}
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

  function openCanonical(id, src, authority) {
    const modal = ensureModal();
    modal.querySelector('.canonical-modal-meta').textContent = `${id.toUpperCase()} · LATEST APPROVED · ${authority}`;
    modal.querySelector('.canonical-modal-image').src = src;
    modal.hidden = false;
  }

  function previewHost(article) {
    return article.querySelector('.preview .viewport') || article.querySelector('.viewport') || article.querySelector('.preview');
  }

  function installCanonicalPreview(id, src, authority) {
    const article = document.getElementById(id);
    if (!article) return;
    const host = previewHost(article);
    if (!host) return;

    const resolved = new URL(src, document.baseURI).href;
    host.style.position = 'relative';
    const img = document.createElement('img');
    img.className = 'canonical-preview-image';
    img.src = resolved;
    img.alt = `${id.toUpperCase()} 최신 승인본 화면`;
    img.loading = 'eager';
    img.decoding = 'async';
    img.addEventListener('click', () => openCanonical(id, resolved, authority));
    host.replaceChildren(img);

    const badge = document.createElement('div');
    badge.className = 'canonical-authority-badge';
    badge.textContent = `LATEST APPROVED · ${authority}`;
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
        openCanonical(id, resolved, authority);
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
    Object.entries(AUTHORITIES).forEach(([id, [src, authority]]) => installCanonicalPreview(id, src, authority));
    installB09Blocker();
    document.documentElement.dataset.portfolioPreviewAuthority = 'drive-canonical-20260816';
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
})();
