/* B66 three-pane shell.
   Presentation-only orchestration: moves existing authoritative controls/preview
   without cloning business logic or creating a second quote input path. */
(function () {
  "use strict";

  var PREVIEW_MIN = 300;
  var PREVIEW_MAX = 1000;
  var MOBILE_BREAKPOINT = 900;

  function byId(id) { return document.getElementById(id); }

  function clickExisting(id) {
    var node = byId(id);
    if (node && typeof node.click === "function") node.click();
  }

  function makeButton(id, icon, title, note) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "shell-rail-item";
    button.id = id;
    button.innerHTML =
      '<span class="shell-rail-icon" aria-hidden="true">' + icon + '</span>' +
      '<span><strong>' + title + '</strong>' +
      (note ? '<small>' + note + '</small>' : '') +
      '</span>';
    return button;
  }

  function buildRail(shell) {
    var rail = document.createElement("aside");
    rail.className = "shell-rail";
    rail.id = "shellRail";
    rail.setAttribute("aria-label", "견적 메뉴");

    var menu = document.createElement("div");
    menu.className = "shell-rail-menu";

    var newSection = document.createElement("section");
    newSection.className = "shell-rail-section";
    newSection.innerHTML =
      '<h2>새 견적 · 템플릿</h2>' +
      '<div class="shell-template-current">' +
      '<span class="shell-rail-icon" aria-hidden="true">▤</span>' +
      '<span><strong>배정된 템플릿으로 만들기</strong>' +
      '<small id="shellTemplateName">로그인 후 템플릿을 불러옵니다</small></span>' +
      '</div>' +
      '<div class="shell-template-select" id="shellTemplateSelect"></div>' +
      '<p class="shell-runtime-status" id="shellRuntimeStatus" role="status" aria-live="polite"></p>';
    menu.appendChild(newSection);

    var historySection = document.createElement("section");
    historySection.className = "shell-rail-section";
    historySection.innerHTML = '<h2>기존 견적서 · 지난 대화</h2>';
    var recent = makeButton(
      "shellRecentQuote",
      "↶",
      "최근 견적 불러오기",
      "이 브라우저에 저장한 견적을 엽니다"
    );
    recent.addEventListener("click", function () { clickExisting("recentQuoteStarter"); });
    historySection.appendChild(recent);
    menu.appendChild(historySection);

    var importSection = document.createElement("section");
    importSection.className = "shell-rail-section";
    importSection.innerHTML = '<h2>가져오기</h2>';
    var file = makeButton(
      "shellFileImport",
      "＋",
      "파일에서 불러오기",
      "PDF·사진·문서를 선택합니다"
    );
    file.addEventListener("click", function () { clickExisting("fileStarter"); });
    importSection.appendChild(file);
    menu.appendChild(importSection);

    rail.appendChild(menu);

    var account = document.createElement("div");
    account.className = "shell-account-row";
    account.id = "shellAccountRow";
    rail.appendChild(account);

    shell.appendChild(rail);

    var skillSelect = byId("padiemSavedSkillSelect");
    var skillStatus = byId("padiemQuoteStatus");
    var selectHost = byId("shellTemplateSelect");
    if (skillSelect && selectHost) {
      selectHost.appendChild(skillSelect);
      function syncTemplateName() {
        var name = byId("shellTemplateName");
        if (!name) return;
        var option = skillSelect.selectedOptions && skillSelect.selectedOptions[0];
        name.textContent = option && option.textContent
          ? option.textContent + " · 사용 중"
          : "로그인 후 템플릿을 불러옵니다";
      }
      skillSelect.addEventListener("change", syncTemplateName);
      new MutationObserver(syncTemplateName).observe(skillSelect, {
        childList: true,
        subtree: true,
        attributes: true
      });
      syncTemplateName();
    }
    if (skillStatus) {
      byId("shellRuntimeStatus").replaceWith(skillStatus);
      skillStatus.classList.add("shell-runtime-status");
    }

    var accountButton = byId("padiemAccountButton");
    var settingsButton = byId("settingsButton");
    if (accountButton) account.appendChild(accountButton);
    if (settingsButton) account.appendChild(settingsButton);

    var logout = byId("padiemLogout");
    var settingsPanel = byId("settingsPanel");
    if (logout && settingsPanel) settingsPanel.appendChild(logout);

    return rail;
  }

  function buildPreviewHost(shell) {
    var preview = shell.querySelector(".preview-wrap");
    if (!preview) return null;

    var host = document.createElement("aside");
    host.className = "shell-preview-host";
    host.id = "shellPreviewHost";
    host.setAttribute("aria-label", "견적서 미리보기 패널");

    var divider = document.createElement("div");
    divider.className = "shell-divider";
    divider.setAttribute("role", "separator");
    divider.setAttribute("aria-orientation", "vertical");
    divider.setAttribute("aria-label", "미리보기 너비 조절");

    host.appendChild(divider);
    host.appendChild(preview);
    shell.appendChild(host);

    var toolbar = preview.querySelector(".preview-toolbar");
    var collapse = document.createElement("button");
    collapse.type = "button";
    collapse.className = "shell-pane-button shell-preview-collapse";
    collapse.textContent = "접기 »";
    collapse.setAttribute("aria-controls", "shellPreviewHost");
    collapse.addEventListener("click", function () {
      document.body.classList.add("preview-collapsed");
    });
    if (toolbar) toolbar.appendChild(collapse);

    var reopen = document.createElement("button");
    reopen.type = "button";
    reopen.className = "shell-preview-reopen";
    reopen.textContent = "미리보기 열기 ◀";
    reopen.setAttribute("aria-controls", "shellPreviewHost");
    reopen.addEventListener("click", function () {
      document.body.classList.remove("preview-collapsed");
    });
    shell.appendChild(reopen);

    function syncPreviewScale() {
      var paper = byId("quotePaper");
      if (!paper) return;
      var naturalWidth = parseFloat(getComputedStyle(paper).width);
      if (!Number.isFinite(naturalWidth) || naturalWidth <= 0) return;
      var available = Math.max(0, preview.clientWidth - 18);
      var scale = Math.min(1, available / naturalWidth);
      var zoom = String(Math.max(0.25, scale));
      paper.style.zoom = zoom;
      var details = document.querySelectorAll("#pvDetailPages .quote-detail-page");
      details.forEach(function (page) { page.style.zoom = zoom; });
    }

    if (typeof ResizeObserver === "function") {
      new ResizeObserver(syncPreviewScale).observe(preview);
    }
    var paper = byId("quotePaper");
    if (paper && typeof MutationObserver === "function") {
      new MutationObserver(syncPreviewScale).observe(paper, {
        attributes: true,
        childList: true,
        subtree: true
      });
    }
    window.addEventListener("resize", syncPreviewScale);
    window.setTimeout(syncPreviewScale, 0);

    divider.addEventListener("mousedown", function (event) {
      event.preventDefault();
      var startX = event.clientX;
      var startWidth = host.getBoundingClientRect().width;
      document.body.classList.add("shell-resizing");

      function move(moveEvent) {
        var width = Math.round(startWidth + (startX - moveEvent.clientX));
        width = Math.min(PREVIEW_MAX, Math.max(PREVIEW_MIN, width));
        document.documentElement.style.setProperty("--b66-preview-width", width + "px");
      }
      function up() {
        window.removeEventListener("mousemove", move);
        window.removeEventListener("mouseup", up);
        document.body.classList.remove("shell-resizing");
      }
      window.addEventListener("mousemove", move);
      window.addEventListener("mouseup", up);
    });

    return host;
  }

  function buildTopbarToggle() {
    var topbar = document.querySelector(".topbar");
    var brand = topbar && topbar.querySelector(".brand");
    if (!topbar || !brand) return;

    var left = document.createElement("div");
    left.className = "shell-topbar-left";

    var toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "shell-rail-toggle";
    toggle.id = "shellRailToggle";
    toggle.textContent = "☰";
    toggle.title = "메뉴 접기/열기";
    toggle.setAttribute("aria-controls", "shellRail");
    toggle.addEventListener("click", function () {
      document.body.classList.toggle("rail-collapsed");
    });

    left.appendChild(toggle);
    left.appendChild(brand);
    topbar.insertBefore(left, topbar.firstChild);
  }

  function syncDirectMode() {
    var direct = byId("directView");
    if (!direct) return;
    function sync() {
      document.body.classList.toggle("mode-direct", !direct.hidden);
    }
    sync();
    new MutationObserver(sync).observe(direct, {
      attributes: true,
      attributeFilter: ["hidden"]
    });
  }

  function syncMobileDefault() {
    if (window.matchMedia("(max-width:" + MOBILE_BREAKPOINT + "px)").matches) {
      document.body.classList.add("rail-collapsed");
      document.body.classList.add("preview-collapsed");
    }
  }

  function init() {
    var shell = document.querySelector("main.shell");
    if (!shell || byId("shellRail")) return;

    document.body.classList.add("b66-three-pane");
    buildRail(shell);
    buildPreviewHost(shell);
    buildTopbarToggle();
    syncDirectMode();
    syncMobileDefault();

    var legacyPanel = byId("padiemAccountPanel");
    if (legacyPanel) legacyPanel.classList.add("shell-legacy-account-panel");

    var topbarActions = document.querySelector(".topbar-actions");
    if (topbarActions) {
      topbarActions.classList.add("shell-empty-topbar-actions");
      if (!topbarActions.querySelector("button, a, input, select")) topbarActions.hidden = true;
    }
  }

  init();

  window.B66ShellLayout = Object.freeze({
    init: init,
    previewBounds: Object.freeze({ min: PREVIEW_MIN, max: PREVIEW_MAX })
  });
})();
