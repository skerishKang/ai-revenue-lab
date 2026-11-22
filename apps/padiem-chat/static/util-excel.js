/*
 * #7500 · Excel 열기/검토 inside the Util app (#util/excel).
 *
 * File boundary: this screen and its sheet (util-excel.css) live in the Util
 * app; field definitions come from window.PadiemUtilManifest (util-manifest.js);
 * app.js gains nothing (R5 #7216).
 *
 * The screen uploads the original .xlsx bytes to the server route
 * (/api/util/excel/review) and paints the deterministic review the route
 * returns: sheet list with row/column counts, the head of the first readable
 * sheet and the review summary. Refusal copy is the server's own Korean
 * guidance (the shipped wording), so one code never grows two wordings.
 *
 * #7461: the screen offers both form and conversational intake (same shared
 * seam as the other util tools); both call the same /api/util/excel/review
 * route, reuse the same usage gate and show the same server refusal copy.
 */
(() => {
  "use strict";

  const T = Object.freeze({
    ko: Object.freeze({
      loginRequired: "로그인 후 이용할 수 있습니다.",
      loginUnknown: "로그인 상태를 확인하는 중입니다.",
      login: "로그인",
      required: "검토할 XLSX 파일을 선택해 주세요.",
      wrongKind: "XLSX(.xlsx) 파일만 열 수 있습니다.",
      reviewing: "파일을 읽는 중…",
      submit: "검토 시작",
      result: "검토 결과",
      emptyResult: "XLSX 파일을 선택하고 검토를 시작하면 시트 목록·앞부분 표·검토 요약이 이 결과 칸에 표시됩니다.",
      generic: "검토를 마치지 못했습니다. 잠시 후 다시 시도해 주세요.",
      authNeeded: "로그인이 필요합니다.",
      tooLarge: "파일이 너무 큽니다.",
      quota: "오늘 사용 한도를 다 썼어요. 내일 다시 이용해 주세요.",
      sheetsTitle: "시트 목록",
      sheetFallback: (index) => "시트 #" + (index + 1),
      emptySheet: "빈 시트",
      rowsLabel: "데이터 행",
      columnsLabel: "열",
      truncatedNote: "상한 초과 — 앞부분만 읽음",
      previewTitle: "앞부분 미리보기",
      previewNone: "표의 앞부분을 읽지 못했습니다.",
      summaryTitle: "검토 요약",
      summarySheetCount: "시트 개수",
      summaryReadable: "값을 읽은 시트",
      summaryEmpty: "빈 시트",
      summaryTruncated: "상한으로 잘린 시트",
      summaryRows: "읽은 데이터 행(시트당 상한 500)",
      summaryNote: "검토 메모",
      noValue: "—",
    }),
    en: Object.freeze({
      loginRequired: "Sign in to use this tool.",
      loginUnknown: "Checking your sign-in state…",
      login: "Sign in",
      required: "Choose the XLSX file to review.",
      wrongKind: "Only XLSX (.xlsx) files can be opened.",
      reviewing: "Reading the file…",
      submit: "Start review",
      result: "Review result",
      emptyResult: "Pick an XLSX file and start the review to see the sheet list, head table and review summary here.",
      generic: "The review could not finish. Please try again shortly.",
      authNeeded: "Sign-in is required.",
      tooLarge: "The file is too large.",
      quota: "Today's usage limit is used up. Please come back tomorrow.",
      sheetsTitle: "Sheets",
      sheetFallback: (index) => "Sheet #" + (index + 1),
      emptySheet: "Empty sheet",
      rowsLabel: "Data rows",
      columnsLabel: "Columns",
      truncatedNote: "past the bound — head only",
      previewTitle: "Head preview",
      previewNone: "The head of the table could not be read.",
      summaryTitle: "Review summary",
      summarySheetCount: "Sheets",
      summaryReadable: "Sheets with values",
      summaryEmpty: "Empty sheets",
      summaryTruncated: "Sheets cut at the bound",
      summaryRows: "Data rows read (500 per sheet)",
      summaryNote: "Review note",
      noValue: "—",
    }),
  });

  function t(key) {
    const locale = document.documentElement && document.documentElement.lang === "en" ? "en" : "ko";
    return T[locale][key] || T.ko[key] || "";
  }

  /* #7461: conversational intake copy overrides; every unanswered engine key
   * (mode tabs, attach button, open-form, …) keeps the shared util wording. */
  const CHAT_COPY = Object.freeze({
    ko: Object.freeze({
      refinePlaceholder: "무엇을 더 확인할지 적어 주세요 (예: 합계 수식과 단가 누락)",
      allReadyIdle: "검토 준비가 끝났습니다. 바로 검토하거나 검토 목표를 입력해 주세요.",
      allReadyWithDraft: "검토 결과와 입력값을 유지하고 있습니다. 무엇을 더 확인할지 적어 주세요.",
      generatingTurn: "올린 파일을 기존 검토 경로로 읽고 있습니다…",
      generatedTurn: "오른쪽 결과 칸에 검토 결과를 준비했습니다. '폼으로 열기'로 세부 입력을 바꿀 수 있습니다.",
      generationFailedTurn: "검토를 마치지 못했습니다. 오른쪽 안내를 확인한 뒤 다시 시도해 주세요.",
    }),
    en: Object.freeze({
      refinePlaceholder: "Tell me what else to check (e.g. totals and missing unit prices)",
      allReadyIdle: "Ready to review. Start now or describe what to check.",
      allReadyWithDraft: "Keeping the review result and your inputs. Tell me what else to check.",
      generatingTurn: "Reading your file via the existing review route…",
      generatedTurn: "The review result is ready in the pane on the right. Choose 'Open in form' to edit the inputs.",
      generationFailedTurn: "The review could not finish. Check the note on the right and try again.",
    }),
  });

  function manifestTool() {
    try {
      const reg = window.PadiemUtilManifest;
      return reg && typeof reg.getTool === "function" ? reg.getTool("excel") : null;
    } catch (_) {
      return null;
    }
  }

  function fieldSpec(key) {
    const tool = manifestTool();
    const fields = tool && Array.isArray(tool.fields) ? tool.fields : [];
    return fields.find((field) => field.key === key) || null;
  }

  function fieldCopy(spec, kind) {
    if (!spec || !spec[kind]) return "";
    const locale = document.documentElement && document.documentElement.lang === "en" ? "en" : "ko";
    const text = spec[kind];
    return (text && (text[locale] || text.ko)) || "";
  }

  function element(tagName, className, text) {
    const node = document.createElement(tagName);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function authSession() {
    try {
      if (window.PadiemAuthSession && typeof window.PadiemAuthSession.get === "function") {
        const session = window.PadiemAuthSession.get();
        return session && typeof session === "object" ? session : null;
      }
    } catch (_) { /* an unreadable session is treated as unknown */ }
    return null;
  }

  function loginGate(known) {
    const gate = element("div", "util-gate");
    gate.appendChild(element("p", "util-gate-text", known ? t("loginRequired") : t("loginUnknown")));
    const login = element("button", "util-gate-login", t("login"));
    login.type = "button";
    login.addEventListener("click", () => {
      const button = document.getElementById("loginButton");
      if (button && typeof button.click === "function") button.click();
    });
    gate.appendChild(login);
    return gate;
  }

  function rowItem(label, value) {
    const item = element("li", "util-excel-summary-row");
    item.appendChild(element("span", "util-excel-summary-key", label));
    item.appendChild(element("span", "util-excel-summary-value", value));
    return item;
  }

  function renderSheets(host, sheets) {
    host.replaceChildren();
    sheets.forEach((sheet) => {
      const item = element("li", "util-excel-sheet");
      const title = sheet.empty
        ? (sheet.title || t("sheetFallback")(sheet.index)) + " · " + t("emptySheet")
        : (sheet.title || t("sheetFallback")(sheet.index));
      item.appendChild(element("span", "util-excel-sheet-title", title));
      const meta = sheet.empty
        ? t("rowsLabel") + " 0 · " + t("columnsLabel") + " 0"
        : t("rowsLabel") + " " + sheet.rows + " · " + t("columnsLabel") + " " + sheet.columns;
      item.appendChild(element("span", "util-excel-sheet-meta", meta));
      if (sheet.truncated) {
        item.appendChild(element("span", "util-excel-sheet-truncated", t("truncatedNote")));
      }
      host.appendChild(item);
    });
  }

  function renderPreview(host, preview) {
    host.replaceChildren();
    if (!preview || !Array.isArray(preview.headers) || !preview.headers.length) {
      host.appendChild(element("p", "util-excel-note", t("previewNone")));
      return;
    }
    const table = element("table", "util-excel-table");
    const caption = element("caption", null,
      (preview.sheet_title || "") + " · " + t("previewTitle"));
    table.appendChild(caption);
    const thead = element("thead");
    const headRow = element("tr");
    preview.headers.forEach((header) => {
      const th = element("th", null, String(header));
      th.setAttribute("scope", "col");
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);
    const tbody = element("tbody");
    (preview.rows || []).forEach((row) => {
      const tr = element("tr");
      (row || []).forEach((cell) => tr.appendChild(element("td", null, String(cell))));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    host.appendChild(table);
  }

  function renderSummary(host, summary) {
    host.replaceChildren();
    const sheets = summary.sheet_count;
    const readable = summary.readable_sheet_count;
    const empty = Array.isArray(summary.empty_sheet_indices)
      ? summary.empty_sheet_indices.length : 0;
    const truncated = Array.isArray(summary.truncated_sheet_titles)
      ? summary.truncated_sheet_titles.length : 0;
    host.appendChild(rowItem(t("summarySheetCount"), String(sheets)));
    host.appendChild(rowItem(t("summaryReadable"), String(readable)));
    host.appendChild(rowItem(t("summaryEmpty"), String(empty)));
    host.appendChild(rowItem(t("summaryTruncated"), String(truncated)));
    host.appendChild(rowItem(t("summaryRows"), String(summary.total_data_rows)));
    if (summary.review_note) {
      host.appendChild(rowItem(t("summaryNote"), String(summary.review_note)));
    }
  }

  function paintEmptyResult(host) {
    host.setAttribute("data-empty", "true");
    host.replaceChildren(element("p", "util-result-empty", t("emptyResult")));
  }

  async function requestReview(fileName, bytes, goal) {
    const url = "/api/util/excel/review" + (goal ? "?goal=" + encodeURIComponent(goal) : "");
    const response = await window.fetch(url, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/octet-stream",
        "X-Padiem-Filename": encodeURIComponent(fileName),
        "X-Padiem-Media-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      },
      body: bytes,
    });
    if (!response.ok) {
      const error = new Error("excel review failed");
      error.status = response.status;
      try {
        const body = await response.json();
        error.code = body && body.error && typeof body.error.code === "string" ? body.error.code : "";
        error.serverMessage = body && body.error && typeof body.error.message === "string"
          ? body.error.message : "";
      } catch (_) { /* a non-JSON refusal keeps the status sentence */ }
      throw error;
    }
    const data = await response.json().catch(() => null);
    if (!data || data.ok !== true || !data.review || !Array.isArray(data.review.sheets)) {
      const error = new Error("invalid review");
      error.code = "invalid_review";
      throw error;
    }
    return data.review;
  }

  function serverOrLocal(error) {
    // The route already answers with the shipped Korean guidance wording, so
    // the server sentence wins and the local map is only the fallback.
    if (error && error.serverMessage) return error.serverMessage;
    const status = error && error.status;
    if (status === 401 || status === 403) return t("authNeeded");
    if (status === 413) return t("tooLarge");
    if (status === 429) return t("quota");
    return t("generic");
  }

  function buildScreen(initialMode) {
    let busy = false;
    // A file attached in chat mode cannot be put back into the browser's file
    // input, so it is kept here and named next to the field; a pick made in
    // the form always wins over a carried-over file.
    let carriedFile = null;
    const wrap = element("div", "util-tool-form util-tool-workbench util-excel-form");
    wrap.setAttribute("data-util-form", "excel");

    const inputPane = element("div", "util-pane-input");
    inputPane.setAttribute("data-util-pane", "input");

    const form = element("form", "util-form");
    form.id = "utilToolForm-excel";
    form.noValidate = true;

    const fileSpec = fieldSpec("file");
    const fileField = element("label", "util-field");
    fileField.appendChild(element("span", "util-field-label",
      fieldCopy(fileSpec, "label") || "XLSX"));
    const fileInput = element("input", "util-input util-excel-file");
    fileInput.type = "file";
    fileInput.name = "file";
    fileInput.accept = (fileSpec && fileSpec.accept) || ".xlsx";
    fileField.appendChild(fileInput);
    const questionCopy = fieldCopy(fileSpec, "question");
    const questionNote = questionCopy ? element("p", "util-excel-note", questionCopy) : null;
    if (questionNote) fileField.appendChild(questionNote);
    const chosenNote = element("p", "util-excel-note util-excel-file-chosen", "");
    chosenNote.hidden = true;
    chosenNote.setAttribute("data-util-carried-file", "");
    fileField.appendChild(chosenNote);
    function syncFileFeedback() {
      const picked = readWorkbook();
      if (questionNote) questionNote.hidden = !picked.error;
      if (fileInput.getAttribute("aria-invalid") === "true") {
        if (picked.error) {
          setStatus(picked.error, "error");
        } else {
          fileInput.removeAttribute("aria-invalid");
          setStatus("", null);
        }
      }
    }
    fileInput.addEventListener("change", () => {
      carriedFile = null;
      chosenNote.hidden = true;
      chosenNote.textContent = "";
      syncFileFeedback();
    });
    form.appendChild(fileField);

    const goalSpec = fieldSpec("goal");
    const goalField = element("label", "util-field");
    goalField.appendChild(element("span", "util-field-label", fieldCopy(goalSpec, "label")));
    const goal = element("textarea", "util-input util-excel-goal");
    goal.name = "goal";
    goal.rows = (goalSpec && goalSpec.rows) || 3;
    const goalPlaceholder = fieldCopy(goalSpec, "placeholder");
    if (goalPlaceholder) goal.placeholder = goalPlaceholder;
    goalField.appendChild(goal);
    form.appendChild(goalField);

    const submit = element("button", "util-generate", t("submit"));
    submit.type = "submit";
    form.appendChild(submit);

    const resultPane = element("section", "util-result util-pane-result");
    resultPane.setAttribute("data-util-pane", "result");
    resultPane.appendChild(element("h4", "util-result-title", t("result")));
    const status = element("div", "util-excel-status", "");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    resultPane.appendChild(status);

    const output = element("div", "util-result-output");
    output.setAttribute("data-empty", "true");
    output.setAttribute("role", "region");
    output.setAttribute("aria-label", t("result"));
    resultPane.appendChild(output);

    // #7461: conversational intake — same shared seam as the other util tools
    // (PadiemUtilChatMode), the same manifest field definitions and the same
    // single server route. The optional review goal is asked conversationally
    // (an empty answer skips it) so an upload never spends a review before
    // the user can say what to look at.
    const chatApi = window.PadiemUtilChatMode;
    const hasChatMode = Boolean(
      chatApi
      && typeof chatApi.create === "function"
      && typeof chatApi.buildModeSwitch === "function"
    );

    function readValues() {
      const picked = carriedFile || (fileInput.files && fileInput.files[0]) || null;
      return { file: picked ? [picked] : [], goal: String(goal.value || "").trim() };
    }

    function writeValues(incoming) {
      if (!incoming || typeof incoming !== "object") return;
      if (Object.prototype.hasOwnProperty.call(incoming, "goal")) {
        goal.value = String(incoming.goal == null ? "" : incoming.goal);
      }
      if (Object.prototype.hasOwnProperty.call(incoming, "file")) {
        const list = Array.isArray(incoming.file) ? incoming.file.filter(Boolean) : [];
        const picked = list[0] || null;
        carriedFile = picked;
        chosenNote.textContent = picked ? String(picked.name || "") : "";
        chosenNote.hidden = !picked;
        syncFileFeedback();
      }
    }

    function hasDraft() {
      return output.getAttribute("data-empty") !== "true";
    }

    let modeSwitch = null;
    let chatIntake = null;
    function setMode(nextMode, focusChat) {
      if (!chatIntake || !modeSwitch) return;
      const toChat = nextMode === "chat";
      wrap.setAttribute("data-active-mode", toChat ? "chat" : "form");
      modeSwitch.setActive(toChat ? "chat" : "form");
      if (toChat) {
        setStatus("", null);
        form.hidden = true;
        chatIntake.root.hidden = false;
        chatIntake.enter({ focusInput: Boolean(focusChat) });
      } else {
        writeValues(chatIntake.getValues());
        chatIntake.root.hidden = true;
        form.hidden = false;
      }
    }

    if (hasChatMode) {
      chatIntake = chatApi.create({
        toolId: "excel",
        askOptional: ["goal"],
        copy: CHAT_COPY,
        getValues: () => readValues(),
        setValues: (vals) => writeValues(vals),
        hasDraft: () => hasDraft(),
        onGenerate: (vals, note) => {
          if (busy) return false;
          const list = Array.isArray(vals && vals.file) ? vals.file.filter(Boolean) : [];
          const file = list[0]
            || (carriedFile || (fileInput.files && fileInput.files[0]) || null);
          if (!file) return false;
          carriedFile = file;
          chosenNote.textContent = String(file.name || "");
          chosenNote.hidden = false;
          let goalText = String((vals && vals.goal) || "").trim();
          if (note) {
            goalText = goalText
              ? goalText + "\n" + String(note).trim()
              : String(note).trim();
          }
          return runReviewFile(file, goalText);
        },
        onSwitchToForm: () => setMode("form", false),
      });
    }

    if (chatIntake) {
      const startMode = initialMode === "chat" ? "chat" : "form";
      modeSwitch = chatApi.buildModeSwitch(startMode, (picked) => setMode(picked, picked === "chat"));
      inputPane.appendChild(modeSwitch.root);
      inputPane.appendChild(form);
      inputPane.appendChild(chatIntake.root);
      setMode(startMode, false);
    } else {
      inputPane.appendChild(form);
    }

    wrap.appendChild(inputPane);
    wrap.appendChild(resultPane);

    function setStatus(text, tone) {
      status.textContent = text || "";
      status.hidden = !text;
      status.setAttribute("data-tone", tone || "info");
    }

    function readWorkbook() {
      const file = carriedFile || (fileInput.files && fileInput.files[0]);
      if (!file) return { error: t("required") };
      const name = String(file.name || "").toLowerCase();
      if (!name.endsWith(".xlsx")) return { error: t("wrongKind") };
      return { file: file };
    }

    async function runReviewFile(file, goalText) {
      busy = true;
      submit.disabled = true;
      setStatus(t("reviewing"), "busy");
      output.setAttribute("data-empty", "false");
      output.replaceChildren();
      try {
        const bytes = await file.arrayBuffer();
        const review = await requestReview(
          file.name, bytes, String(goalText || "").trim()
        );
        const sheetsBlock = element("div", "util-excel-block");
        sheetsBlock.appendChild(element("h5", "util-excel-block-title", t("sheetsTitle")));
        const sheetList = element("ul", "util-excel-sheets");
        sheetList.setAttribute("aria-label", t("sheetsTitle"));
        renderSheets(sheetList, review.sheets);
        sheetsBlock.appendChild(sheetList);
        output.appendChild(sheetsBlock);

        const previewBlock = element("div", "util-excel-block");
        previewBlock.appendChild(element("h5", "util-excel-block-title", t("previewTitle")));
        const previewHost = element("div", "util-excel-preview");
        renderPreview(previewHost, review.preview);
        previewBlock.appendChild(previewHost);
        output.appendChild(previewBlock);

        const summaryBlock = element("div", "util-excel-block");
        summaryBlock.appendChild(element("h5", "util-excel-block-title", t("summaryTitle")));
        const summaryList = element("ul", "util-excel-summary");
        summaryList.setAttribute("aria-label", t("summaryTitle"));
        renderSummary(summaryList, review.summary);
        summaryBlock.appendChild(summaryList);
        output.appendChild(summaryBlock);

        setStatus("", null);
        return true;
      } catch (err) {
        setStatus(serverOrLocal(err), "error");
        paintEmptyResult(output);
        return false;
      } finally {
        busy = false;
        submit.disabled = false;
      }
    }

    async function runReview() {
      if (busy) return;
      const picked = readWorkbook();
      if (picked.error) {
        fileInput.setAttribute("aria-invalid", "true");
        setStatus(picked.error, "error");
        return;
      }
      await runReviewFile(picked.file, String(goal.value || "").trim());
    }

    form.addEventListener("submit", (event) => {
      if (event && typeof event.preventDefault === "function") event.preventDefault();
      void runReview();
    });
    return wrap;
  }

  let current = null;

  function mount(host) {
    if (!host || typeof host.appendChild !== "function") return false;
    host.setAttribute("data-util-mounted", "form");
    const initialMode = host.getAttribute
      && host.getAttribute("data-util-initial-mode") === "chat" ? "chat" : "form";
    const session = authSession();
    if (session && session.authenticated !== true) {
      host.appendChild(loginGate(true));
      current = { host: host };
      return true;
    }
    if (session === null) {
      host.appendChild(loginGate(false));
      current = { host: host };
      return true;
    }
    host.appendChild(buildScreen(initialMode));
    current = { host: host };
    return true;
  }

  function remount() {
    if (!current || !current.host) return;
    const host = current.host;
    if (host.isConnected === false) return;
    if (typeof host.replaceChildren !== "function") return;
    host.replaceChildren();
    mount(host);
  }

  window.addEventListener("padiem:auth-state", remount);

  window.PadiemUtilExcel = Object.freeze({ mount: mount });
})();
