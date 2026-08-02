(() => {
  const calmStyle = document.createElement('link');
  calmStyle.rel = 'stylesheet';
  calmStyle.href = 'styles/hero-v3-1.css';
  document.head.appendChild(calmStyle);

  const heroLabel = document.querySelector('.hero .micro-label');
  if (heroLabel) heroLabel.textContent = '기관·기업 미디어팀을 위한 6주 AI 업무전환 프로그램';
  const primaryHeroAction = document.querySelector('.hero-actions .button--signal');
  if (primaryHeroAction) primaryHeroAction.textContent = '우리 팀 전환안 살펴보기';
  const secondaryHeroAction = document.querySelector('.hero-actions .button--glass');
  if (secondaryHeroAction) secondaryHeroAction.textContent = '프로그램 방식 보기';
  const consoleLabel = document.querySelector('.console-head span');
  if (consoleLabel) consoleLabel.textContent = '조직 전환 미리보기';

  const data = window.PADIEM_V3_DATA;
  const topbar = document.querySelector('[data-topbar]');
  const form = document.querySelector('#transformation-form');
  const teamInput = form?.elements.team;
  const teamOutput = document.querySelector('[data-team-output]');
  const tabs = [...document.querySelectorAll('[data-output-tab]')];
  const stages = [...document.querySelectorAll('[data-output-stage]')];
  let currentBrief = '';

  const setSolidNav = () => topbar?.classList.toggle('is-solid', window.scrollY > window.innerHeight * .72);
  window.addEventListener('scroll', setSolidNav, { passive: true });
  setSolidNav();

  const revealObserver = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (entry.isIntersecting) entry.target.classList.add('is-visible');
    });
  }, { threshold: .12 });
  document.querySelectorAll('.reveal').forEach(el => revealObserver.observe(el));

  const selectStage = name => {
    tabs.forEach(tab => tab.classList.toggle('is-active', tab.dataset.outputTab === name));
    stages.forEach(stage => stage.classList.toggle('is-active', stage.dataset.outputStage === name));
  };
  tabs.forEach(tab => tab.addEventListener('click', () => selectStage(tab.dataset.outputTab)));

  const updateTeam = () => {
    if (teamOutput && teamInput) teamOutput.value = `${teamInput.value}명`;
  };
  teamInput?.addEventListener('input', updateTeam);
  updateTeam();

  const offerFor = ({ team, ai, bottleneck }) => {
    if (Number(team) <= 5 && ai === 'none') return ['A', '진단 워크숍', '현재 업무와 AI 적용 후보를 정리하고 첫 파일럿 범위를 결정합니다.'];
    if (ai === 'partial' && bottleneck !== 'brief') return ['B1', '디자인 파트너 파일럿', '이미 사용 중인 AI 업무를 검토·승인 구조와 연결해 4주 제한 파일럿으로 정리합니다.'];
    return ['B2', '표준 6주 파일럿', '한 팀의 반복 업무를 기준선 측정부터 운영 플레이북까지 전환합니다.'];
  };

  const renderResult = values => {
    const org = data.orgs[values.org];
    const asset = data.assets[values.asset];
    const bottleneck = data.bottlenecks[values.bottleneck];
    const aiLabel = values.ai === 'none' ? 'AI 사용 거의 없음' : values.ai === 'partial' ? '일부 표준화' : '개인별 AI 사용';
    const readiness = Math.min(88, 43 + Number(values.team) + (values.ai === 'partial' ? 16 : values.ai === 'individual' ? 8 : 0));
    const [offerCode, offerTitle, offerDesc] = offerFor(values);

    document.querySelector('[data-result-org]').textContent = `${org} · ${values.team}명`;
    document.querySelector('[data-readiness]').textContent = `전환 준비도 ${readiness}`;
    document.querySelector('[data-result-headline]').textContent = bottleneck.title;
    document.querySelector('[data-result-note]').textContent = `${aiLabel}. ${bottleneck.note}`;
    document.querySelectorAll('.diagnosis-bars i').forEach((bar, index) => bar.style.setProperty('--value', `${bottleneck.scores[index]}%`));
    document.querySelectorAll('.diagnosis-bars b').forEach((score, index) => score.textContent = bottleneck.scores[index]);
    document.querySelector('[data-offer-code]').textContent = offerCode;
    document.querySelector('[data-offer-title]').textContent = offerTitle;
    document.querySelector('[data-offer-desc]').textContent = offerDesc;
    document.querySelector('[data-pilot-task]').textContent = asset;

    currentBrief = [
      `[파디엠 AI 미디어 업무전환 요약]`,
      `조직: ${org} / ${values.team}명`,
      `핵심 업무: ${asset}`,
      `우선 병목: ${bottleneck.title}`,
      `현재 AI 상태: ${aiLabel}`,
      `추천 프로그램: ${offerCode} ${offerTitle}`,
      `전환 흐름: 구조화된 요청서 → AI-assisted 초안 → 근거·권리 확인 → 담당자 검토 → 승인·게시`
    ].join('\n');

    const preview = document.querySelector('[data-brief-preview]');
    if (preview) {
      preview.querySelector('strong').textContent = `${org} · ${asset}`;
      preview.querySelector('p').textContent = `추천: ${offerTitle} · ${bottleneck.title}`;
    }
  };

  form?.addEventListener('submit', event => {
    event.preventDefault();
    const formData = new FormData(form);
    const values = Object.fromEntries(formData.entries());
    values.team = teamInput.value;
    renderResult(values);
    selectStage('diagnosis');
    document.querySelector('[data-studio-output]')?.animate([
      { opacity: .3, transform: 'translateY(10px)' },
      { opacity: 1, transform: 'translateY(0)' }
    ], { duration: 420, easing: 'cubic-bezier(.2,.8,.2,1)' });
  });

  document.querySelector('[data-copy-brief]')?.addEventListener('click', async () => {
    if (!currentBrief) form?.requestSubmit();
    const status = document.querySelector('[data-copy-status]');
    try {
      await navigator.clipboard.writeText(currentBrief);
      status.textContent = '전환안이 복사되었습니다.';
    } catch {
      status.textContent = '브라우저에서 복사가 차단되었습니다. 전환 스튜디오 결과를 직접 선택해 주세요.';
    }
  });

  form?.requestSubmit();
})();
