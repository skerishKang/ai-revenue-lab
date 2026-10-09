/* B66 — Google Drive 저장·불러오기 화면 연결 (#3871 Slice D).
   이 기능은 선택 사항이다. Google Drive 를 연결하지 않아도 기존 견적 작성,
   최근 견적, PDF 다운로드는 그대로 동작한다.

   원칙
   - 저장 위치는 항상 사용자가 명시적으로 고른다. 자동 저장·자동 동기화 없음.
   - 성공/실패/부분 성공을 정확히 표시한다. 부분 성공을 성공으로 표시하지 않는다.
   - PDF 는 기존 인증된 렌더러(app.js certifiedPdfBytes)에서만 얻는다.
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
  var CONFIG_GLOBAL = "B66_DRIVE_CLIENT_ID";

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

  function clientIdFromConfig(explicit) {
    if (typeof explicit === "string" && explicit.trim()) return explicit.trim();
    var configured = resolveGlobal(CONFIG_GLOBAL);
    if (typeof configured === "string" && configured.trim()) return configured.trim();
    return "";
  }

  function createClient(options) {
    var Client = resolveGlobal("B66QuoteDriveClient");
    if (!Client || typeof Client.create !== "function") return null;
    var clientId = clientIdFromConfig(options && options.clientId);
    return Client.create({
      clientId: clientId,
      appId: (options && options.appId) || "",
      developerKey: (options && options.developerKey) || ""
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

    var bridge = opts.bridge || resolveGlobal("B66QuoteAppBridge") || null;
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
    actions.appendChild(retryButton);
    actions.appendChild(fileSelect);
    actions.appendChild(confirmOpenButton);
    container.replaceChildren(status, actions);

    var pendingOutcome = null;
    var fileIndex = [];

    function setStatus(text, tone) {
      status.textContent = typeof text === "string" ? text : "";
      status.dataset.tone = tone || "info";
      if (bridge && typeof bridge.toast === "function" && typeof text === "string" && text) {
        bridge.toast(text, 4200);
      }
    }

    /* silent=true 면 상태 문구를 덮어쓰지 않는다. 저장/불러오기 결과 메시지를 지키기 위한 구분이다. */
    function renderConnection(options) {
      var silent = Boolean(options && options.silent === true);
      var session = client.session();
      connectButton.textContent = session.connected ? "Google Drive 연결 해제" : "내 Google Drive 연결";
      var configured = client.isConfigured();
      saveButton.disabled = !configured || !session.connected;
      openButton.disabled = !configured || !session.connected;
      if (silent) return;
      if (!configured) {
        setStatus("Google Drive 연결 설정이 준비되지 않았습니다. 견적 작성과 PDF 다운로드는 그대로 사용할 수 있습니다.", "info");
      } else if (!session.connected) {
        setStatus("연결된 Google 계정이 없습니다. 저장·불러오기를 하려면 먼저 연결해 주세요.", "info");
      } else {
        setStatus("내 Google Drive에 연결되었습니다. 저장과 불러오기를 사용할 수 있습니다.", "ok");
      }
    }

    async function onConnect() {
      var session = client.session();
      if (session.connected) {
        await client.disconnect();
        pendingOutcome = null;
        retryButton.hidden = true;
        fileSelect.hidden = true;
        confirmOpenButton.hidden = true;
        renderConnection({ silent: true });
        setStatus("Google Drive 연결을 해제했습니다. 저장된 파일은 그대로 남아 있습니다.", "info");
        return;
      }
      var result = await client.connect();
      if (!result.ok) {
        renderConnection({ silent: true });
        setStatus(result.message || "Google 계정 연결에 실패했습니다.", "error");
        return;
      }
      renderConnection();
    }

    async function onSave() {
      if (!bridge || typeof bridge.getDraft !== "function") {
        setStatus("현재 견적을 읽을 수 없습니다.", "error");
        return;
      }
      saveButton.disabled = true;
      try {
        var draft = bridge.getDraft();
        if (!draft) {
          setStatus("저장할 견적 내용이 없습니다.", "error");
          return;
        }
        var pdf = typeof bridge.certifiedPdfBytes === "function"
          ? await bridge.certifiedPdfBytes()
          : { ok: false, code: "pdf_source_unavailable" };
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
        pendingOutcome = outcome;
        if (outcome.status === "complete") {
          retryButton.hidden = true;
          setStatus("견적 JSON과 PDF를 내 Google Drive에 저장했습니다.", "ok");
        } else if (outcome.partial) {
          /* 부분 성공을 조용히 넘기지 않는다. */
          retryButton.hidden = false;
          setStatus(outcome.message, "warn");
        } else {
          retryButton.hidden = false;
          setStatus(outcome.message || (outcome.code ? "저장에 실패했습니다. (" + outcome.code + ")" : "저장에 실패했습니다."), "error");
        }
      } finally {
        saveButton.disabled = false;
        renderConnection({ silent: true });
      }
    }

    async function onRetry() {
      if (!pendingOutcome) return;
      if (!bridge || typeof bridge.getDraft !== "function") return;
      retryButton.disabled = true;
      try {
        var draft = bridge.getDraft();
        var pdf = typeof bridge.certifiedPdfBytes === "function"
          ? await bridge.certifiedPdfBytes()
          : { ok: false, code: "pdf_source_unavailable" };
        var outcome = await client.retryMissing({
          outcome: pendingOutcome,
          draft: draft,
          template: typeof bridge.activeTemplateReference === "function" ? bridge.activeTemplateReference() : null,
          pdfBytes: pdf && pdf.bytes ? pdf.bytes : null
        });
        pendingOutcome = outcome;
        if (outcome.status === "complete") {
          retryButton.hidden = true;
          setStatus("이어서 저장을 완료했습니다.", "ok");
        } else {
          setStatus(outcome.message || "다시 저장에 실패했습니다.", "error");
        }
      } finally {
        retryButton.disabled = false;
      }
    }

    async function onOpen() {
      var listed = await client.listQuoteFiles();
      if (!listed.ok) {
        setStatus(listed.code === "drive_token_expired"
          ? "Google 계정 연결이 만료되었습니다. 다시 연결해 주세요."
          : "저장된 견적 목록을 불러오지 못했습니다.", "error");
        renderConnection({ silent: true });
        return;
      }
      var jsonFiles = listed.files.filter(function (file) {
        return file.mimeType === "application/json";
      });
      if (!jsonFiles.length) {
        setStatus("내 Google Drive에서 저장한 견적 JSON을 찾지 못했습니다.", "info");
        fileSelect.hidden = true;
        confirmOpenButton.hidden = true;
        return;
      }
      fileIndex = jsonFiles;
      fileSelect.replaceChildren();
      jsonFiles.forEach(function (file) {
        var option = element(doc, "option", file.name || file.id);
        option.value = file.id;
        fileSelect.appendChild(option);
      });
      fileSelect.value = jsonFiles[0].id;
      fileSelect.hidden = false;
      confirmOpenButton.hidden = false;
      setStatus("불러올 견적을 선택해 주세요.", "info");
    }

    async function onConfirmOpen() {
      var fileId = fileSelect.value;
      if (!fileId) return;
      var opened = await client.openQuoteFile(fileId);
      if (!opened.ok) {
        setStatus(opened.message || "선택한 파일을 불러올 수 없습니다. (" + opened.code + ")", "error");
        return;
      }
      if (!bridge || typeof bridge.replaceDraft !== "function") {
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
      bridge.replaceDraft(opened.draft);
      var grand = opened.totals ? opened.totals.grand : null;
      var message = "견적을 불러왔습니다. 금액은 QuoteCore로 다시 계산했습니다.";
      if (grand !== null && typeof grand === "number") {
        message += " 합계 " + String(grand);
      }
      if (opened.warnings && opened.warnings.length) {
        message += " · 배정된 견적서 양식을 확인해 주세요. 다른 양식으로 자동 대체하지 않았습니다.";
      }
      setStatus(message, opened.warnings && opened.warnings.length ? "warn" : "ok");
    }

    connectButton.addEventListener("click", onConnect);
    saveButton.addEventListener("click", onSave);
    openButton.addEventListener("click", onOpen);
    retryButton.addEventListener("click", onRetry);
    confirmOpenButton.addEventListener("click", onConfirmOpen);

    renderConnection();

    return {
      ok: true,
      contract: Contract ? Contract.CONTRACT_ID : null,
      session: function () { return client.session(); },
      statusText: function () { return status.textContent; },
      retryVisible: function () { return retryButton.hidden === false; },
      saveDisabled: function () { return saveButton.disabled; },
      openDisabled: function () { return openButton.disabled; },
      lastOutcome: function () { return pendingOutcome; },
      click: function (name) {
        var map = { connect: connectButton, save: saveButton, open: openButton, retry: retryButton, confirmOpen: confirmOpenButton };
        var node = map[name];
        if (!node) return false;
        node.click();
        return true;
      }
    };
  }

  return Object.freeze({
    DEFAULT_CONTAINER_ID: DEFAULT_CONTAINER_ID,
    CONFIG_GLOBAL: CONFIG_GLOBAL,
    clientIdFromConfig: clientIdFromConfig,
    mount: mount
  });
});
