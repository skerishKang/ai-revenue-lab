(() => {
  const run = () => {
    const $ = (selector, root = document) => root.querySelector(selector);
    const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
    const compareState = new Set();
    const pricing = window.B14CatalogV31.pricing;
    const fx = 1380;

    function toast(message) {
      const node = $('#toast');
      if (!node) return;
      node.textContent = message;
      node.hidden = false;
      clearTimeout(toast.timer);
      toast.timer = setTimeout(() => { node.hidden = true; }, 1800);
    }

    function selectCandidate(candidate) {
      $$('.candidate').forEach((button) => button.classList.toggle('is-selected', button.dataset.candidate === candidate));
      const mapping = {
        'gpt-terra': ['GPT-5.6 Terra', '최신 세대의 품질·가격 균형', '약 ₩62'],
        sonnet: ['Claude Sonnet 5', '한국어 문서와 에이전트 작업', '약 ₩45'],
        'gemini-flash': ['Gemini 3.6 Flash', '빠른 멀티모달·에이전트 실행', '약 ₩34'],
        clova: ['HyperCLOVA X THINK', '국내 처리 선호 · 상품 단가 확인 필요', '가격 확인 필요'],
      };
      const value = mapping[candidate];
      if (!value) return;
      $('#selected-model').textContent = value[0];
      $('#selected-reason').textContent = value[1];
      $('#request-estimate').textContent = value[2];
    }

    function sortModels() {
      const select = $('#model-sort');
      if (!select) return;
      const table = $('#model-table');
      const rows = $$('.model-price-row', table);
      const compare = {
        rank: (a, b) => Number(a.dataset.rank) - Number(b.dataset.rank),
        newest: (a, b) => Number(b.dataset.released) - Number(a.dataset.released),
        price: (a, b) => Number(a.dataset.price) - Number(b.dataset.price),
        context: (a, b) => Number(b.dataset.context) - Number(a.dataset.context),
        provider: (a, b) => a.dataset.provider.localeCompare(b.dataset.provider, 'ko'),
      }[select.value];
      rows.sort(compare).forEach((row) => table.append(row));
    }

    function filterModels() {
      const query = $('#model-search').value.trim().toLowerCase();
      const active = $('#model-filters .is-active')?.dataset.filter || 'all';
      let visible = 0;
      $$('.model-price-row').forEach((row) => {
        const matchesQuery = !query || row.textContent.toLowerCase().includes(query);
        const matchesFilter = active === 'all' || row.dataset.tags.split(' ').includes(active);
        row.hidden = !(matchesQuery && matchesFilter);
        if (!row.hidden) visible += 1;
      });
      sortModels();
      $('#model-empty').hidden = visible > 0;
    }

    function updateCompare() {
      $('#compare-count').textContent = String(compareState.size);
      $('#open-compare').disabled = compareState.size < 2;
    }

    function openCompare() {
      const content = $('#compare-content');
      content.innerHTML = '';
      compareState.forEach((name) => {
        const row = $(`[data-compare="${CSS.escape(name)}"]`)?.closest('.model-price-row');
        if (!row) return;
        const prices = $$('.unit-price strong, .request-price strong', row).map((el) => el.textContent);
        const card = document.createElement('div');
        card.className = 'compare-card';
        card.innerHTML = `<div><strong>${name}</strong><small>${$('.use-case strong', row)?.textContent || ''}</small></div><div><small>입력 / 1M</small><strong>${prices[0] || '—'}</strong></div><div><small>출력 / 1M</small><strong>${prices[1] || '—'}</strong></div><div><small>예상 요청</small><strong>${prices[2] || '—'}</strong></div>`;
        content.append(card);
      });
      $('#compare-dialog').showModal();
    }

    function formatWon(value) { return `₩${Math.round(value).toLocaleString('ko-KR')}`; }

    function calculateCost() {
      const model = pricing[$('#calc-model').value];
      if (!model) return;
      const inputTokens = Math.max(0, Number($('#input-tokens').value) || 0);
      const outputTokens = Math.max(0, Number($('#output-tokens').value) || 0);
      const feeRate = Math.max(0, Number($('#platform-fee').value) || 0) / 100;
      const providerUsd = (inputTokens / 1_000_000) * model.input + (outputTokens / 1_000_000) * model.output;
      const providerKrw = providerUsd * fx;
      const fee = providerKrw * feeRate;
      $('#provider-cost').textContent = formatWon(providerKrw);
      $('#fee-cost').textContent = formatWon(fee);
      $('#total-cost').textContent = formatWon(providerKrw + fee);
    }

    function replaceControl(id) {
      const node = $(`#${id}`);
      if (!node) return null;
      const clone = node.cloneNode(true);
      node.replaceWith(clone);
      return clone;
    }

    window.B14CatalogV31.install();

    $$('.candidate').forEach((button) => button.addEventListener('click', () => selectCandidate(button.dataset.candidate)));
    $('#model-search').addEventListener('input', filterModels);
    $$('#model-filters button').forEach((button) => button.addEventListener('click', () => {
      $$('#model-filters button').forEach((item) => item.classList.toggle('is-active', item === button));
      filterModels();
    }));
    $('#model-sort').addEventListener('change', filterModels);
    $$('[data-compare]').forEach((input) => input.addEventListener('change', () => {
      if (input.checked) {
        if (compareState.size >= 3) { input.checked = false; toast('비교는 최대 3개까지 가능합니다.'); return; }
        compareState.add(input.dataset.compare);
      } else compareState.delete(input.dataset.compare);
      updateCompare();
    }));
    $('#open-compare').addEventListener('click', openCompare);
    $('#open-calculator').addEventListener('click', () => $('#calculator-panel').scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'center' }));
    $$('[data-detail]').forEach((button) => button.addEventListener('click', () => toast(`${button.dataset.detail} 상세 모델 화면은 Router Core 카탈로그 단계에서 연결됩니다.`)));

    ['calc-model', 'input-tokens', 'output-tokens', 'platform-fee'].forEach((id) => replaceControl(id));
    ['calc-model', 'input-tokens', 'output-tokens', 'platform-fee'].forEach((id) => $(`#${id}`).addEventListener('input', calculateCost));
    calculateCost();
    filterModels();
  };

  (window.B14CatalogReady || Promise.resolve())
    .then(run)
    .catch(() => {
      const toast = document.querySelector('#toast');
      if (toast) {
        toast.textContent = '모델 카탈로그를 초기화하지 못했습니다.';
        toast.hidden = false;
      }
    });
})();