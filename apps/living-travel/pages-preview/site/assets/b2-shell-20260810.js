(function () {
  'use strict';

  var script = document.currentScript;
  if (!script) return;

  var siteRoot = new URL('../', script.src);
  var header = document.querySelector('.lt-topbar');
  if (!header) return;

  var brand = header.querySelector('.lt-wordmark');
  var nav = header.querySelector('.lt-nav');
  if (!brand || !nav) return;

  function url(rel) { return new URL(rel, siteRoot).href; }
  function here(name) { return window.location.pathname.toLowerCase().endsWith(name.toLowerCase()); }

  brand.href = url('index.html');
  brand.setAttribute('aria-label', 'Living Travel 홈');

  /*
   * New place-led customer surfaces still load this external script so the
   * repository's CSP/persistent-shell contract remains real and testable.
   * They deliberately own their own bounded customer navigation, however.
   * In preserve-page-nav mode the shell may normalize the home link and mark
   * itself ready, but it must not replace page navigation or inject operator
   * / editor controls into the participant experience.
   */
  var preservePageNav = document.body && document.body.getAttribute('data-shell-mode') === 'preserve-page-nav';
  if (preservePageNav) {
    header.classList.add('lt-topbar--persistent');
    document.documentElement.classList.add('lt-shell-ready', 'lt-shell-local-nav');
    return;
  }

  var active = 'edition';
  if (here('/guide.html')) active = 'guide';
  else if (here('/preferences.html') || here('/intro.html') || here('/generation.html') || here('/pending.html') || here('/traveler/enter.html')) active = 'taste';
  else if (here('/history.html')) active = 'archive';
  else if (here('/index.html') || window.location.pathname === '/' || window.location.pathname.endsWith('/')) active = 'home';

  var items = [
    { key: 'guide', label: '30초 사용법', href: 'guide.html', guide: true },
    { key: 'taste', label: '취향', href: 'demo/preferences.html' },
    { key: 'edition', label: '현재 여행판', href: 'demo/traveler-home.html' },
    { key: 'archive', label: '기록', href: 'demo/history.html' },
    { key: 'operator', label: '편집실', href: 'operator/login.html', utility: true }
  ];

  nav.classList.add('lt-nav--persistent');
  nav.setAttribute('aria-label', 'Living Travel 주요 메뉴');
  nav.innerHTML = '';

  items.forEach(function (item) {
    var a = document.createElement('a');
    a.href = url(item.href);
    a.textContent = item.label;
    a.className = 'lt-shell-link' + (item.guide ? ' is-guide' : '') + (item.utility ? ' is-utility' : '');
    a.dataset.shellKey = item.key;
    if (item.key === active) {
      a.classList.add('is-active');
      a.setAttribute('aria-current', 'page');
    }
    if (item.guide) a.setAttribute('data-product-guide', 'true');
    nav.appendChild(a);
  });

  header.classList.add('lt-topbar--persistent');
  document.documentElement.classList.add('lt-shell-ready');
})();