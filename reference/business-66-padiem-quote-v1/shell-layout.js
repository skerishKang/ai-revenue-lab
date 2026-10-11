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
    var railCollapse = document.createElement("button");
    railCollapse.id = "shellRailCollapse";
    railCollapse.type = "button";
    railCollapse.className = "shell-pane-button shell-rail-collapse";
    railCollapse.textContent = "접기 ‹";
    railCollapse.setAttribute("aria-label", "왼쪽 메뉴 접기");
    railCollapse.setAttribute("aria-controls", "shellRail");
    railCollapse.addEventListener("click", function () {
      document.body.classList.add("rail-collapsed");
      var reopenButton = byId("shellRailToggle");
      if (reopenButton) reopenButton.focus();
    });
    rail.appendChild(railCollapse);

    var menu = document.createElement("div");
    menu.className = "shell-rail-menu";

    var newSection = document.createElement("section");
    newSection.className = "shell-rail-section";
    newSection.setAttribute("aria-label", "새 견적 시작");
    newSection.innerHTML =
      '<button type="button" class="shell-rail-item shell-new-quote" id="shellNewQuote">' +
      '<span class="shell-rail-icon" aria-hidden="true">＋</span>' +
      '<span><strong>새 견적 시작</strong><small>현재 내용을 비우고 새 견적을 작성합니다</small></span>' +
      '</button>';
    menu.appendChild(newSection);

    var managementSection = document.createElement("section");
    managementSection.className = "shell-rail-section";
    managementSection.setAttribute("aria-label", "견적서 양식 선택 및 새 양식 등록");
    managementSection.innerHTML =
      '<label class="shell-picker-label">견적서 양식<select-host id="shellSkillSelect"></select-host></label>' +
      '<p class="shell-runtime-status" id="shellRuntimeStatus" role="status" aria-live="polite"></p>' +
      '<label class="shell-picker-label" id="shellModelControl" hidden><select-host id="shellModelSelect"></select-host></label>';
    // A reusable template starts from an existing file, not from quote line-item
    // editing. Reuse the registered Saved Quote Skill file intake/wizard.
    var manual = makeButton(
      "shellManualQuote",
      "▤",
      "새 양식 만들기",
      "기존 견적서 파일을 선택해 새 양식을 검토합니다"
    );
    manual.addEventListener("click", function () {
      document.dispatchEvent(new CustomEvent("b66:open-skill-register"));
    });
    newSection.appendChild(manual);
    menu.appendChild(managementSection);

    var historySection = document.createElement("section");
    historySection.className = "shell-rail-section";
    historySection.setAttribute("aria-label", "최근 견적 불러오기");
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

    rail.appendChild(menu);

    var account = document.createElement("div");
    account.className = "shell-account-row";
    account.id = "shellAccountRow";
    rail.appendChild(account);

    shell.appendChild(rail);

    var skillSelect = byId("padiemSavedSkillSelect");
    var modelSelect = byId("padiemQuoteModelSelect");
    var skillStatus = byId("padiemQuoteStatus");
    var skillHost = byId("shellSkillSelect");
    var modelHost = byId("shellModelSelect");
    var toolbar = byId("easyModelToolbar");
    if (skillSelect && skillHost) {
      skillHost.appendChild(skillSelect);
      // The selector itself shows the current approved template; do not repeat it in a second card.
    }
    // The secondary output-template selector remains within the existing
    // advanced-template details; the rail has only the approved Saved Skill.
    if (modelSelect && modelHost && toolbar) {
      // Move the original registered model selector into the composer; no cloned authority.
      var modelControl = byId("shellModelControl");
      toolbar.appendChild(modelControl);
      modelHost.appendChild(modelSelect);
      var reasoningSelect = byId("padiemQuoteReasoningSelect");
      var reasoningControl = document.createElement("label");
      reasoningControl.id = "shellReasoningControl";
      reasoningControl.className = "shell-picker-label b66-composer-reasoning";
      reasoningControl.hidden = true; // Product admin policy will own reasoning later.
      if (reasoningSelect) reasoningControl.appendChild(reasoningSelect);
      toolbar.appendChild(reasoningControl);
      function syncModelControl(event) {
        var signedIn = event && event.detail
          ? event.detail.authenticated === true
          : !!(byId("padiemAccountPanel") && !byId("padiemAccountPanel").hidden);
        // A visible, disabled signed-out selector tells mobile users where the
        // model will appear; the server only enables registered models after login.
        modelControl.hidden = false;
        if (modelSelect && !signedIn) modelSelect.disabled = true;
        reasoningControl.hidden = true; // Never expose a customer-level thinking override.
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
    // Keep the existing programmatic trigger for the account menu; never show two settings buttons.
    if (settingsButton) {
      settingsButton.hidden = true;
      account.appendChild(settingsButton);
    }

    var accountMenu = document.createElement("div");
    accountMenu.id = "b66AccountMenu";
    accountMenu.className = "b66-account-menu";
    accountMenu.hidden = true;
    accountMenu.setAttribute("aria-label", "계정 메뉴");
    accountMenu.innerHTML = '<button id="b66AccountMenuSettings" type="button">설정</button>' +
      '<button id="b66AccountMenuDrive" type="button">Google Drive 저장</button>' +
      '<button id="b66AccountMenuLogout" type="button">로그아웃</button>';
    account.appendChild(accountMenu);
    if (accountButton) {
      accountButton.setAttribute("aria-haspopup", "true");
      accountButton.setAttribute("aria-expanded", "false");
    }
    byId("b66AccountMenuSettings").addEventListener("click", function () {
      accountMenu.hidden = true;
      if (accountButton) accountButton.setAttribute("aria-expanded", "false");
      clickExisting("settingsButton");
    });
    byId("b66AccountMenuDrive").addEventListener("click", function () {
      accountMenu.hidden = true;
      if (accountButton) accountButton.setAttribute("aria-expanded", "false");
      clickExisting("settingsButton");
      clickExisting("settingsDriveChoice"); // existing settings and Drive UI; no new OAuth path
    });
    byId("b66AccountMenuLogout").addEventListener("click", function () {
      accountMenu.hidden = true;
      if (accountButton) accountButton.setAttribute("aria-expanded", "false");
      clickExisting("padiemLogout");
    });
    document.addEventListener("click", function (event) {
      if (!account.contains(event.target)) {
        accountMenu.hidden = true;
        if (accountButton) accountButton.setAttribute("aria-expanded", "false");
      }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !accountMenu.hidden) {
        accountMenu.hidden = true;
        if (accountButton) {
          accountButton.setAttribute("aria-expanded", "false");
          accountButton.focus();
        }
      }
    });

    var logout = byId("padiemLogout");
    var privacyPanel = byId("privacySettingsView");
    if (logout && privacyPanel) privacyPanel.appendChild(logout);

    return rail;
  }

  function buildPreviewHost(shell) {
    var preview = shell.querySelector(".preview-wrap");
    if (!preview) return null;

    var host = document.createElement("aside");
    host.className = "shell-preview-host";
    host.id = "shellPreviewHost";
    host.setAttribute("aria-label", "견적서 미리보기 패널");
    host.setAttribute("tabindex", "-1");

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
      if (window.matchMedia("(max-width:1250px)").matches) reopen.focus();
    });
    var pdfShortcut = document.createElement("button");
    pdfShortcut.id = "shellPreviewPdf";
    pdfShortcut.type = "button";
    pdfShortcut.className = "shell-pane-button shell-preview-pdf";
    pdfShortcut.textContent = "PDF 저장";
    pdfShortcut.title = "견적 내용을 확인한 뒤 PDF로 저장";
    pdfShortcut.addEventListener("click", function () {
      clickExisting("printPdf"); // reuse canonical readiness and PDF authority
    });
    var printShortcut = document.createElement("button");
    printShortcut.id = "shellPreviewPrint";
    printShortcut.type = "button";
    printShortcut.className = "shell-pane-button shell-preview-print";
    printShortcut.textContent = "인쇄";
    printShortcut.title = "현재 견적서 미리보기를 그대로 인쇄";
    printShortcut.addEventListener("click", function () {
      if (typeof window.B66QuotePrintPreview === "function") window.B66QuotePrintPreview();
    });
    if (toolbar) {
      var readinessStatus = document.createElement("span");
      readinessStatus.id = "shellPreviewReadiness";
      readinessStatus.className = "shell-preview-readiness";
      readinessStatus.textContent = "작성 중";
      readinessStatus.setAttribute("role", "status");
      toolbar.appendChild(readinessStatus);
      toolbar.appendChild(pdfShortcut);
      toolbar.appendChild(printShortcut);
      toolbar.appendChild(collapse);
      function syncReadiness() {
        var core = window.QuoteCore;
        var app = window.B66QuoteAppBridge;
        var runtime = window.B66QuoteRuntimeBridge;
        var ready = false;
        try {
          ready = !!(core && app && runtime &&
            core.printReadiness(app.getDraft()).ready &&
            runtime.readiness().ready === true);
        } catch (_) { ready = false; }
        readinessStatus.textContent = ready ? "출력 준비" : "작성 중";
        readinessStatus.dataset.ready = String(ready);
      }
      document.addEventListener("input", syncReadiness);
      document.addEventListener("change", syncReadiness);
      document.addEventListener("b66:auth-changed", syncReadiness);
      var readinessPaper = byId("quotePaper");
      if (readinessPaper && typeof MutationObserver === "function") {
        new MutationObserver(syncReadiness).observe(readinessPaper, {
          childList: true, subtree: true, attributes: true
        });
      }
      window.setTimeout(syncReadiness, 0);
    }

    var reopen = document.createElement("button");
    reopen.type = "button";
    reopen.className = "shell-preview-reopen";
    reopen.textContent = "견적서 보기";
    reopen.setAttribute("aria-label", "견적서 미리보기 열기");
    reopen.setAttribute("aria-controls", "shellPreviewHost");
    reopen.addEventListener("click", function () {
      if (window.matchMedia("(max-width:900px)").matches) {
        document.body.classList.add("rail-collapsed");
      }
      document.body.classList.remove("preview-collapsed");
      if (window.matchMedia("(max-width:1250px)").matches) collapse.focus();
    });
    shell.appendChild(reopen);

    // Viewer-only zoom: no changes to the certified quote DOM or print geometry.
    var zoomFactor = 1;
    var zoomStatus = document.createElement("span");
    zoomStatus.className = "shell-preview-zoom-status";
    zoomStatus.setAttribute("role", "status");
    zoomStatus.setAttribute("aria-live", "polite");
    var zoomControls = document.createElement("div");
    zoomControls.className = "shell-preview-zoom";
    zoomControls.setAttribute("role", "group");
    zoomControls.setAttribute("aria-label", "미리보기 확대");
    function zoomButton(label, symbol, value) {
      var button = document.createElement("button");
      button.type = "button";
      button.textContent = symbol;
      button.setAttribute("aria-label", label);
      button.addEventListener("click", function () {
        zoomFactor = value === 0 ? 1 : Math.min(3, Math.max(1, zoomFactor + value));
        syncPreviewScale();
      });
      return button;
    }
    var zoomOut = zoomButton("미리보기 축소", "−", -0.5);
    var zoomReset = zoomButton("화면에 맞추기", "맞춤", 0);
    var zoomIn = zoomButton("미리보기 확대", "+", 0.5);
    zoomControls.appendChild(zoomOut);
    zoomControls.appendChild(zoomStatus);
    zoomControls.appendChild(zoomIn);
    zoomControls.appendChild(zoomReset);
    if (toolbar) toolbar.insertBefore(zoomControls, collapse);

    function syncPreviewScale() {
      var paper = byId("quotePaper");
      if (!paper) return;
      var naturalWidth = parseFloat(getComputedStyle(paper).width);
      if (!Number.isFinite(naturalWidth) || naturalWidth <= 0) return;
      var available = Math.max(0, preview.clientWidth - 18);
      var scale = Math.min(1, available / naturalWidth);
      var zoom = String(Math.max(0.25, scale * zoomFactor));
      zoomStatus.textContent = Math.round(Number(zoom) * 100) + "%";
      zoomOut.disabled = zoomFactor <= 1;
      zoomIn.disabled = zoomFactor >= 3;
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

    // When pagination grows from one A4 sheet to two or three, follow the
    // newly added page within the preview scroller only. Respect manual scroll.
    var detailHost = byId("pvDetailPages");
    if (detailHost && typeof MutationObserver === "function") {
      var previousPages = detailHost.querySelectorAll(".quote-detail-page").length;
      var followNewPages = true;
      var programmaticPreviewScroll = false;
      var pendingPage = null;

      function showNewPage(page) {
        if (!page || !followNewPages || document.body.classList.contains("preview-collapsed")) {
          pendingPage = page || pendingPage;
          return;
        }
        pendingPage = null;
        window.requestAnimationFrame(function () {
          if (!followNewPages) return;
          var box = page.getBoundingClientRect();
          var viewerBox = preview.getBoundingClientRect();
          var top = preview.scrollTop + box.top - viewerBox.top - 12;
          programmaticPreviewScroll = true;
          preview.scrollTop = Math.max(0, top);
          window.requestAnimationFrame(function () { programmaticPreviewScroll = false; });
        });
      }

      preview.addEventListener("scroll", function () {
        if (programmaticPreviewScroll) return;
        followNewPages = preview.scrollHeight - preview.clientHeight - preview.scrollTop <= 96;
      }, { passive: true });

      new MutationObserver(function () {
        var pages = detailHost.querySelectorAll(".quote-detail-page");
        if (pages.length > previousPages) showNewPage(pages[pages.length - 1]);
        previousPages = pages.length;
      }).observe(detailHost, { childList: true, subtree: true });

      reopen.addEventListener("click", function () {
        if (pendingPage) showNewPage(pendingPage);
      });
    }

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
      if (window.matchMedia("(max-width:900px)").matches) {
        if (!document.body.classList.contains("rail-collapsed")) {
          document.body.classList.add("preview-collapsed");
          var first = byId("shellNewQuote");
          if (first) first.focus();
        } else {
          toggle.focus();
        }
      }
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
    var senderSection = direct.querySelector(".panel > .section");
    var quotePaper = byId("quotePaper");
    if (senderSection && quotePaper) {
      var senderNote = document.createElement("p");
      senderNote.id = "b66CertifiedSenderNote";
      senderNote.className = "b66-certified-sender-note";
      senderNote.hidden = true;
      senderNote.textContent = "이 CGI 양식의 회사정보·직인은 승인된 고정 배경에 포함됩니다. 아래 입력값만 수정해도 고정된 회사정보는 바뀌지 않으니, 다른 회사 견적서로 사용하지 마세요.";
      var senderLoad = senderSection.querySelector(".b66-sender-load");
      if (senderLoad) senderLoad.insertAdjacentElement("afterend", senderNote);
      function syncSenderNote() {
        senderNote.hidden = !(quotePaper.getAttribute("data-layout-variant") === "cgi-v2" &&
          quotePaper.getAttribute("data-certified-preview") === "true");
      }
      if (typeof MutationObserver === "function") {
        new MutationObserver(syncSenderNote).observe(quotePaper, {
          attributes: true, attributeFilter: ["data-layout-variant", "data-certified-preview"]
        });
      }
      syncSenderNote();
    }
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


  function wireOverlayKeyboard() {
    var rail = byId("shellRail");
    var preview = byId("shellPreviewHost");
    var toggle = byId("shellRailToggle");
    var reopen = document.querySelector(".shell-preview-reopen");
    if (!rail || !preview || !toggle || !reopen) return;

    function isRailModal() {
      return window.matchMedia("(max-width:900px)").matches &&
        !document.body.classList.contains("rail-collapsed");
    }
    function isPreviewModal() {
      return window.matchMedia("(max-width:1250px)").matches &&
        !document.body.classList.contains("preview-collapsed");
    }
    function syncSemantics() {
      var railOpen = isRailModal();
      var previewOpen = isPreviewModal();
      toggle.setAttribute("aria-expanded", String(
        !document.body.classList.contains("rail-collapsed")
      ));
      reopen.setAttribute("aria-expanded", String(
        !document.body.classList.contains("preview-collapsed")
      ));
      [rail, preview].forEach(function (panel, index) {
        if (index === 0 ? railOpen : previewOpen) {
          panel.setAttribute("role", "dialog");
          panel.setAttribute("aria-modal", "true");
        } else {
          panel.removeAttribute("role");
          panel.removeAttribute("aria-modal");
        }
      });
    }
    syncSemantics();
    new MutationObserver(syncSemantics).observe(document.body, {
      attributes: true, attributeFilter: ["class"]
    });
    window.addEventListener("resize", syncSemantics);

    document.addEventListener("keydown", function (event) {
      var panel = isPreviewModal() ? preview : (isRailModal() ? rail : null);
      if (!panel) return;
      if (event.key === "Escape") {
        event.preventDefault();
        if (panel === preview) {
          document.body.classList.add("preview-collapsed");
          reopen.focus();
        } else {
          document.body.classList.add("rail-collapsed");
          toggle.focus();
        }
        return;
      }
      if (event.key !== "Tab") return;
      var candidates = Array.prototype.slice.call(panel.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), ' +
        'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      )).filter(function (node) {
        return node.getClientRects().length > 0 && !node.closest("[hidden]");
      });
      if (!candidates.length) {
        event.preventDefault();
        panel.focus();
        return;
      }
      var first = candidates[0];
      var last = candidates[candidates.length - 1];
      if (!panel.contains(document.activeElement)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
  }

  function wireComposerVisualViewport() {
    var viewport = window.visualViewport;
    var composer = byId("easyComposer");
    if (!viewport || !composer) return;

    // Mobile keyboards can resize only the visual viewport (not 100dvh).
    // Apply the override solely while the canonical chat input is focused.
    function sync() {
      var mobile = window.matchMedia("(max-width:900px)").matches;
      var editing = document.activeElement === composer;
      var height = viewport.height;
      var obscured = window.innerHeight - height;
      var keyboardLike = Number.isFinite(height) && height > 0 &&
        obscured >= 120 && viewport.scale <= 1.05;
      if (mobile && editing && keyboardLike) {
        document.documentElement.style.setProperty(
          "--b66-visual-height", Math.floor(height) + "px"
        );
      } else {
        document.documentElement.style.removeProperty("--b66-visual-height");
      }
    }

    viewport.addEventListener("resize", sync);
    window.addEventListener("resize", sync);
    composer.addEventListener("focus", sync);
    composer.addEventListener("blur", function () {
      window.requestAnimationFrame(sync);
    });
    sync();
  }

  function init() {
    var shell = document.querySelector("main.shell");
    if (!shell || byId("shellRail")) return;

    document.body.classList.add("b66-three-pane");
    buildRail(shell);
    var attach = byId("easyAttach");
    if (attach) attach.addEventListener("click", function () {
      document.dispatchEvent(new CustomEvent("b66:open-file-intake"));
    });
    buildPreviewHost(shell);
    buildTopbarToggle();
    syncDirectMode();
    syncMobileDefault();
    wireOverlayKeyboard();
    wireComposerVisualViewport();

    var legacyPanel = byId("padiemAccountPanel");
    if (legacyPanel) legacyPanel.classList.add("shell-legacy-account-panel");

    var topbarActions = document.querySelector(".topbar-actions");
    if (topbarActions) {
      topbarActions.classList.add("shell-empty-topbar-actions");
      if (!topbarActions.querySelector("button, a, input, select")) topbarActions.hidden = true;
    }
    // Hide the uncomposed HTML during deferred script load, then reveal once.
    window.requestAnimationFrame(function () {
      document.documentElement.classList.remove("b66-shell-booting");
    });
  }

  init();

  window.B66ShellLayout = Object.freeze({
    init: init,
    previewBounds: Object.freeze({ min: PREVIEW_MIN, max: PREVIEW_MAX })
  });
})();
