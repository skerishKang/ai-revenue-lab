(() => {
  const signals = window.B60_ACCESS_SIGNALS || [];
  const signalSection = document.getElementById('signal');
  const sourceSection = document.getElementById('source');
  if (!signals.length || !signalSection || !sourceSection) return;

  const explore = document.createElement('section');
  explore.className = 'explore';
  explore.id = 'explore';
  explore.innerHTML = `
    <div class="explore-shell">
      <div class="explore-kicker"><i></i> VERIFIED ACCESS INDEX · 2026-08-23</div>
      <div class="explore-head">
        <h2>영화가 끝나면,<br>진짜 쓸 수 있는 길만 남깁니다.</h2>
        <p>무료·크레딧·라우터·플레이그라운드·API를 한 화면에서 비교합니다. 광고 문구와 공식 확인 사실은 섞지 않습니다.</p>
      </div>
      <div class="explore-toolbar">
        <div class="explore-tabs" role="tablist" aria-label="AI API discovery views">
          <button class="explore-tab is-active" type="button" data-view="now">NOW</button>
          <button class="explore-tab" type="button" data-view="expiring">EXPIRING</button>
          <button class="explore-tab" type="button" data-view="models">MODELS</button>
          <button class="explore-tab" type="button" data-view="access">ACCESS</button>
        </div>
        <label class="explore-search"><input id="signal-search" type="search" placeholder="provider / model / access" autocomplete="off"></label>
      </div>
      <div class="explore-stats" id="explore-stats"></div>
      <div class="signal-grid-v6" id="signal-grid-v6"></div>
    </div>`;
  sourceSection.before(explore);

  const drawer = document.createElement('aside');
  drawer.className = 'signal-drawer-v6';
  drawer.setAttribute('aria-hidden','true');
  drawer.innerHTML = '<button class="drawer-close" type="button" aria-label="Close details">×</button><div id="drawer-body"></div>';
  document.body.appendChild(drawer);

  const grid = document.getElementById('signal-grid-v6');
  const stats = document.getElementById('explore-stats');
  const search = document.getElementById('signal-search');
  let view = 'now';

  const esc = (s='') => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  const searchable = s => [s.provider,s.title,s.model,s.summary,...(s.access||[])].join(' ').toLowerCase();
  const visibleSignals = () => {
    const q = search.value.trim().toLowerCase();
    return signals.filter(s => !q || searchable(s).includes(q));
  };

  function renderStats(list){
    const official = list.filter(s=>s.verification==='VERIFIED_OFFICIAL_WEB').length;
    const free = list.filter(s=>/FREE/.test(s.dealType)||/free/i.test(s.freeLabel)||/credit/i.test(s.freeLabel)).length;
    const providers = new Set(list.map(s=>s.provider)).size;
    stats.innerHTML = `<span><b>${list.length}</b> signals</span><span><b>${providers}</b> providers</span><span><b>${official}</b> official</span><span><b>${free}</b> free/credit paths</span>`;
  }

  function card(s,index){
    return `<article class="access-card ${index===0?'is-featured':''}" tabindex="0" role="button" data-id="${esc(s.id)}" aria-label="Open ${esc(s.title)} details">
      <div class="card-top"><span class="card-provider">${esc(s.provider)}</span><span class="verify-pill">OFFICIAL</span></div>
      <h3>${esc(s.title)}</h3>
      <p>${esc(s.summary)}</p>
      <strong class="card-free">${esc(s.freeLabel)}</strong>
      <div class="card-meta">${(s.access||[]).map(x=>`<span>${esc(x)}</span>`).join('')}<span>${esc(s.dealType)}</span></div>
      <span class="card-arrow">↗</span>
    </article>`;
  }

  function renderNow(list){
    grid.innerHTML = list.map(card).join('') || '<div class="expiring-empty"><h3>검색 결과가 없습니다.</h3><p>다른 provider/model/access 키워드로 검색해보세요.</p></div>';
  }

  function renderExpiring(list){
    const verifiedExpiring = list.filter(s=>s.expiresAt && s.expiryVerification==='VERIFIED_OFFICIAL_WEB');
    const pending = list.filter(s=>s.pending);
    if (verifiedExpiring.length) {
      grid.innerHTML = verifiedExpiring.map(card).join('');
      return;
    }
    grid.innerHTML = `<div class="expiring-empty">
      <div><span class="explore-kicker">TRUTH-FIRST EXPIRY</span><h3>현재 공식 확인된 종료 임박 signal은 없습니다.</h3></div>
      <div><p>종료일을 추측해서 카운트다운하지 않습니다. 1차 출처로 확인된 순간에만 EXPIRING에 올립니다.</p>
      ${pending.map(s=>`<div class="pending-signal"><b>${esc(s.provider)}</b><br>${esc(s.pending.label)}<br><span>${esc(s.pending.state)}</span></div>`).join('')}</div>
    </div>`;
  }

  function renderModels(list){
    const rows = list.filter(s=>s.model).map(s=>`<div class="model-row" tabindex="0" role="button" data-id="${esc(s.id)}">
      <strong>${esc(s.model)}</strong><span>${esc(s.provider)}</span><span>${esc(s.context)}</span><span>${esc(s.price)}</span><em>${esc(s.freeLabel)}</em>
    </div>`).join('');
    grid.innerHTML = rows || '<div class="expiring-empty"><h3>모델 결과가 없습니다.</h3><p>검색어를 지워보세요.</p></div>';
  }

  function renderAccess(list){
    const groups = new Map();
    list.forEach(s => (s.access||[]).forEach(a => {
      if(!groups.has(a)) groups.set(a,[]);
      groups.get(a).push(s);
    }));
    grid.innerHTML = [...groups.entries()].map(([method,items])=>`<article class="access-lane">
      <small>ACCESS METHOD</small><h3>${esc(method)}</h3><p>${items.length}개의 검증된 경로가 현재 이 방식으로 접근 가능합니다.</p>
      <ul>${items.map(s=>`<li data-id="${esc(s.id)}">${esc(s.provider)} · ${esc(s.freeLabel)}</li>`).join('')}</ul>
    </article>`).join('');
  }

  function render(){
    const list = visibleSignals();
    renderStats(list);
    if(view==='expiring') renderExpiring(list);
    else if(view==='models') renderModels(list);
    else if(view==='access') renderAccess(list);
    else renderNow(list);
  }

  function openDrawer(id){
    const s = signals.find(x=>x.id===id);
    if(!s) return;
    const sources = (s.sources||[]).map(src=>`<a class="drawer-source" href="${esc(src.url)}" target="_blank" rel="noopener noreferrer">${esc(src.label)} ↗</a>`).join('');
    const pending = s.pending ? `<div class="drawer-pending"><b>${esc(s.pending.state)}</b><br>${esc(s.pending.label)}<br>${esc(s.pending.note)}</div>` : '';
    document.getElementById('drawer-body').innerHTML = `
      <div class="drawer-provider">${esc(s.provider)} · ${esc(s.verification)} · VERIFIED ${esc(s.verifiedAt)}</div>
      <h3>${esc(s.title)}</h3>
      <p>${esc(s.summary)}</p>
      <strong class="drawer-free">${esc(s.freeLabel)}</strong>
      <div class="card-meta">${(s.access||[]).map(x=>`<span>${esc(x)}</span>`).join('')}</div>
      <ul class="drawer-facts">${(s.facts||[]).map(f=>`<li>${esc(f)}</li>`).join('')}</ul>
      ${pending}
      ${sources}`;
    drawer.classList.add('is-open');
    drawer.setAttribute('aria-hidden','false');
  }

  grid.addEventListener('click', e=>{
    const target = e.target.closest('[data-id]');
    if(target) openDrawer(target.dataset.id);
  });
  grid.addEventListener('keydown', e=>{
    if((e.key==='Enter'||e.key===' ') && e.target.closest('[data-id]')) { e.preventDefault(); openDrawer(e.target.closest('[data-id]').dataset.id); }
  });
  drawer.querySelector('.drawer-close').addEventListener('click',()=>{drawer.classList.remove('is-open');drawer.setAttribute('aria-hidden','true')});
  addEventListener('keydown',e=>{if(e.key==='Escape'){drawer.classList.remove('is-open');drawer.setAttribute('aria-hidden','true')}});
  search.addEventListener('input',render);
  document.querySelectorAll('.explore-tab').forEach(btn=>btn.addEventListener('click',()=>{
    document.querySelectorAll('.explore-tab').forEach(b=>b.classList.remove('is-active'));
    btn.classList.add('is-active'); view=btn.dataset.view; render();
  }));

  const headerNav = document.querySelector('.shell nav');
  if(headerNav){
    headerNav.innerHTML = '<a href="#explore">NOW</a><a href="#explore" data-jump-view="expiring">EXPIRING</a><a href="#explore" data-jump-view="models">MODELS</a><a href="#explore" data-jump-view="access">ACCESS</a>';
    headerNav.querySelectorAll('[data-jump-view]').forEach(a=>a.addEventListener('click',()=>{
      const target = document.querySelector(`.explore-tab[data-view="${a.dataset.jumpView}"]`); if(target) target.click();
    }));
  }

  render();
})();
