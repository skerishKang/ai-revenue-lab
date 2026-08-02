(() => {
  const installStylesheet = () => {
    if (document.querySelector('link[data-business14-visual="v3.2"]')) return;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = 'styles/v32.css';
    link.dataset.business14Visual = 'v3.2';
    document.head.append(link);
  };

  const applyLayout = () => {
    document.body.dataset.visualVersion = 'v3.2';
    const theme = document.querySelector('meta[name="theme-color"]');
    if (theme) theme.content = '#f8fafc';

    const brandSubtitle = document.querySelector('.brand small');
    if (brandSubtitle) brandSubtitle.textContent = 'Korean AI Gateway';

    const statusLine = document.querySelector('.status-line');
    if (statusLine) {
      const dot = statusLine.querySelector('.status-dot');
      statusLine.replaceChildren();
      if (dot) statusLine.append(dot);
      statusLine.append(document.createTextNode(' 개인용 베타 · 16개 대표 모델 · 가격 스냅샷'));
    }

    const paygCard = [...document.querySelectorAll('.plan-card')]
      .find((card) => card.querySelector('h2')?.textContent.trim() === 'Pay as you go');
    if (paygCard && !paygCard.querySelector('.payg-meter')) {
      const meter = document.createElement('div');
      meter.className = 'payg-meter';
      meter.setAttribute('aria-label', '종량제 사용 예시');
      meter.innerHTML = `
        <div><span>예시 충전</span><strong>₩30,000</strong><small>모델 사용 크레딧</small></div>
        <div><span>플랫폼 비용</span><strong>5% 예시</strong><small>결제 전에 분리 표시</small></div>
        <div><span>예상 사용량</span><strong>약 880회</strong><small>Gemini 3.6 Flash 예시 요청 기준</small></div>`;
      const action = paygCard.querySelector('button');
      paygCard.insertBefore(meter, action || null);
    }
  };

  installStylesheet();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', applyLayout, { once: true });
  } else {
    applyLayout();
  }
})();
