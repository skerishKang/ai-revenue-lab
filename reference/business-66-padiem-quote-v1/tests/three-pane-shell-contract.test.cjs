const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
const css = fs.readFileSync(path.join(ROOT, "styles.css"), "utf8");
const shell = fs.readFileSync(path.join(ROOT, "shell-layout.js"), "utf8");
const app = fs.readFileSync(path.join(ROOT, "app.js"), "utf8");
const refresh = fs.readFileSync(path.join(ROOT, "b66-surface-refresh.css"), "utf8");
const driveUi = fs.readFileSync(path.join(ROOT, "quote-drive-ui.js"), "utf8");
const check = (condition, label) => assert.ok(condition, "contract failed: " + label);

check(html.includes('<script src="shell-layout.js" defer></script>'),
  "canonical page loads three-pane shell after account/runtime scripts");
check(html.includes('id="easyComposer"') && html.includes('id="easySend"'),
  "single chat composer remains primary conversational input");
check(!html.includes('id="padiemQuoteRequest"') && !html.includes('id="padiemQuoteGenerate"'),
  "duplicate legacy quote input and send action are removed");
check(shell.includes('skillHost.appendChild(skillSelect)'),
  "rail moves actual Saved Quote Skill selector");
check(!shell.includes('templateHost.appendChild(templateSelect)') &&
      html.includes('<details class="advanced-template">') &&
      html.includes('id="templateSelect"') &&
      app.includes('$("templateSelect").addEventListener("change"'),
  "legacy output template selector remains functional in advanced management");
check(shell.includes('modelHost.appendChild(modelSelect)'),
  "rail moves the one authoritative selected-model control, no hidden fallback");
check(shell.includes('b66:open-recent-quotes') && shell.includes('b66:open-file-intake'),
  "rail secondary navigation activates the canonical Easy view actions");
check(shell.includes('id="shellNewQuote"') && shell.includes('clickExisting("newQuote")'),
  "rail exposes an explicit new-quote action");
check(shell.includes('shellManualQuote') && shell.includes('새 양식 만들기') &&
  shell.includes('b66:open-skill-register') && shell.includes('newSection.appendChild(manual)') &&
  shell.includes('id="shellNewQuote"'),
  "파일 기반 새 양식 등록은 새 견적 시작 버튼 바로 아래에 연결된다");
check(app.includes('b66:open-skill-register') &&
      app.includes('skillUiApi.actions.openWizard($("shellManualQuote"))') &&
      app.includes('SkillUi.bindSkillSection'),
  "파일을 선택해 검토하는 기존 Saved Skill 마법사를 사용한다");
check(shell.includes('account.appendChild(accountButton)'),
  "rail moves actual account button");
check(shell.includes('host.appendChild(preview)'),
  "right pane moves canonical preview node");
check(shell.includes('railCollapse.className = "shell-pane-button shell-rail-collapse"') &&
      shell.includes('railCollapse.textContent = "접기 ‹"') &&
      shell.includes('collapse.textContent = "접기 »"'),
  "both sidebar collapse actions use the same button family and opposing arrows");
check(refresh.includes('.shell-rail-collapse::before { content: none; }') &&
      refresh.includes('.shell-preview-host > .preview-wrap {\n    background: transparent;') &&
      refresh.includes('.shell-preview-host #quotePaper,') &&
      refresh.includes('box-shadow: 0 6px 22px rgba(38,63,81,.13);'),
  "only the A4 paper is white; the tall preview backing is transparent on screen");
check(html.includes('href="b66-surface-refresh.css?v=20261012-0646" media="screen"'),
  "viewer presentation never changes print or certified A4 geometry");
check(!shell.includes('createElement("iframe")') && !shell.includes("b66-cgi-form.html"),
  "production shell never embeds CGI prototype iframe");
check(css.includes(".shell-legacy-account-panel") && css.includes("display: none !important"),
  "large legacy account panel is removed from presentation");
check(css.includes("max-width: 820px"), "conversation reading width is capped at 820px");
check(css.includes("--b66-preview-width") && shell.includes("PREVIEW_MIN = 300") &&
      shell.includes("PREVIEW_MAX = 1000"), "preview resize is bounded");
check(shell.includes('classList.add("preview-collapsed")') &&
      shell.includes('classList.remove("preview-collapsed")'), "preview collapse/reopen exists");
check(shell.includes('classList.toggle("rail-collapsed")'), "rail collapse/reopen exists");
check(css.includes("@media (max-width: 900px)"), "mobile shell has explicit bounded layout");
check(html.match(/id="quotePaper"/g)?.length === 1, "exactly one canonical quote paper exists");
check(html.match(/id="easyComposer"/g)?.length === 1, "exactly one chat composer exists");

check(html.includes('<link rel="stylesheet" href="b66-surface-refresh.css?v=20261012-0646" media="screen">'),
  "UI-only stylesheet is loaded for screen, never CGI PDF print geometry");
const resetStart = app.indexOf('  $("newQuote").addEventListener("click", () => {');
const resetConfirm = app.indexOf('if (!window.confirm(', resetStart);
const resetCommitted = app.indexOf('    draft = next;', resetStart);
const navigateAfterCommit = app.indexOf('document.dispatchEvent(new CustomEvent("b66:open-easy-chat"));', resetStart);
check(resetStart !== -1 && resetConfirm > resetStart && resetCommitted > resetConfirm &&
  navigateAfterCommit > resetCommitted, "new quote navigates only after confirmed reset");
check(!/clickExisting\("newQuote"\);\s*document\.dispatchEvent/.test(shell),
  "cancelled new-quote action never navigates from the rail itself");
check(shell.includes('세부 항목 편집 중') && shell.includes('shell-edit-return'),
  "direct-edit mode is explicitly labelled with a non-destructive way back");
check(refresh.includes('.direct-view > .modebar { display: none; }'),
  "duplicate direct-edit navigation is hidden only in the B66 shell");
check(refresh.includes('overflow-y: auto') && refresh.includes('overscroll-behavior: contain') &&
  refresh.includes('flex: 0 0 auto;'), "mobile keeps the composer visible while conversation scrolls");
check(refresh.includes('position: fixed;') && refresh.includes('shell-preview-host'),
  "mobile preview opens above the form instead of after the full-length form");
check(css.includes("body.b66-three-pane .shell-edit-heading { display: none !important; }"),
  "screen-only edit explanation must never appear in printed CGI PDF");

check(shell.includes('COMPACT_PREVIEW_BREAKPOINT = 1480') &&
  shell.includes('window.addEventListener("resize", syncMobileDefault)') &&
  shell.includes('previewAutoCollapsed') &&
  refresh.includes('min-width: 901px') &&
  refresh.includes('max-width: 1480px') &&
  refresh.includes('grid-template-columns: 260px minmax(0, 1fr)'),
  "resized mid-width windows automatically center the editor with a reopenable preview");
check(refresh.includes('height: max(185px, calc(var(--b66-visual-height, 100dvh) - 165px))'),
  "mobile conversation responds to compact keyboard viewport height");
check(refresh.includes('body.b66-three-pane .shell-preview-reopen::after'),
  "mobile preview opener is compact rather than colliding with the brand");
check(refresh.includes('body.b66-three-pane .toast') && refresh.includes('bottom: auto'),
  "mobile and medium-width status notices stay away from the bottom composer");
check(driveUi.includes('var initializingConnection = true;') &&
  driveUi.includes('if (!initializingConnection && bridge') &&
  driveUi.includes('initializingConnection = false;'),
  "optional Google Drive startup readiness does not create an obstructive toast");

check(shell.includes('function wireOverlayKeyboard()') &&
  shell.includes('event.key === "Escape"') && shell.includes('event.key !== "Tab"') &&
  shell.includes('panel.setAttribute("role", "dialog")') &&
  shell.includes('panel.setAttribute("aria-modal", "true")') &&
  shell.includes('toggle.setAttribute("aria-expanded"') &&
  shell.includes('reopen.setAttribute("aria-expanded"'),
  "compact rail and preview must have Escape, focus trap, and accessible dialog state");
check(shell.includes('reopen.focus()') && shell.includes('toggle.focus()') &&
  shell.includes('first.focus()') && shell.includes('last.focus()'),
  "closing dialogs restores the opener and loops keyboard focus");
check(shell.includes('zoomFactor') && shell.includes('zoomControls') &&
  shell.includes('syncPreviewScale()') && refresh.includes('.shell-preview-zoom'),
  "screen-only preview viewer supports fit, zoom and horizontal scroll");
check(!html.includes('id="shell-preview-zoom"'), "certified HTML paper stays unchanged");

check(shell.includes("function wireComposerVisualViewport()") &&
  shell.includes('viewport.addEventListener("resize", sync)') &&
  shell.includes('document.activeElement === composer') &&
  shell.includes('obscured >= 120') &&
  shell.includes('viewport.scale <= 1.05') &&
  shell.includes('style.removeProperty("--b66-visual-height")'),
  "visual-only mobile keyboard shrink must be bounded to a focused composer and reset");
check(refresh.includes("var(--b66-visual-height, 100dvh)") &&
  refresh.includes("height: max(185px"),
  "keyboard-aware composer keeps the pre-existing dvh fallback and bounded minimum");
const paneFix = refresh.split("/* #4316 UI follow-up:")[1] || "";
check(paneFix.includes("The 2px phantom scrollbar belonged to .easy-view") &&
  paneFix.includes("overflow: hidden;") &&
  paneFix.includes("min-height: 0;") &&
  paneFix.includes("position: relative;") &&
  paneFix.includes("margin-top: 0;") &&
  paneFix.includes("flex: 0 0 auto;"),
  "desktop pane and transcript share height without a premature outer scrollbar");
check(paneFix.includes("one right-side card like the left rail") &&
  paneFix.includes(".shell-preview-host .preview-toolbar") &&
  paneFix.includes("background: #f8fbfd;") &&
  paneFix.includes("background: #f8fbfd;") &&
  paneFix.includes("backdrop-filter: none;") &&
  paneFix.includes("border-radius: 22px;"),
  "right preview is one bounded light pane, not two stacked cards");
check(html.includes('media="screen"') &&
  !refresh.includes("@page"),
  "presentation-only scroll/pane CSS cannot modify printed A4 paper");
console.log("B66_THREE_PANE_SHELL=PASS");
console.log("B66_PRIMARY_INPUT_AUTHORITY=EASY_COMPOSER");
console.log("B66_CANONICAL_PREVIEW_COUNT=1");
console.log("B66_CGI_IFRAME_COUNT=0");
