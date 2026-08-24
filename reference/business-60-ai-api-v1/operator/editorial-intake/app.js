(() => {
  'use strict';

  const core = window.B60EditorialIntake;
  if (!core) return;

  const form = document.getElementById('intake-form');
  const verdictCard = document.getElementById('verdict-card');
  const verdictText = document.getElementById('verdict-text');
  const dispositionText = document.getElementById('disposition-text');
  const issueList = document.getElementById('issue-list');
  const jsonOutput = document.getElementById('json-output');
  const jsOutput = document.getElementById('js-output');
  const mediaOutput = document.getElementById('media-output');
  const mediaPanel = document.getElementById('media-panel');
  const sourceOpen = document.getElementById('source-open');
  const recurringFields = document.querySelector('.recurring-fields');
  const resetButton = document.getElementById('reset-form');

  let lastOutputs = { json: '', opportunityJs: '', mediaJs: '' };

  function formObject() {
    return Object.fromEntries(new FormData(form).entries());
  }

  function setDefaults() {
    const now = new Date();
    form.elements.verifiedAt.value = core.todayKey(now);
    form.elements.observedAt.value = core.kstTimestamp(now);
  }

  function updateSourceLink() {
    const value = form.elements.sourceUrl.value.trim();
    let valid = false;
    try {
      const parsed = new URL(value);
      valid = parsed.protocol === 'http:' || parsed.protocol === 'https:';
    } catch (_) {}
    sourceOpen.classList.toggle('is-disabled', !valid);
    sourceOpen.href = valid ? value : '#';
  }

  function updateRecurringVisibility() {
    const recurring = form.elements.opportunityType.value === 'RECURRING_FREE';
    recurringFields.hidden = !recurring;
  }

  function renderIssues(validation) {
    const groups = [
      ['오류', 'is-error', validation.errors],
      ['보류', 'is-pending', validation.pending],
      ['경고', 'is-warning', validation.warnings]
    ];
    const items = groups.flatMap(([label, className, records]) => records.map(record =>
      `<p class="issue-item ${className}"><b>${label}</b>${escapeHtml(record.message)} <small>${escapeHtml(record.code)}</small></p>`
    ));
    issueList.innerHTML = items.length ? items.join('') : '<p class="muted">Truth Gate 이슈가 없습니다.</p>';
  }

  function escapeHtml(value) {
    return String(value || '').replace(/[&<>"']/g, char => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
    }[char]));
  }

  function renderOutputs(outputs) {
    lastOutputs = outputs;
    const validation = outputs.validation;
    verdictCard.dataset.verdict = validation.verdict;
    verdictText.textContent = validation.verdict;
    dispositionText.textContent = `${validation.disposition} · urgency ${validation.urgencyEligible ? 'eligible' : 'not eligible'}`;
    renderIssues(validation);
    jsonOutput.textContent = outputs.json;
    jsOutput.textContent = outputs.opportunityJs;
    mediaPanel.hidden = !outputs.mediaJs;
    mediaOutput.textContent = outputs.mediaJs;
  }

  function runValidation() {
    const outputs = core.buildOutputs(formObject(), new Date());
    renderOutputs(outputs);
    return outputs;
  }

  async function copyText(key, button) {
    const text = lastOutputs[key] || '';
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      const original = button.textContent;
      button.textContent = '복사됨';
      setTimeout(() => { button.textContent = original; }, 1200);
    } catch (_) {
      const area = document.createElement('textarea');
      area.value = text;
      area.setAttribute('readonly', '');
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.appendChild(area);
      area.select();
      document.execCommand('copy');
      area.remove();
    }
  }

  form.addEventListener('submit', event => {
    event.preventDefault();
    runValidation();
  });

  form.addEventListener('input', event => {
    if (event.target.name === 'sourceUrl') updateSourceLink();
    if (event.target.name === 'opportunityType') updateRecurringVisibility();
  });

  form.addEventListener('change', event => {
    if (event.target.name === 'opportunityType') updateRecurringVisibility();
  });

  document.addEventListener('click', event => {
    const copy = event.target.closest('[data-copy]');
    if (copy) copyText(copy.dataset.copy, copy);
  });

  resetButton.addEventListener('click', () => {
    form.reset();
    setDefaults();
    updateSourceLink();
    updateRecurringVisibility();
    verdictCard.dataset.verdict = 'EMPTY';
    verdictText.textContent = '입력 대기';
    dispositionText.textContent = '아직 후보를 만들지 않았습니다.';
    issueList.innerHTML = '<p class="muted">검증 후 여기에 표시됩니다.</p>';
    jsonOutput.textContent = '{}';
    jsOutput.textContent = '// 검증 후 생성됩니다.';
    mediaOutput.textContent = '';
    mediaPanel.hidden = true;
    lastOutputs = { json: '', opportunityJs: '', mediaJs: '' };
  });

  setDefaults();
  updateSourceLink();
  updateRecurringVisibility();
})();
