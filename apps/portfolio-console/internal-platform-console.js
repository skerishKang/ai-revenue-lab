/* Internal Platform view — separate from Business numbering. */
(function () {
  "use strict";

  var platforms = Array.isArray(window.ARL_INTERNAL_PLATFORMS) ? window.ARL_INTERNAL_PLATFORMS : [];
  var active = false;
  var lastFocused = null;
  var languageObserver = null;
  var headerObserver = null;

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function lang() {
    return document.documentElement.lang === "en" ? "en" : "ko";
  }

  function text(ko, en) {
    return lang() === "en" ? en : ko;
  }

  function ensureStylesheet() {
    if (document.querySelector('link[data-internal-platform-style]')) return;
    var link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "./internal-platform.css?v=internal-platform-20260903-1";
    link.setAttribute("data-internal-platform-style", "true");
    document.head.appendChild(link);
  }

  function ensureNav() {
    var nav = document.querySelector(".view-nav");
    if (!nav || nav.querySelector('[data-view="platform"]')) return;
    var button = document.createElement("button");
    button.className = "view-nav-item";
    button.type = "button";
    button.dataset.view = "platform";
    button.innerHTML = '<span aria-hidden="true">◇</span><span class="nav-label" data-label-ko="내부 플랫폼" data-label-en="INTERNAL PLATFORM">내부 플랫폼</span>';
    nav.appendChild(button);
  }

  function ensureView() {
    if (document.querySelector("#view-platform")) return;
    var main = document.querySelector(".main-panel");
    var footer = main && main.querySelector(".site-footer");
    if (!main || !footer) return;

    var section = document.createElement("section");
    section.className = "view-container";
    section.id = "view-platform";
    section.hidden = true;
    section.setAttribute("aria-label", "내부 플랫폼");
    section.innerHTML = [
      '<p class="ip-intro" id="ip-intro"></p>',
      '<div class="ip-toolbar">',
      '  <label class="ip-search-field">',
      '    <span class="ip-search-label" id="ip-search-label">검색</span>',
      '    <input id="ip-search-input" type="search" autocomplete="off">',
      '  </label>',
      '  <div class="dialog-links">',
      '    <a class="dialog-link" href="https://github.com/skerishKang/ai-revenue-lab/blob/main/docs/internal-platform/INTERNAL_PLATFORM_REGISTRY.md" target="_blank" rel="noopener noreferrer">Registry</a>',
      '    <a class="dialog-link" href="https://github.com/skerishKang/ai-revenue-lab/blob/main/docs/internal-platform/AI_ADOPTION_PLAYBOOK.md" target="_blank" rel="noopener noreferrer">AI Adoption Playbook</a>',
      '  </div>',
      '</div>',
      '<div class="ip-list" id="ip-list"></div>'
    ].join("");
    main.insertBefore(section, footer);
  }

  function ensureDialog() {
    if (document.querySelector("#internal-platform-dialog")) return;
    var dialog = document.createElement("dialog");
    dialog.id = "internal-platform-dialog";
    dialog.className = "project-dialog";
    dialog.setAttribute("aria-labelledby", "ip-dialog-title");
    dialog.innerHTML = [
      '<div class="dialog-scroll">',
      '  <div class="dialog-header">',
      '    <h2 id="ip-dialog-title" class="dialog-title">Internal Platform</h2>',
      '    <button type="button" class="dialog-close-btn" id="ip-dialog-close-btn" aria-label="닫기">×</button>',
      '  </div>',
      '  <div class="dialog-body" id="ip-dialog-body"></div>',
      '</div>'
    ].join("");
    document.body.appendChild(dialog);
  }

  function statusLabel(status) {
    if (status === "active-development") return text("개발 중", "ACTIVE DEVELOPMENT");
    if (status === "maintenance") return text("유지보수", "MAINTENANCE");
    return status || "—";
  }

  function roleOf(item) {
    return lang() === "en" ? item.roleEn : item.roleKo;
  }

  function currentWorkOf(item) {
    return lang() === "en" ? item.currentWorkEn : item.currentWorkKo;
  }

  function filteredPlatforms() {
    var input = document.querySelector("#ip-search-input");
    var query = (input ? input.value : "").trim().toLowerCase();
    if (!query) return platforms.slice();
    return platforms.filter(function (item) {
      var haystack = [
        item.id,
        item.name,
        item.koreanName,
        item.sourcePath,
        item.runtime,
        item.roleKo,
        item.roleEn,
        currentWorkOf(item),
        (item.owns || []).join(" "),
        (item.dependencies || []).join(" "),
        (item.consumers || []).join(" ")
      ].join(" ").toLowerCase();
      return haystack.indexOf(query) !== -1;
    });
  }

  function updatePlatformCopy() {
    var intro = document.querySelector("#ip-intro");
    var searchLabel = document.querySelector("#ip-search-label");
    var searchInput = document.querySelector("#ip-search-input");
    if (intro) {
      intro.textContent = text(
        "Business 번호와 분리된 Padiem 공통 인프라입니다. AI 기능을 새로 만들기 전에 여기서 Core · Engine · Control Plane 소유 경계를 먼저 확인하세요.",
        "Shared Padiem infrastructure kept separate from Business numbering. Check Core, Engine, and Control Plane ownership here before adding new AI capability."
      );
    }
    if (searchLabel) searchLabel.textContent = text("검색", "SEARCH");
    if (searchInput) searchInput.placeholder = text("ID, 이름, 소스 경로, 역할, 현재 작업 검색", "Search ID, name, source path, role, or current work");
  }

  function setHeaderCount(count) {
    if (!active) return;
    var badge = document.querySelector("#header-count");
    if (badge) badge.textContent = "IP " + count;
  }

  function expectedHeader() {
    return text("내부 플랫폼 관리", "Internal Platform");
  }

  function setPlatformHeader() {
    if (!active) return;
    var prefix = document.querySelector("#header-prefix");
    var expected = expectedHeader();
    if (prefix && prefix.textContent !== expected) prefix.textContent = expected;
    setHeaderCount(filteredPlatforms().length);
  }

  function restoreDefaultHeader() {
    var prefix = document.querySelector("#header-prefix");
    if (!prefix) return;
    var attribute = lang() === "en" ? "data-prefix-en" : "data-prefix-ko";
    prefix.textContent = prefix.getAttribute(attribute) || text("내 비즈니스 관리", "Business Operations");
  }

  function render() {
    var list = document.querySelector("#ip-list");
    if (!list) return;
    var visible = filteredPlatforms();
    if (!visible.length) {
      list.innerHTML = '<div class="ip-empty">' + esc(text("일치하는 내부 플랫폼이 없습니다.", "No matching Internal Platform component.")) + '</div>';
      setHeaderCount(0);
      return;
    }

    list.innerHTML = visible.map(function (item) {
      return [
        '<article class="ip-item" data-platform-id="' + esc(item.id) + '" tabindex="0" aria-label="' + esc(item.name) + '">',
        '  <span class="ip-id">' + esc(item.id) + '</span>',
        '  <div class="ip-title-group">',
        '    <span class="ip-title">' + esc(item.name) + '</span>',
        '    <span class="ip-korean">' + esc(item.koreanName) + '</span>',
        '    <span class="ip-role">' + esc(roleOf(item)) + '</span>',
        '  </div>',
        '  <div class="ip-source-group">',
        '    <span class="ip-source-label">' + esc(text("소스 권위", "SOURCE AUTHORITY")) + '</span>',
        '    <span class="ip-source">' + esc(item.sourcePath) + '</span>',
        '  </div>',
        '  <span class="status-badge phase-ip ip-status">' + esc(statusLabel(item.status)) + '</span>',
        '</article>'
      ].join("");
    }).join("");

    list.querySelectorAll(".ip-item").forEach(function (card) {
      function open() { openDialog(card.dataset.platformId); }
      card.addEventListener("click", open);
      card.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          open();
        }
      });
    });
    setHeaderCount(visible.length);
  }

  function listHtml(values) {
    if (!Array.isArray(values) || !values.length) return "—";
    return '<ul class="ip-dialog-list">' + values.map(function (value) {
      return '<li>' + esc(value) + '</li>';
    }).join("") + '</ul>';
  }

  function row(label, value) {
    return '<div class="dialog-section"><span class="dialog-section-label">' + esc(label) + '</span><span class="dialog-section-value">' + value + '</span></div>';
  }

  function openDialog(id) {
    var item = platforms.find(function (candidate) { return candidate.id === id; });
    var dialog = document.querySelector("#internal-platform-dialog");
    var body = document.querySelector("#ip-dialog-body");
    var title = document.querySelector("#ip-dialog-title");
    if (!item || !dialog || !body || !title) return;

    lastFocused = document.activeElement;
    title.textContent = item.id + " · " + item.name;
    var currentIssue = item.currentIssue
      ? '<a class="dialog-link" href="' + esc(item.currentIssue.url) + '" target="_blank" rel="noopener noreferrer">' + esc(item.currentIssue.label) + '</a>'
      : "—";

    body.innerHTML = [
      '<div class="dialog-biznumber">' + esc(item.id) + '</div>',
      '<div class="dialog-name">' + esc(item.name) + '</div>',
      '<div class="dialog-korean">' + esc(item.koreanName) + '</div>',
      '<hr class="dialog-divider">',
      row(text("구분", "TYPE"), esc(text("내부 플랫폼 — Business 번호 없음", "Internal Platform — no Business number"))),
      row(text("역할", "ROLE"), esc(roleOf(item))),
      row(text("런타임", "RUNTIME"), esc(item.runtime)),
      row(text("저장소", "REPOSITORY"), esc(item.repository)),
      row(text("소스 경로", "SOURCE PATH"), '<code>' + esc(item.sourcePath) + '</code>'),
      row(text("소유", "OWNS"), listHtml(item.owns)),
      row(text("소유하지 않음", "DOES NOT OWN"), listHtml(item.doesNotOwn)),
      row(text("의존성", "DEPENDENCIES"), listHtml(item.dependencies)),
      row(text("사용 제품/통합", "CONSUMERS / INTEGRATIONS"), listHtml(item.consumers)),
      row(text("현재 작업", "CURRENT WORK"), esc(currentWorkOf(item))),
      row(text("현재 이슈", "CURRENT ISSUE"), currentIssue),
      '<hr class="dialog-divider">',
      '<div class="dialog-links">',
      '  <a class="dialog-link" href="' + esc(item.sourceUrl) + '" target="_blank" rel="noopener noreferrer">' + esc(text("소스 열기", "OPEN SOURCE")) + '</a>',
      '  <a class="dialog-link" href="' + esc(item.authorityDocUrl) + '" target="_blank" rel="noopener noreferrer">' + esc(text("권위 문서", "AUTHORITY DOC")) + '</a>',
      '</div>'
    ].join("");

    dialog.showModal();
    document.body.style.overflow = "hidden";
    var closeButton = document.querySelector("#ip-dialog-close-btn");
    if (closeButton) closeButton.focus();
  }

  function closeDialog() {
    var dialog = document.querySelector("#internal-platform-dialog");
    if (!dialog || !dialog.open) return;
    dialog.close();
    document.body.style.overflow = "";
    if (lastFocused && typeof lastFocused.focus === "function") lastFocused.focus();
  }

  function closeDrawer() {
    var sidebar = document.querySelector("#sidebar");
    var overlay = document.querySelector("#drawer-overlay");
    if (sidebar) sidebar.classList.remove("is-open");
    if (overlay) overlay.classList.remove("is-visible");
  }

  function showPlatformView() {
    active = true;
    document.querySelectorAll(".view-container").forEach(function (view) { view.hidden = true; });
    var platformView = document.querySelector("#view-platform");
    if (platformView) platformView.hidden = false;
    document.querySelectorAll(".view-nav-item").forEach(function (button) {
      var selected = button.dataset.view === "platform";
      button.classList.toggle("is-active", selected);
      if (selected) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    updatePlatformCopy();
    render();
    setPlatformHeader();
    closeDrawer();
  }

  function leavePlatformView() {
    if (!active) return;
    active = false;
    var platformView = document.querySelector("#view-platform");
    if (platformView) platformView.hidden = true;
    restoreDefaultHeader();
  }

  function schedulePlatformResync() {
    if (!active) return;
    window.requestAnimationFrame(function () {
      if (!active) return;
      showPlatformView();
      window.requestAnimationFrame(setPlatformHeader);
    });
  }

  function installObservers() {
    if (!languageObserver) {
      languageObserver = new MutationObserver(function () {
        schedulePlatformResync();
      });
      languageObserver.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["lang"]
      });
    }

    var prefix = document.querySelector("#header-prefix");
    if (prefix && !headerObserver) {
      headerObserver = new MutationObserver(function () {
        if (!active) return;
        var expected = expectedHeader();
        if (prefix.textContent !== expected) prefix.textContent = expected;
      });
      headerObserver.observe(prefix, {
        childList: true,
        characterData: true,
        subtree: true
      });
    }
  }

  function bindEvents() {
    var platformButton = document.querySelector('[data-view="platform"]');
    if (platformButton) platformButton.addEventListener("click", showPlatformView);

    document.querySelectorAll('.view-nav-item:not([data-view="platform"])').forEach(function (button) {
      button.addEventListener("click", leavePlatformView);
    });

    var input = document.querySelector("#ip-search-input");
    if (input) input.addEventListener("input", render);

    var closeButton = document.querySelector("#ip-dialog-close-btn");
    if (closeButton) closeButton.addEventListener("click", closeDialog);

    var dialog = document.querySelector("#internal-platform-dialog");
    if (dialog) {
      dialog.addEventListener("click", function (event) {
        if (event.target === dialog) closeDialog();
      });
      dialog.addEventListener("close", function () {
        document.body.style.overflow = "";
      });
    }

    window.addEventListener("resize", function () {
      if (!active) return;
      window.requestAnimationFrame(setPlatformHeader);
    });
  }

  function init() {
    ensureStylesheet();
    ensureNav();
    ensureView();
    ensureDialog();
    updatePlatformCopy();
    render();
    bindEvents();
    installObservers();
  }

  document.addEventListener("DOMContentLoaded", init);
  if (document.readyState !== "loading") init();
})();
