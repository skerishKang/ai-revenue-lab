(() => {
  'use strict';
  const core = document.querySelector('[data-meaning-core]');
  const nodes = [...document.querySelectorAll('[data-meaning-node]')];
  if (!core || !nodes.length) return;

  const defaults = {
    person: ['서윤', '사람 · 반복해서 떠오르는 창문과 대화'],
    place: ['철길 옆 집', '장소 · 주소보다 계절과 소리로 남은 곳'],
    event: ['비가 멈춘 오후', '사건 · 여러 기억 조각이 한 장면으로 묶인 날'],
    object: ['푸른 찻잔', '물건 · 장소가 바뀌어도 같은 대화를 불러오는 것']
  };

  function activate(node) {
    nodes.forEach(n => n.classList.toggle('is-active', n === node));
    const [title, detail] = defaults[node.dataset.meaningNode] || ['의미 군집', '지금 선택한 기억의 연결'];
    core.querySelector('strong').textContent = title;
    core.querySelector('small').textContent = detail;
    document.querySelector('.pm-field-stage')?.setAttribute('data-focus-node', node.dataset.meaningNode);
  }

  nodes.forEach(node => {
    node.addEventListener('click', () => activate(node));
    node.addEventListener('focus', () => activate(node));
  });
})();