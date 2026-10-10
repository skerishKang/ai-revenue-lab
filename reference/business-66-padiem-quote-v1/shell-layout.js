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
      '<h2>새 견적</h2>' +
      '<button type="button" class="shell-rail-item shell-new-quote" id="shellNewQuote">' +
      '<span class="shell-rail-icon" aria-hidden="true">＋</span>' +
      '<span><strong>새 견적 시작</strong><small>내용을 비우고 대화에서 새 견적을 시작합니다.</small></span>' +
      '</button>' +
      '<div class="shell-template-current">' +
      '<span class="shell-rail-icon" aria-hidden="true">▣</span>' +
      '<span><strong>배정된 내 견적서</strong>' +
      '<small id="shellTemplateName">로그인한 계정의 Saved Skill을 불러옵니다.</small></span>' +
      '</div>' +
      '<p class="shell-runtime-status" id="shellRuntimeStatus" role="status" aria-live="polite"></p>';
    menu.appendChild(newSection);

    var managementSection = document.createElement("section");
    managementSection.className = "shell-rail-section";
    managementSection.innerHTML =
      '<h2>견적서 관리</h2>' +
      '<label class="shell-picker-label">배정된 내 견적서<select-host id="shellSkillSelect"></select-host></label>' +
      '<label class="shell-picker-label">출력 양식<select-host id="shellQuoteTemplateSelect"></select-host></label>' +
      '<label class="shell-picker-label" id="shellModelControl" hidden>견적 해석 AI 모델<select-host id="shellModelSelect"></select-host></label>';
    menu.appendChild(managementSection);

    var historySection = document.createElement("section");
    historySection.className = "shell-rail-section";
    historySection.innerHTML = '<h2>최근 견적</h2>';
    var recent = makeButton(
      "shellRecentQuote",
      "↶",
      "최근 견적 불러오기",
      "로그인 계정 또는 이 브라우저의 최근 견적을 엽니다"
    );
    recent.addEventListener("click", function () {
      document.dispatchEvent(new CustomEvent("b66:open-recent-quotes"));
    });
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
    file.addEventListener("click", function () {
      document.dispatchEvent(new CustomEvent("b66:open-file-intake"));
    });
    importSection.appendChild(file);
    menu.appendChild(importSection);

    rail.appendChild(menu);

    var account = document.createElement("div");
    account.className = "shell-account-row";
    account.id = "shellAccountRow";
    rail.appendChild(account);

    shell.appendChild(rail);

    var skillSelect = byId("padiemSavedSkillSelect");
    var templateSelect = byId("templateSelect");
    var modelSelect = byId("padiemQuoteModelSelect");
    var skillStatus = byId("padiemQuoteStatus");
    var skillHost = byId("shellSkillSelect");
    var templateHost = byId("shellQuoteTemplateSelect");
    var modelHost = byId("shellModelSelect");
    if (skillSelect && skillHost) {
      skillHost.appendChild(skillSelect);
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
    if (templateSelect && templateHost) {
      templateHost.appendChild(templateSelect);
    }
    if (modelSelect && modelHost) {
      // Move the one authoritative B14 picker; never clone the select or choose a model.
      modelHost.appendChild(modelSelect);
      var modelControl = byId("shellModelControl");
      function syncModelControl(event) {
        var signedIn = event && event.detail
          ? event.detail.authenticated === true
          : byId("padiemAccountPanel") && !byId("padiemAccountPanel").hidden;
        if (modelControl) modelControl.hidden = !signedIn;
      }
      document.addEventListener("b66:auth-changed", syncModelControl);
      syncModelControl();
    }
    var newQuoteButton = byId("shellNewQuote");
    if (newQuoteButton) {
      newQuoteButton.addEventListener("click", function () {
        clickExisting("newQuote");
      });
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
    // Editing is a separate, explicitly labelled task, not a new blank quotation.
    var directTab = byId("directModeButton");
    if (directTab) directTab.textContent = "세부 항목 편집";
    var manualStarter = byId("directStarter");
    if (manualStarter) {
      var starterTitle = manualStarter.querySelector("strong");
      var starterNote = manualStarter.querySelector("small");
      if (starterTitle) starterTitle.textContent = "세부 항목 직접 편집";
      if (starterNote) starterNote.textContent = "보내는 사람·품목·금액을 직접 수정합니다";
    }
    var editHeader = document.createElement("div");
    editHeader.className = "shell-edit-heading";
    editHeader.innerHTML = '<div><strong>세부 항목 편집 중</strong><p>현재 견적의 내용을 직접 수정하는 화면입니다. 새 견적 시작과는 다릅니다.</p></div>' +
      '<button type="button" class="shell-edit-return">채팅으로 돌아가기</button>';
    editHeader.querySelector("button").addEventListener("click", function () {
      document.dispatchEvent(new CustomEvent("b66:open-easy-chat"));
    });
    direct.insertBefore(editHeader, direct.firstChild);
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
    }
    // Medium laptop widths must retain sufficient room for the primary editor.
    if (window.matchMedia("(max-width:1250px)").matches) {
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
