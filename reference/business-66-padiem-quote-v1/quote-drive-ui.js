/* B66 — Google Drive 저장·불러오기 화면 연결 (#3871 Slice D).
   이 기능은 선택 사항이다. Google Drive 를 연결하지 않아도 기존 견적 작성,
   최근 견적, PDF 다운로드는 그대로 동작한다.

   원칙
   - 저장 위치는 항상 사용자가 명시적으로 고른다. 자동 저장·자동 동기화 없음.
   - 성공/실패/부분 성공을 정확히 표시한다. 부분 성공을 성공으로 표시하지 않는다.
   - B66 로그아웃·계정 전환은 Drive 세션을 즉시 폐기한다(토큰 격리).
   - 계정이 바뀐 뒤 도착한 in-flight 응답은 편집기나 상태를 갱신하지 못한다.
   - PDF 는 기존 인증된 렌더러(app.js certifiedPdfBytes)에서만 얻는다.
   - 불러오기는 승인된 템플릿 권위가 확인된 경우에만 편집기에 적용한다.
   - 모델 호출 0, innerHTML 0.

   DOM 이 필요한 모듈이다. Node 테스트는 문서 스텁을 주입한다. */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.B66QuoteDriveUi = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var DEFAULT_CONTAINER_ID = "driveStoragePanel";
  var START_HOOK_FLAG = "__b66DriveUiStartHooked";
  var CONFIG_GLOBAL = "B66_DRIVE_CLIENT_ID";
  var CONFIG_APP_ID_GLOBAL = "B66_DRIVE_PICKER_APP_ID";
  var CONFIG_DEVELOPER_KEY_GLOBAL = "B66_DRIVE_PICKER_DEVELOPER_KEY";
  var BRIDGE_GLOBAL = "B66QuoteAppBridge";
  var BOOTSTRAP_RETRY_MS = 250;
  var BOOTSTRAP_MAX_ATTEMPTS = 40;

  /* B66 계정 권위가 유지되는 상태에서만 Drive 세션을 보존한다. */
  var DRIVE_SESSION_KEEP_ACTIONS = ["owner_bound", "same_account_resume"];

  function resolveGlobal(name) {
    if (typeof window !== "undefined" && window[name]) return window[name];
    if (typeof globalThis !== "undefined" && globalThis[name]) return globalThis[name];
    return null;
  }

  function element(doc, tag, text) {
    var node = doc.createElement(tag);
    if (typeof text === "string" && text) node.textContent = text;
    return node;
  }

  function configString(explicit, globalName) {
    if (typeof explicit === "string" && explicit.trim()) return explicit.trim();
    var configured = resolveGlobal(globalName);
    if (typeof configured === "string" && configured.trim()) return configured.trim();
    return "";
  }

  function createClient(options) {
    var Client = resolveGlobal("B66QuoteDriveClient");
    if (!Client || typeof Client.create !== "function") return null;
    return Client.create({
      clientId: configString(options && options.clientId, CONFIG_GLOBAL),
      appId: configString(options && options.appId, CONFIG_APP_ID_GLOBAL),
      developerKey: configString(options && options.developerKey, CONFIG_DEVELOPER_KEY_GLOBAL)
    });
  }

  function mount(options) {
    var opts = options || {};
    var doc = opts.document || (typeof document !== "undefined" ? document : null);
    if (!doc || typeof doc.getElementById !== "function") {
      return { ok: false, code: "ui_unavailable" };
    }
    var container = doc.getElementById(opts.containerId || DEFAULT_CONTAINER_ID);
    if (!container) return { ok: false, code: "container_missing" };

    var client = opts.client || createClient(opts);
    if (!client) return { ok: false, code: "client_unavailable" };

    var bridge = opts.bridge || resolveGlobal(BRIDGE_GLOBAL) || null;
    var Contract = opts.contract || resolveGlobal("B66QuoteDriveContract") || null;

    var status = element(doc, "p", "");
    status.className = "drive-status";
    var connectButton = element(doc, "button", "내 Google Drive 연결");
    connectButton.type = "button";
    connectButton.className = "btn";
    var saveButton = element(doc, "button", "내 Google Drive에 저장");
    saveButton.type = "button";
    saveButton.className = "btn";
    var openButton = element(doc, "button", "Google Drive에서 열기");
    openButton.type = "button";
    openButton.className = "btn";
    var pickerButton = element(doc, "button", "파일 선택기로 열기");
    pickerButton.type = "button";
    pickerButton.className = "btn";
    pickerButton.hidden = true;
    var retryButton = element(doc, "button", "다시 저장");
    retryButton.type = "button";
    retryButton.className = "btn";
    retryButton.hidden = true;
    var fileSelect = element(doc, "select");
    fileSelect.className = "drive-file-select";
    fileSelect.hidden = true;
    var confirmOpenButton = element(doc, "button", "선택한 견적 불러오기");
    confirmOpenButton.type = "button";
    confirmOpenButton.className = "btn";
    confirmOpenButton.hidden = true;

    var actions = element(doc, "div", "");
    actions.className = "drive-actions";
    actions.appendChild(connectButton);
    actions.appendChild(saveButton);
    actions.appendChild(openButton);
    actions.appendChild(pickerButton);
    actions.appendChild(retryButton);
    actions.appendChild(fileSelect);
    actions.appendChild(confirmOpenButton);
    container.replaceChildren(status, actions);

    var pendingOutcome = null;
    var fileIndex = [];
    var busy = false;

    function setStatus(text, tone) {
      status.textContent = typeof text === "string" ? text : "";
      status.dataset.tone = tone || "info";
      if (bridge && typeof bridge.toast === "function" && typeof text === "string" && text) {
        bridge.toast(text, 4200);
      }
    }

    function clearSelection() {
      fileIndex = [];
      fileSelect.replaceChildren();
      fileSelect.hidden = true;
      confirmOpenButton.hidden = true;
    }

    function clearPending() {
      pendingOutcome = null;
      retryButton.hidden = true;
    }

    /* renderConnection(options) — silent=true 면 결과 메시지를 덮어쓰지 않는다. */
    function renderConnection(options) {
      var silent = Boolean(options && options.silent === true);
      var session = client.session();
      var configured = client.isConfigured();
      var connected = session.connected === true;
      connectButton.textContent = connected ? "Google Drive 연결 해제" : "내 Google Drive 연결";
      saveButton.disabled = !configured || !connected;
      openButton.disabled = !configured || !connected;
      pickerButton.hidden = !(configured && connected && client.pickerReady());
      if (silent) return;
      if (!configured) {
        setStatus("Google Drive 연결 설정이 준비되지 않았습니다. 견적 작성과 PDF 다운로드는 그대로 사용할 수 있습니다.", "info");
      } else if (!connected) {
        setStatus("연결된 Google 계정이 없습니다. 저장·불러오기를 하려면 먼저 연결해 주세요.", "info");
      } else {
        setStatus("내 Google Drive에 연결되었습니다. 저장과 불러오기를 사용할 수 있습니다.", "ok");
      }
    }

    /* 계정 epoch 이 바뀌었으면 이 작업의 결과를 절대 반영하지 않는다. */
    function epochNow() {
      return client.session().epoch;
    }

    function superseded(epoch) {
      if (client.session().epoch === epoch) return false;
      clearPending();
      clearSelection();
      renderConnection({ silent: true });
      setStatus("B66 계정이 변경되어 진행 중이던 Google Drive 작업을 취소했습니다.", "warn");
      return true;
    }

    /* ── B66 로그아웃 / 계정 전환 격리 ──
       B66 계정 권위가 유지되는 상태가 아니면 Drive 토큰을 즉시 폐기한다. */
    function applyAccountAuthority(detail, source) {
      var authenticated = Boolean(detail && detail.authenticated === true);
      var action = detail && typeof detail.action === "string" ? detail.action : null;
      var keep = authenticated && DRIVE_SESSION_KEEP_ACTIONS.indexOf(action) !== -1;
      if (source === "auth-changed" && !authenticated) keep = false;
      if (keep) return false;
      var session = client.session();
      if (!session.connected && !pendingOutcome && !fileIndex.length) return false;
      clearPending();
      clearSelection();
      client.disconnect({ reason: "b66_account_authority_changed" });
      renderConnection({ silent: true });
      setStatus("B66 계정이 로그아웃되었거나 변경되어 Google Drive 연결을 해제했습니다.", "warn");
      return true;
    }

    function onScopeChanged(event) {
      applyAccountAuthority(event && event.detail, "account-scope-changed");
    }

    function onAuthChanged(event) {
      applyAccountAuthority(event && event.detail, "auth-changed");
    }

    async function onConnect() {
      if (busy) return;
      var session = client.session();
      if (session.connected) {
        await client.disconnect();
        clearPending();
        clearSelection();
        renderConnection({ silent: true });
        setStatus("Google Drive 연결을 해제했습니다. 저장된 파일은 그대로 남아 있습니다.", "info");
        return;
      }
      busy = true;
      connectButton.disabled = true;
      try {
        var epoch = epochNow();
        var result = await client.connect();
        if (superseded(epoch)) return;
        if (!result.ok) {
          renderConnection({ silent: true });
          setStatus(result.message || "Google 계정 연결에 실패했습니다.", "error");
          return;
        }
        renderConnection();
      } finally {
        busy = false;
        connectButton.disabled = false;
      }
    }

    function approvedTemplates() {
      if (!bridge || typeof bridge.listApprovedSkills !== "function") return [];
      try {
        var list = bridge.listApprovedSkills();
        return Array.isArray(list) ? list : [];
      } catch (err) {
        return [];
      }
    }

    async function onSave() {
      if (busy) return;
      if (!bridge || typeof bridge.getDraft !== "function") {
        setStatus("현재 견적을 읽을 수 없습니다.", "error");
        return;
      }
      busy = true;
      saveButton.disabled = true;
      try {
        var epoch = epochNow();
        var draft = bridge.getDraft();
        if (!draft) {
          setStatus("저장할 견적 내용이 없습니다.", "error");
          return;
        }
        var pdf = typeof bridge.certifiedPdfBytes === "function"
          ? await bridge.certifiedPdfBytes()
          : { ok: false, code: "pdf_source_unavailable" };
        if (superseded(epoch)) return;
        if (!pdf || pdf.ok !== true || !pdf.bytes) {
          /* PDF 없이 JSON만 올려 외톨이 파일을 만들지 않는다. */
          setStatus("인증된 PDF를 만들지 못해 저장을 시작하지 않았습니다. 견적 내용을 확인해 주세요. (" +
            ((pdf && pdf.code) || "pdf_source_unavailable") + ")", "error");
          return;
        }
        var template = typeof bridge.activeTemplateReference === "function"
          ? bridge.activeTemplateReference()
          : null;
        var outcome = await client.savePair({ draft: draft, template: template, pdfBytes: pdf.bytes });
        if (superseded(epoch)) return;
        if (outcome.code === "drive_session_changed") {
          setStatus(outcome.message || "계정 변경으로 저장을 중단했습니다.", "warn");
          return;
        }
        pendingOutcome = outcome.partial === true ? outcome : null;
        if (outcome.status === "complete") {
          retryButton.hidden = true;
          setStatus("견적 JSON과 PDF를 내 Google Drive에 저장했습니다.", "ok");
        } else if (outcome.partial) {
          /* 부분 성공을 조용히 넘기지 않는다. */
          retryButton.hidden = false;
          setStatus(outcome.message, "warn");
        } else {
          retryButton.hidden = true;
          setStatus(outcome.message || (outcome.code ? "저장에 실패했습니다. (" + outcome.code + ")" : "저장에 실패했습니다."), "error");
        }
      } finally {
        busy = false;
        renderConnection({ silent: true });
        saveButton.disabled = !client.session().connected;
      }
    }

    async function onRetry() {
      if (busy || !pendingOutcome) return;
      if (!bridge || typeof bridge.getDraft !== "function") return;
      busy = true;
      retryButton.disabled = true;
      try {
        var epoch = epochNow();
        var draft = bridge.getDraft();
        var pdf = typeof bridge.certifiedPdfBytes === "function"
          ? await bridge.certifiedPdfBytes()
          : { ok: false, code: "pdf_source_unavailable" };
        if (superseded(epoch)) return;
        var outcome = await client.retryMissing({
          outcome: pendingOutcome,
          draft: draft,
          template: typeof bridge.activeTemplateReference === "function" ? bridge.activeTemplateReference() : null,
          pdfBytes: pdf && pdf.bytes ? pdf.bytes : null
        });
        if (superseded(epoch)) return;
        if (outcome.status === "complete") {
          pendingOutcome = null;
          retryButton.hidden = true;
          setStatus("이어서 저장을 완료했습니다.", "ok");
        } else if (outcome.partial) {
          pendingOutcome = outcome;
          setStatus(outcome.message, "warn");
        } else {
          /* 내용이 바뀌었거나 유지된 파일을 확인할 수 없으면 이어서 저장하지 않는다. */
          pendingOutcome = null;
          retryButton.hidden = true;
          setStatus(outcome.message || ("이어서 저장하지 못했습니다. (" + (outcome.code || "retry_failed") + ")"), "error");
        }
      } finally {
        busy = false;
        retryButton.disabled = false;
      }
    }

    function loadFileIntoSelect(files) {
      fileIndex = files;
      fileSelect.replaceChildren();
      files.forEach(function (file) {
        var option = element(doc, "option", file.name || file.id);
        option.value = file.id;
        fileSelect.appendChild(option);
      });
      fileSelect.value = files[0].id;
      fileSelect.hidden = false;
      confirmOpenButton.hidden = false;
    }

    async function onOpen() {
      if (busy) return;
      busy = true;
      openButton.disabled = true;
      try {
        var epoch = epochNow();
        var listed = await client.listQuoteFiles();
        if (superseded(epoch)) return;
        if (!listed.ok) {
          setStatus(listed.code === "drive_token_expired"
            ? "Google 계정 연결이 만료되었습니다. 다시 연결해 주세요."
            : "저장된 견적 목록을 불러오지 못했습니다. (" + (listed.code || "list_failed") + ")", "error");
          renderConnection({ silent: true });
          return;
        }
        var jsonFiles = listed.files.filter(function (file) {
          return file.mimeType === "application/json";
        });
        if (!jsonFiles.length) {
          clearSelection();
          setStatus("내 Google Drive에서 저장한 견적 JSON을 찾지 못했습니다.", "info");
          return;
        }
        loadFileIntoSelect(jsonFiles);
        setStatus("불러올 견적을 선택해 주세요.", "info");
      } finally {
        busy = false;
        openButton.disabled = !client.session().connected;
      }
    }

    async function onPickerOpen() {
      if (busy) return;
      busy = true;
      pickerButton.disabled = true;
      try {
        var epoch = epochNow();
        var picked = await client.openPicker();
        if (superseded(epoch)) return;
        if (!picked.ok) {
          if (picked.code === "picker_cancelled") {
            setStatus("파일 선택을 취소했습니다.", "info");
            return;
          }
          busy = false;
          pickerButton.disabled = false;
          await onOpen();
          /* 목록 경로가 만든 안내를 지우지 않고 선택기 미지원 사실을 함께 알린다. */
          setStatus("파일 선택기를 사용할 수 없어 목록에서 선택합니다. " + (status.textContent || ""), "warn");
          return;
        }
        await applyOpen(picked.picked[0].id);
      } finally {
        busy = false;
        pickerButton.disabled = false;
      }
    }

    async function applyOpen(fileId) {
      var epoch = epochNow();
      var opened = await client.openQuoteFile(fileId, { templates: approvedTemplates() });
      if (superseded(epoch)) return;
      if (!opened.ok) {
        /* 승인 템플릿 권위가 확인되지 않으면 편집기에 적용하지 않는다. */
        setStatus(opened.message || ("선택한 파일을 불러올 수 없습니다. (" + opened.code + ")"), "error");
        return;
      }
      if (!bridge || typeof bridge.replaceDraft !== "function" || typeof bridge.getDraft !== "function") {
        setStatus("불러온 견적을 편집기에 적용할 수 없습니다.", "error");
        return;
      }
      var confirmed = typeof opts.confirm === "function"
        ? opts.confirm("현재 작성 중인 견적을 바꾸고 이 견적을 불러올까요?")
        : true;
      if (confirmed !== true) {
        setStatus("불러오기를 취소했습니다.", "info");
        return;
      }

      /* 적용 결과를 반드시 확인한다. 실패를 성공으로 표시하지 않는다. */
      var applied = null;
      try {
        applied = bridge.replaceDraft(opened.draft);
      } catch (err) {
        applied = { ok: false, error: "replace_failed" };
      }
      if (!applied || applied.ok !== true) {
        setStatus("불러온 견적을 편집기에 적용하지 못했습니다. (" +
          ((applied && applied.error) || "replace_failed") + ")", "error");
        return;
      }

      var readBack = null;
      try {
        readBack = bridge.getDraft();
      } catch (err) {
        readBack = null;
      }
      var templateRef = typeof bridge.activeTemplateReference === "function" ? bridge.activeTemplateReference() : null;
      var expected = opened.contentFingerprint;
      var actual = Contract && typeof Contract.contentFingerprint === "function"
        ? Contract.contentFingerprint(readBack, templateRef)
        : null;
      if (!readBack || !actual || (expected && actual !== expected)) {
        setStatus("불러온 견적이 편집기에 정확히 반영되지 않았습니다. 다시 시도해 주세요.", "error");
        return;
      }

      var grand = opened.totals ? opened.totals.grand : null;
      var message = "견적을 불러왔습니다. 금액은 QuoteCore로 다시 계산했습니다.";
      if (grand !== null && typeof grand === "number") message += " 합계 " + String(grand);
      setStatus(message, "ok");
    }

    async function onConfirmOpen() {
      if (busy) return;
      var fileId = fileSelect.value;
      if (!fileId) return;
      busy = true;
      confirmOpenButton.disabled = true;
      try {
        await applyOpen(fileId);
      } finally {
        busy = false;
        confirmOpenButton.disabled = false;
      }
    }

    connectButton.addEventListener("click", onConnect);
    saveButton.addEventListener("click", onSave);
    openButton.addEventListener("click", onOpen);
    pickerButton.addEventListener("click", onPickerOpen);
    retryButton.addEventListener("click", onRetry);
    confirmOpenButton.addEventListener("click", onConfirmOpen);

    if (typeof doc.addEventListener === "function") {
      doc.addEventListener("b66:account-scope-changed", onScopeChanged);
      doc.addEventListener("b66:auth-changed", onAuthChanged);
    }

    renderConnection();

    return {
      ok: true,
      contract: Contract ? Contract.CONTRACT_ID : null,
      container: container,
      session: function () { return client.session(); },
      statusText: function () { return status.textContent; },
      statusTone: function () { return status.dataset.tone || "info"; },
      retryVisible: function () { return retryButton.hidden === false; },
      pickerVisible: function () { return pickerButton.hidden === false; },
      connectVisible: function () { return connectButton.hidden !== true; },
      saveVisible: function () { return saveButton.hidden !== true; },
      openVisible: function () { return openButton.hidden !== true; },
      saveDisabled: function () { return saveButton.disabled; },
      openDisabled: function () { return openButton.disabled; },
      lastOutcome: function () { return pendingOutcome; },
      applyAccountAuthority: applyAccountAuthority,
      click: function (name) {
        var map = {
          connect: connectButton,
          save: saveButton,
          open: openButton,
          picker: pickerButton,
          retry: retryButton,
          confirmOpen: confirmOpenButton
        };
        var node = map[name];
        if (!node) return false;
        node.click();
        return true;
      }
    };
  }

  /* ── 1회성 시작 훅 ──
     B66QuoteAppBridge 가 존재한 뒤에만 mount 한다. 여러 번 호출해도 한 번만 붙는다. */
  var bootstrapState = { handle: null, attempts: 0, scheduled: false };

  function bootstrap(options) {
    var opts = options || {};
    if (bootstrapState.handle) return bootstrapState.handle;
    var bridge = resolveGlobal(BRIDGE_GLOBAL);
    if (!bridge && !opts.bridge) {
      if (bootstrapState.scheduled) return { ok: false, code: "bootstrap_pending" };
      if (bootstrapState.attempts >= BOOTSTRAP_MAX_ATTEMPTS) return { ok: false, code: "bridge_unavailable" };
      bootstrapState.attempts += 1;
      bootstrapState.scheduled = true;
      var timer = opts.setTimeout || (typeof setTimeout === "function" ? setTimeout : null);
      if (!timer) return { ok: false, code: "bridge_unavailable" };
      timer(function () {
        bootstrapState.scheduled = false;
        bootstrap(opts);
      }, BOOTSTRAP_RETRY_MS);
      return { ok: false, code: "bootstrap_pending" };
    }
    var handle = mount(Object.assign({}, opts, { bridge: opts.bridge || bridge }));
    if (handle && handle.ok) {
      bootstrapState.handle = handle;
      var globalScope = typeof window !== "undefined" ? window : (typeof globalThis !== "undefined" ? globalThis : null);
      if (globalScope) globalScope.B66QuoteDriveUiInstance = handle;
    }
    return handle;
  }

  function resetBootstrapForTest() {
    bootstrapState.handle = null;
    bootstrapState.attempts = 0;
    bootstrapState.scheduled = false;
  }

  /* ── 브라우저 시작 훅 ──
     index.html 에 별도 호출 코드를 두지 않고 이 모듈이 스스로 한 번만 붙는다.
     B66QuoteAppBridge 가 아직 없으면 bootstrap() 이 제한된 횟수만큼 다시 시도한다. */
  function installStartHook(scope, api) {
    if (!scope || !scope.document || scope[START_HOOK_FLAG]) return false;
    scope[START_HOOK_FLAG] = true;
    var start = function () {
      try {
        api.bootstrap();
      } catch (err) {
        /* 시작 훅 실패가 기존 견적 작성 흐름을 막지 않는다. */
      }
    };
    if (scope.document.readyState === "loading" && typeof scope.document.addEventListener === "function") {
      scope.document.addEventListener("DOMContentLoaded", start);
    } else {
      start();
    }
    return true;
  }

  var api = {
    DEFAULT_CONTAINER_ID: DEFAULT_CONTAINER_ID,
    CONFIG_GLOBAL: CONFIG_GLOBAL,
    CONFIG_APP_ID_GLOBAL: CONFIG_APP_ID_GLOBAL,
    CONFIG_DEVELOPER_KEY_GLOBAL: CONFIG_DEVELOPER_KEY_GLOBAL,
    DRIVE_SESSION_KEEP_ACTIONS: DRIVE_SESSION_KEEP_ACTIONS.slice(),
    configString: configString,
    mount: mount,
    bootstrap: bootstrap,
    installStartHook: installStartHook,
    resetBootstrapForTest: resetBootstrapForTest
  };

  if (typeof window !== "undefined" && window.document) installStartHook(window, api);

  return Object.freeze(api);
});
