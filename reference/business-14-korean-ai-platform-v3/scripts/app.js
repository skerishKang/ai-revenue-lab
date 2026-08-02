(() => {
  const state = {
    view: 'start',
    mode: 'easy',
    compare: new Set(),
    selectedCandidate: 'gemini',
    selectedCredit: 30000,
  };

  const pricing = {
    gemini: { name: 'Gemini 3.1 Pro', input: 2, output: 12 },
    gpt: { name: 'GPT-5.5', input: 5, output: 30 },
    grok: { name: 'Grok 4.5', input: 2, output: 6 },
  };
  const fx = 1380;

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  function showToast(message) {
    const toast = $('#toast');
    toast.textContent = message;
    toast.hidden = false;
    clearTimeout(showToast.timer);
    showToast.timer = setTimeout(() => { toast.hidden = true; }, 1800);
  }

  function setView(view) {
    state.view = view;
    $$('.view').forEach((section) => section.classList.toggle('is-active', section.dataset.view === view));
    $$('[data-view-link]').forEach((button) => button.classList.toggle('is-active', button.dataset.viewLink === view));
    window.scrollTo({ top: 0, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  }

  function setMode(mode) {
    state.mode = mode;
    document.body.dataset.uiMode = mode;
    $$('[data-mode]').forEach((button) => button.classList.toggle('is-active', button.dataset.mode === mode));
    if (mode === 'developer') {
      $('#advanced-options').open = true;
      showToast('개발자 모드: 고급 설정을 표시합니다.');
    } else {
      $('#advanced-options').open = false;
      showToast('간편 모드: 필요한 선택만 표시합니다.');
    }
  }

  function applyPreset(preset) {
    const tasks = {
      document: '긴 한국어 계약서를 핵심 쟁점별로 요약하고, 확인이 필요한 조항을 표시해줘.',
      code: '이 저장소의 로그인 오류를 찾아 수정 계획과 테스트 방법을 한국어로 정리해줘.',
      batch: '고객 문의 2,000건을 주제별로 분류하고 긴급한 문의만 표시해줘.',
      private: '외부 전송 없이 비공개 문서의 개인정보 항목을 찾아줘.',
    };
    $('#task-input').value = tasks[preset];
    $$('[data-preset]').forEach((button) => button.classList.toggle('is-active', button.dataset.preset === preset));
  }

  function selectCandidate(candidate) {
    state.selectedCandidate = candidate;
    $$('.candidate').forEach((button) => button.classList.toggle('is-selected', button.dataset.candidate === candidate));
    const mapping = {
      gemini: ['Gemini 3.1 Pro', '긴 한국어 문서와 정확도 기준', '약 ₩36'],
      grok: ['Grok 4.5', '비용을 줄이면서 일반 작업 수행', '약 ₩24'],
      clova: ['HyperCLOVA X', '국내 처리 선호 · 단가 확인 필요', '가격 확인 필요'],
    };
    $('#selected-model').textContent = mapping[candidate][0];
    $('#selected-reason').textContent = mapping[candidate][1];
    $('#request-estimate').textContent = mapping[candidate][2];
  }

  function previewRoute() {
    const flow = $('#route-flow');
    flow.dataset.state = 'running';
    $('#demo-result').hidden = true;
    setTimeout(() => {
      flow.dataset.state = 'ready';
      flow.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'center' });
      showToast('추천 경로와 예상 비용을 계산했습니다.');
    }, 650);
  }

  function runDemo() {
    $('#demo-result').hidden = false;
    $('#demo-result').scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'nearest' });
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
    $('#model-empty').hidden = visible > 0;
  }

  function updateCompare() {
    const count = state.compare.size;
    $('#compare-count').textContent = String(count);
    $('#open-compare').disabled = count < 2;
  }

  function openCompare() {
    const content = $('#compare-content');
    content.innerHTML = '';
    state.compare.forEach((name) => {
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

  function calculateCost() {
    const model = pricing[$('#calc-model').value];
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

  function formatWon(value) {
    return `₩${Math.round(value).toLocaleString('ko-KR')}`;
  }

  function openCreditDrawer() {
    $('#drawer-backdrop').hidden = false;
    $('#credit-drawer').classList.add('is-open');
    $('#credit-drawer').setAttribute('aria-hidden', 'false');
    $('#close-credit').focus();
  }

  function closeCreditDrawer() {
    $('#credit-drawer').classList.remove('is-open');
    $('#credit-drawer').setAttribute('aria-hidden', 'true');
    setTimeout(() => { $('#drawer-backdrop').hidden = true; }, 220);
  }

  function selectCredit(amount) {
    state.selectedCredit = Number(amount);
    $$('[data-credit]').forEach((button) => button.classList.toggle('is-selected', Number(button.dataset.credit) === state.selectedCredit));
    const fee = state.selectedCredit * .05;
    const rows = $$('.fee-breakdown strong');
    rows[0].textContent = formatWon(state.selectedCredit);
    rows[1].textContent = formatWon(fee);
    rows[2].textContent = formatWon(state.selectedCredit + fee);
  }

  function updateBudget() {
    const value = Number($('#budget-range').value);
    $('#budget-display').textContent = formatWon(value);
    const used = 6160;
    $('#budget-progress').style.width = `${Math.min(100, used / value * 100)}%`;
  }

  function codeFor(language) {
    const samples = {
      python: `from openai import OpenAI\n\nclient = OpenAI(\n    base_url="https://api.business14.kr/v1",\n    api_key=os.environ["BUSINESS14_API_KEY"]\n)\n\nresponse = client.chat.completions.create(\n    model="b14/auto",\n    messages=[{"role": "user", "content": task}],\n    extra_body={"business14": {\n        "optimize_for": "balanced",\n        "budget_krw": 500,\n        "route_scope": "domestic_preferred"\n    }}\n)`,
      typescript: `import OpenAI from "openai";\n\nconst client = new OpenAI({\n  baseURL: "https://api.business14.kr/v1",\n  apiKey: process.env.BUSINESS14_API_KEY\n});\n\nconst response = await client.chat.completions.create({\n  model: "b14/auto",\n  messages: [{ role: "user", content: task }],\n  business14: { budget_krw: 500 }\n});`,
      curl: `curl https://api.business14.kr/v1/chat/completions \\\n  -H "Authorization: Bearer $BUSINESS14_API_KEY" \\\n  -H "Content-Type: application/json" \\\n  -d '{\n    "model": "b14/auto",\n    "messages": [{"role":"user","content":"한국어 문서를 요약해줘"}],\n    "business14": {"budget_krw": 500}\n  }'`,
    };
    return samples[language];
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      showToast('클립보드에 복사했습니다.');
    } catch {
      showToast('복사 권한이 없어 직접 선택해 주세요.');
    }
  }

  $$('[data-view-link]').forEach((button) => button.addEventListener('click', () => setView(button.dataset.viewLink)));
  $$('[data-mode]').forEach((button) => button.addEventListener('click', () => setMode(button.dataset.mode)));
  $$('[data-preset]').forEach((button) => button.addEventListener('click', () => applyPreset(button.dataset.preset)));
  $$('.candidate').forEach((button) => button.addEventListener('click', () => selectCandidate(button.dataset.candidate)));
  $('#preview-route').addEventListener('click', previewRoute);
  $('#run-demo').addEventListener('click', runDemo);

  $('#model-search').addEventListener('input', filterModels);
  $$('#model-filters button').forEach((button) => button.addEventListener('click', () => {
    $$('#model-filters button').forEach((item) => item.classList.toggle('is-active', item === button));
    filterModels();
  }));
  $$('[data-compare]').forEach((input) => input.addEventListener('change', () => {
    if (input.checked) {
      if (state.compare.size >= 3) {
        input.checked = false;
        showToast('비교는 최대 3개까지 가능합니다.');
        return;
      }
      state.compare.add(input.dataset.compare);
    } else {
      state.compare.delete(input.dataset.compare);
    }
    updateCompare();
  }));
  $('#open-compare').addEventListener('click', openCompare);
  $('#open-calculator').addEventListener('click', () => $('#calculator-panel').scrollIntoView({ behavior: 'smooth', block: 'center' }));
  ['calc-model', 'input-tokens', 'output-tokens', 'platform-fee'].forEach((id) => $(`#${id}`).addEventListener('input', calculateCost));

  ['open-credit-drawer', 'plan-topup', 'usage-topup', 'wallet-topup'].forEach((id) => $(`#${id}`)?.addEventListener('click', openCreditDrawer));
  $('#close-credit').addEventListener('click', closeCreditDrawer);
  $('#drawer-backdrop').addEventListener('click', closeCreditDrawer);
  $$('[data-credit]').forEach((button) => button.addEventListener('click', () => selectCredit(button.dataset.credit)));
  $('#demo-payment').addEventListener('click', () => showToast('데모에서는 실제 결제가 진행되지 않습니다.'));

  $('#budget-range').addEventListener('input', updateBudget);
  $('#save-budget').addEventListener('click', () => showToast('월 예산 상한을 데모로 저장했습니다.'));
  $$('[data-plan]').forEach((button) => button.addEventListener('click', () => showToast(`${button.dataset.plan} 관심 상태를 데모로 기록했습니다.`)));
  $$('[data-detail]').forEach((button) => button.addEventListener('click', () => showToast(`${button.dataset.detail} 상세 가격 화면은 다음 단계에서 연결됩니다.`)));

  $$('[data-code]').forEach((button) => button.addEventListener('click', () => {
    $$('[data-code]').forEach((item) => item.classList.toggle('is-active', item === button));
    $('#code-sample code').textContent = codeFor(button.dataset.code);
  }));
  $('#copy-code').addEventListener('click', () => copyText($('#code-sample').innerText));
  $$('[data-copy]').forEach((button) => button.addEventListener('click', () => copyText(button.dataset.copy)));

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      closeCreditDrawer();
      if ($('#compare-dialog').open) $('#compare-dialog').close();
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      setView('models');
      setTimeout(() => $('#model-search').focus(), 30);
    }
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter' && state.view === 'start') {
      event.preventDefault();
      previewRoute();
    }
  });

  document.body.dataset.uiMode = state.mode;
  calculateCost();
  updateBudget();
})();
