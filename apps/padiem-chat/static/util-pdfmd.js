(() => {
  "use strict";

  /* #7865: the four badges the owner sees. reviewed is presented as 완료 (the
     server keeps the reviewed state; the screen groups it — no server change).
     queued is presented as 바꾸는 중 because an upload starts its conversion
     right away, so a queued row is a conversion waiting to be claimed. */
  const STATUS_LABELS = {
    queued: "바꾸는 중",
    working: "바꾸는 중",
    reviewed: "완료",
    done: "완료",
    failed: "실패",
  };

  const SCAN_MESSAGE = "스캔본이라 글자가 없어 지금은 읽을 수 없습니다. 글자가 있는 PDF를 올려 주세요.";
  const ERROR_MESSAGES = {
    unauthorized: "로그인이 필요합니다.",
    document_convert_unavailable: "일시적인 오류입니다. 잠시 후(5분 뒤) 다시 시도해 주세요.",
    document_convert_not_found: "작업을 찾을 수 없습니다. 새 작업을 시작해 주세요.",
    convert_store_unavailable: "작업 기록을 저장하지 못했습니다. 잠시 후(5분 뒤) 다시 시도해 주세요.",
    live_abuse_gate_unavailable: "일시적인 오류입니다. 잠시 후(5분 뒤) 다시 시도해 주세요.",
    conversion_failed: "일시적인 오류입니다. 잠시 후(5분 뒤) 다시 시도해 주세요.",
    pdf_encrypted: "암호가 있는 PDF는 변환할 수 없습니다. 암호를 제거한 뒤 다시 올려 주세요.",
    pdf_invalid: "PDF 형식이 아니거나 손상된 파일입니다.", pdf_no_pages: "파일에 읽을 페이지가 없습니다. 다시 확인해 주세요.",
    pdf_page_text_invalid: "파일을 끝까지 읽지 못했습니다. 다시 확인해 주세요.",
    invalid_binary_payload: "PDF 형식이 아니거나 손상된 파일입니다.", unsupported_binary_media_type: "PDF 또는 ZIP 파일만 올릴 수 있습니다.",
    pdf_page_geometry_unavailable: "파일을 끝까지 읽지 못했습니다. 다시 확인해 주세요.",
    original_object_missing: "원본 파일을 찾을 수 없습니다. 파일을 다시 올려 주세요.",
    convert_interrupted: "변환이 중단되었습니다. 다시 시도해 주세요.",
    convert_failed: "변환에 실패했습니다. 다시 시도해 주세요.",
    invalid_archive: "ZIP 파일을 열 수 없습니다.",
    empty_archive: "ZIP 파일 안에 변환할 PDF가 없습니다.",
    invalid_document: "PDF 또는 ZIP 파일만 올릴 수 있습니다.",
    document_too_large: "파일이 너무 큽니다.",
    document_size_limit: "회원 등급의 변환 크기 상한을 넘었습니다.",
    document_page_limit: "회원 등급의 페이지 상한을 넘어 변환하지 못했습니다.",
    conversion_quota_exhausted: "오늘 변환 한도를 다 썼어요. 내일 다시 이용해 주세요.",
    pdf_magic_mismatch: "PDF 형식이 아니거나 손상된 파일입니다.",
    pdf_scanned_no_text: SCAN_MESSAGE,
    convert_timed_out: "시간이 오래 걸려 변환이 끝나지 않았습니다. 다시 시도해 주세요.",
  };

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  /* #7865: one badge per card. A timed-out row (the #7842 rule carries
     error_code=convert_timed_out on the item and, since #7865, on the job
     list) reads 시간 초과 instead of a plain 실패. */
  function badgeText(entry) {
    if (entry && entry.error_code === "convert_timed_out") return "시간 초과";
    const known = Object.prototype.hasOwnProperty.call(STATUS_LABELS, entry && entry.status);
    return known ? STATUS_LABELS[entry.status] : "확인 필요";
  }

  function badgeDataStatus(entry) {
    if (entry && entry.error_code === "convert_timed_out") return "timed-out";
    const status = entry && entry.status;
    if (status === "queued" || status === "working") return "working";
    if (status === "reviewed" || status === "done") return "done";
    if (status === "failed") return "failed";
    return "unknown";
  }

  function statusChip(entry) {
    const chip = el("span", "pdfmd-status-chip", badgeText(entry));
    chip.dataset.status = badgeDataStatus(entry);
    return chip;
  }

  function modeLabel(mode) {
    return mode === "verify" ? "검증 변환" : "빠른 변환";
  }

  const HISTORY_GROUPS = [
    ["today", "pdfmd-history-today", "오늘"],
    ["yesterday", "pdfmd-history-yesterday", "어제"],
    ["this-week", "pdfmd-history-this-week", "이번 주"],
    ["earlier", "pdfmd-history-earlier", "이전"],
  ];

  // Live copy comes from the shared locale authority; the fallback keeps the
  // utility readable when locale.js is not loaded (tests, isolated harness).
  function copy(key, fallback) {
    const locale = window.__padiemLocale;
    if (locale && typeof locale.text === "function") {
      try {
        const value = locale.text(key);
        if (value && value !== key) return value;
      } catch (_) {}
    }
    return fallback;
  }

  function describeWarnings(report) {
    const list = report && Array.isArray(report.warnings) ? report.warnings : [];
    const out = [];
    list.forEach((entry) => { const w = String(entry); if (w.startsWith("unreadable_page")) out.push(SCAN_MESSAGE); else if (w.startsWith("rotated_text_layer")) out.push("글자 방향이 회전된 페이지가 있어 확인이 필요합니다."); });
    return out.length ? out.join(" ") : "";
  }
  function describeError(err, fallback) {
    if (err && err.code && ERROR_MESSAGES[err.code]) return ERROR_MESSAGES[err.code];
    if (err && err.status === 401) return ERROR_MESSAGES.unauthorized;
    return fallback || "일시적인 오류입니다. 잠시 후(5분 뒤) 다시 시도해 주세요.";
  }

  // Reuse the app's own login entries instead of a second auth surface. The
  // sidebar button opens the existing dialog and, when signed in, signs out —
  // so it is clicked only in the state that asks a guest to sign in.
  function openExistingLogin() {
    const loginButton = document.getElementById("loginButton");
    const label = loginButton ? String(loginButton.textContent || "").trim() : "";
    if (loginButton && !loginButton.hidden && !loginButton.disabled && label.indexOf("로그인") !== -1) {
      loginButton.click();
      return true;
    }
    const guestEntry = document.getElementById("guestLoginEntryButton");
    if (guestEntry) {
      guestEntry.click();
      return true;
    }
    return false;
  }

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function formatWhen(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "날짜 없음";
    return (
      date.getFullYear() + "." + pad(date.getMonth() + 1) + "." + pad(date.getDate()) +
      " " + pad(date.getHours()) + ":" + pad(date.getMinutes())
    );
  }

  function countLabel(count) {
    return (Number(count) || 0) + "개 파일";
  }

  function emptyBlock(title, detail, steps, titleKey, detailKey) {
    const box = el("div", "pdfmd-empty");
    const head = el("strong", null, title);
    if (titleKey) head.dataset.localeKey = titleKey;
    box.appendChild(head);
    if (detail) {
      const note = el("p", null, detail);
      if (detailKey) note.dataset.localeKey = detailKey;
      box.appendChild(note);
    }
    if (steps && steps.length) {
      const list = document.createElement("ol");
      steps.forEach((step) => list.appendChild(el("li", null, step)));
      box.appendChild(list);
    }
    return box;
  }

  async function api(path, opts) {
    const res = await fetch(path, Object.assign({ credentials: "include" }, opts || {}));
    let data = null;
    try { data = await res.json(); } catch (_) { data = null; }
    if (!res.ok) {
      const err = new Error("http_" + res.status);
      err.status = res.status;
      if (data && data.error && data.error.code) err.code = data.error.code;
      throw err;
    }
    return data;
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  }

  let pcExchangeLoading = null;

  function loadPcExchange() {
    if (window.PadiemPcFileExchange) return Promise.resolve(window.PadiemPcFileExchange);
    if (pcExchangeLoading) return pcExchangeLoading;
    pcExchangeLoading = new Promise((resolve, reject) => {
      const head = document.head || document.body;
      if (head && !document.querySelector('link[href="./pc-file-exchange.css"]')) {
        const css = document.createElement("link");
        css.rel = "stylesheet";
        css.href = "./pc-file-exchange.css";
        head.appendChild(css);
      }
      const script = document.createElement("script");
      script.src = "./pc-file-exchange.js";
      script.addEventListener("load", () => {
        if (window.PadiemPcFileExchange) resolve(window.PadiemPcFileExchange);
        else reject(new Error("pc-exchange-unavailable"));
      }, { once: true });
      script.addEventListener("error", () => reject(new Error("pc-exchange-unavailable")), { once: true });
      head.appendChild(script);
    });
    return pcExchangeLoading;
  }

  async function pcLinked() {
    if (window.PadiemAuthGate?.authenticated() === false) return null;
    try {
      const res = await fetch("/api/pc/pairings", { credentials: "include", cache: "no-store" });
      if (!res.ok) return null;
      const body = await res.json().catch(() => null);
      const links = body && Array.isArray(body.links) ? body.links : [];
      return links.some((link) => link && link.state === "active");
    } catch (_) {
      return null;
    }
  }

  // The existing Connectors surface owns the computer card: no second pairing screen.
  function openPcConnect() {
    const opener = document.getElementById("connectorsNavButton");
    if (opener) opener.click();
    const card = document.getElementById("connectorComputerCard");
    if (!card) return;
    if (!card.hasAttribute("tabindex")) card.setAttribute("tabindex", "-1");
    if (typeof card.focus === "function") card.focus({ preventScroll: true });
    if (typeof card.scrollIntoView === "function") card.scrollIntoView({ block: "nearest" });
  }

  function resultName(name) {
    return (name.replace(/\.[^.]+$/, "") || "document") + ".md";
  }

  const PC_COPY = {
    pick: "내 PC에서 가져오기",
    ready: "준비 중",
    checking: "확인 중",
    noPc: "컴퓨터를 연결하면 내 PC의 PDF를 가져올 수 있습니다.",
    saveNoPc: "컴퓨터를 연결하면 내 PC에 저장할 수 있습니다.",
    connect: "컴퓨터 연결하기",
    save: "내 PC에 저장",
    saving: "내 PC에 저장하는 중...",
    saved: "내 PC에 저장했습니다.",
    noSave: "PC에 저장할 창을 열지 못했습니다. 잠시 후 다시 시도해 주세요.",
    saveFailed: "저장할 결과를 불러오지 못했습니다.",
    noFile: "PC에서 가져온 파일을 읽지 못했습니다.",
  };

  // #5710 COM2 migration kill switch, kept verbatim (#6012 contract): existing
  // downloads remain available even while new work is hard-paused here.
  const PDFMD_NEW_WORK_DISABLED = true; // #5710 COM2 migration, existing downloads remain.

  window.initPdfMdUtility = function (panel, workState = "checking") {
    // Four states, and only an answer may claim the last three: "checking" is
    // the first paint, "open" and "paused" come from the list route, and
    // "login_required" comes from a 401. A guest is asked to sign in; only the
    // server's pause answer may say the work itself is stopped.
    const PDFMD_LOGIN_REQUIRED = workState === "login_required";
    const PDFMD_CHECKING = workState !== "open" && workState !== "paused" && workState !== "login_required";
    const PDFMD_NEW_WORK_DISABLED = workState === "paused";
    // Everything that refuses an action: an answer or a promise refuses, an
    // unknown never refuses but still cannot act.
    const workBlocked = PDFMD_NEW_WORK_DISABLED || PDFMD_LOGIN_REQUIRED || PDFMD_CHECKING;
    panel.replaceChildren();
    panel.classList.add("pdfmd-shell");

    const inputCol = el("div", "util-pane-input pdfmd-input-col");
    inputCol.setAttribute("data-util-pane", "input");
    const resultCol = el("div", "util-pane-result pdfmd-result-col");
    resultCol.setAttribute("data-util-pane", "result");
    /* 머리(#7865 바꿀 모양 1): 도구 이름은 화면 머리(manifest 제목)가 이미
       말하고, 판 머리 오른쪽에는 오늘 남은 건수와 작은 폼/대화 전환이 놓인다. */
    const headRow = el("div", "pdfmd-head-row");
    const quotaNote = el("span", "pdfmd-quota", "");
    quotaNote.id = "pdfmdQuota";
    quotaNote.setAttribute("role", "status");
    quotaNote.setAttribute("aria-live", "polite");
    headRow.appendChild(quotaNote);

    const pauseNote = el("p", "pdfmd-status", "");
    pauseNote.setAttribute("role", "status");
    if (PDFMD_NEW_WORK_DISABLED) {
      pauseNote.textContent = "지금은 새 변환을 시작할 수 없습니다. 기존 작업 이력과 결과 다운로드는 그대로 이용할 수 있습니다.";
    } else if (PDFMD_LOGIN_REQUIRED) {
      pauseNote.textContent = "";
      pauseNote.appendChild(el("span", null, "로그인 후 PDF 변환을 이용할 수 있습니다. "));
      const loginEntry = el("button", "pdfmd-link", "로그인");
      loginEntry.type = "button";
      loginEntry.id = "pdfmdLoginEntry";
      loginEntry.addEventListener("click", openExistingLogin);
      pauseNote.appendChild(loginEntry);
    } else if (PDFMD_CHECKING) {
      pauseNote.textContent = "새 변환을 열 수 있는지 확인 중…";
    }
    if (!pauseNote.firstChild) pauseNote.hidden = true;
    if (!pauseNote.firstChild) pauseNote.hidden = true;
    headRow.appendChild(pauseNote);
    const modeSwitchHost = el("div", "pdfmd-head-switch");
    headRow.appendChild(modeSwitchHost);
    /* 머리 행은 입력 칸 안이 아니라 판 맨 위 전체 폭 — 머리 오른쪽에 전환이 놓인다. */
    panel.appendChild(headRow);

    panel.appendChild(inputCol);
    panel.appendChild(resultCol);


    /* 올리기 칸(#7865 바꿈 모양 2): 큰 끌어 놓기 칸 하나, 그 아래 글자 링크. */
    const formWrap = el("div", "util-form pdfmd-form-body");
    formWrap.id = "utilToolForm-pdfmd";
    const controls = el("div", "pdfmd-controls");
    const modeSel = document.createElement("select");
    modeSel.id = "pdfmdMode";
    /* #7865: the always-visible 변환 방식 field is gone and the choice is one
       quiet line. 검증 변환 stays reachable — the server accepts both modes
       and the per-page agreement report depends on it, so removing the select
       entirely would lose a working feature (the issue's 하나뿐인 premise does
       not hold). */
    [["fast", "빠른 변환"], ["verify", "검증 변환"]].forEach(([v, t]) => {
      const o = document.createElement("option");
      o.value = v; o.textContent = t;
      if (v === "fast") o.selected = true;
      modeSel.appendChild(o);
    });
    modeSel.disabled = workBlocked;
    modeSel.setAttribute("aria-label", "변환 방식");
    controls.appendChild(modeSel);
    formWrap.appendChild(controls);

    const drop = el("div", "pdfmd-drop");
    drop.setAttribute("role", "button");
    drop.tabIndex = 0;
    drop.setAttribute("aria-label", "PDF 또는 ZIP 파일 선택");
    const dropTitle = el("span", "pdfmd-drop-title", "PDF를 끌어다 놓거나 골라 주세요.");
    const dropSub = el("span", "pdfmd-drop-sub", "여러 개나 ZIP도 됩니다.");
    dropSub.id = "pdfmdDropHint";
    const dropCta = el("button", "pdfmd-drop-cta", "파일 고르기");
    dropCta.type = "button";
    drop.appendChild(dropTitle);
    drop.appendChild(dropSub);
    drop.appendChild(dropCta);
    drop.setAttribute("aria-describedby", "pdfmdDropHint");
    if (workBlocked) {
      drop.removeAttribute("role");
      drop.removeAttribute("tabindex");
      drop.removeAttribute("aria-label");
      drop.classList.add("pdfmd-paused");
      drop.style.opacity = "0.65";
      if (PDFMD_NEW_WORK_DISABLED) {
        dropTitle.textContent = "PDF 업로드 준비 중";
        dropSub.textContent = "곧 다시 이용할 수 있어요.";
        dropCta.textContent = "업로드 일시 중단";
      } else if (PDFMD_LOGIN_REQUIRED) {
        dropTitle.textContent = "로그인이 필요합니다";
        dropSub.textContent = "로그인 후 PDF를 올려 변환할 수 있습니다.";
        dropCta.textContent = "로그인 필요";
      } else {
        dropTitle.textContent = "PDF 파일을 선택하세요";
        dropSub.textContent = "방금 연 화면 · 잠시 후 자동으로 정해집니다.";
        dropCta.textContent = "확인 중";
      }
    }
    if (PDFMD_NEW_WORK_DISABLED || PDFMD_LOGIN_REQUIRED) drop.style.cursor = "not-allowed";

    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.multiple = true;
    fileInput.accept = ".pdf,.zip,application/pdf,application/zip";
    fileInput.hidden = true;
    fileInput.disabled = workBlocked;
    formWrap.appendChild(fileInput);

    formWrap.appendChild(drop);

    // #6012: the same documents, taken straight from the owner's own PC — a
    // text link under the upload box (#7865), not a second big button.
    const pcPick = el("button", "pdfmd-link pdfmd-pc-pick", PC_COPY.pick);
    pcPick.type = "button";
    pcPick.id = "pdfmdPcPick";
    pcPick.addEventListener("click", async () => {
      // An unlinked computer gets the same sentence the council app shows,
      // never a dialog that can only fail inside.
      if (await pcLinked() !== true) { showPcNote(); return; }
      let component;
      try {
        component = await loadPcExchange();
      } catch (_) {
        component = null;
      }
      if (!component || typeof component.open !== "function") {
        uploadStatus.textContent = PC_COPY.noSave;
        return;
      }
      component.open({
        mode: "import",
        onSelect: (picked) => { void importFromPc(picked); },
      });
    });
    if (workBlocked) {
      pcPick.disabled = true;
      pcPick.textContent = PC_COPY.pick + " · " + (PDFMD_NEW_WORK_DISABLED ? PC_COPY.ready : PDFMD_LOGIN_REQUIRED ? "로그인 필요" : PC_COPY.checking);
    }
    const pcLinkRow = el("div", "pdfmd-upload-foot");
    pcLinkRow.appendChild(pcPick);
    formWrap.appendChild(pcLinkRow);

    const pcNote = el("p", "pdfmd-status pdfmd-pc-note", "");
    pcNote.id = "pdfmdPcNote";
    pcNote.hidden = true;
    const pcNoteText = el("span", null, PC_COPY.noPc + " ");
    const pcConnect = el("button", "pdfmd-link", PC_COPY.connect);
    pcConnect.type = "button";
    pcConnect.addEventListener("click", openPcConnect);
    pcNote.appendChild(pcNoteText);
    pcNote.appendChild(pcConnect);
    formWrap.appendChild(pcNote);

    // What happens to the bytes, said once, where the files go in. There is no
    // automatic expiry, so the sentence promises none: the owner's delete is
    // the only thing that removes an original or a result.
    const retentionNote = el(
      "p",
      "pdfmd-retention-note",
      copy(
        "pdfmd-retention-note",
        "올린 원본과 변환 결과는 사용자가 지울 때까지 보관됩니다. 항목을 지우면 그 항목의 원본과 변환 결과가 함께 지워집니다."
      )
    );
    retentionNote.dataset.localeKey = "pdfmd-retention-note";
    formWrap.appendChild(retentionNote);

    function showPcNote(message) {
      pcNoteText.textContent = (message || PC_COPY.noPc) + " ";
      pcNote.hidden = false;
      if (typeof pcNote.scrollIntoView === "function") {
        try { pcNote.scrollIntoView({ block: "nearest" }); } catch (_) {}
      }
      if (typeof pcConnect.focus === "function") {
        try { pcConnect.focus({ preventScroll: true }); } catch (_) {}
      }
    }

    // Only an answer that there is no PC shows the notice; a failed check stays quiet.
    void pcLinked().then((linked) => {
      if (linked === false) pcNote.hidden = false;
    });

    const uploadStatus = el("div", "pdfmd-status", "");
    uploadStatus.id = "pdfmdStatus";
    uploadStatus.setAttribute("role", "status");
    uploadStatus.setAttribute("aria-live", "polite");
    if (!window.PadiemUtilChatMode || typeof window.PadiemUtilChatMode.bindPdfmd !== "function") {
      inputCol.appendChild(formWrap);
    }
    inputCol.appendChild(uploadStatus);
    const uploadProgress = el("ol", "pdfmd-upload-progress");
    uploadProgress.hidden = true;
    uploadProgress.setAttribute("aria-label", "파일별 업로드 진행 상태");
    inputCol.appendChild(uploadProgress);

    // 모두 ZIP (#7865 바꿀 모양 4): 결과 위에, 여러 파일일 때만 나온다.
    const zipBar = el("div", "pdfmd-zipbar");
    const allZipBtn = el("button", "pdfmd-btn", "모두 ZIP으로 받기");
    allZipBtn.type = "button";
    allZipBtn.hidden = true;
    zipBar.appendChild(allZipBtn);
    resultCol.appendChild(zipBar);

    // Items
    const itemsWrap = el("div", "pdfmd-items");
    resultCol.appendChild(itemsWrap);

    // Preview
    const previewWrap = el("div", "pdfmd-preview");
    previewWrap.hidden = true;
    const previewTitle = el("h4", null, "원본과 변환본 비교");
    previewWrap.appendChild(previewTitle);
    const reviewSummary = el("p", "pdfmd-review-summary", "");
    reviewSummary.setAttribute("role", "status");
    previewWrap.appendChild(reviewSummary);

    const pageControls = el("div", "pdfmd-page-controls");
    const previousPageBtn = el("button", "pdfmd-btn", "이전 페이지");
    previousPageBtn.type = "button";
    previousPageBtn.setAttribute("aria-label", "이전 페이지");
    const pageInputLabel = el("label", null, "페이지 ");
    const pageInput = document.createElement("input");
    pageInput.type = "number";
    pageInput.min = "1";
    pageInput.value = "1";
    pageInput.className = "pdfmd-page-input";
    pageInput.setAttribute("aria-label", "이동할 페이지");
    const pageTotal = el("span", "pdfmd-page-total", "/ 1");
    const pageReviewFlag = el("span", "pdfmd-page-review-flag", "");
    pageInputLabel.appendChild(pageInput);
    pageInputLabel.appendChild(pageTotal);
    pageInputLabel.appendChild(pageReviewFlag);
    const nextPageBtn = el("button", "pdfmd-btn", "다음 페이지");
    nextPageBtn.type = "button";
    nextPageBtn.setAttribute("aria-label", "다음 페이지");
    pageControls.appendChild(previousPageBtn);
    pageControls.appendChild(pageInputLabel);
    pageControls.appendChild(nextPageBtn);
    previewWrap.appendChild(pageControls);

    const previewGrid = el("div", "pdfmd-preview-grid");

    // #7834: one rendered image of the page being compared. The pane itself,
    // its fallback and its page URL live in util-pdfmd-pages.js.
    const original = window.PadiemPdfMdOriginalPane.create(el);
    const origPane = original.pane;

    const mdPane = el("div", "pdfmd-pane");
    mdPane.appendChild(el("span", "pdfmd-pane-label", "Markdown 변환본"));
    const mdView = el("div", "pdfmd-md");
    mdView.tabIndex = 0;
    mdView.setAttribute("role", "region");
    mdView.setAttribute("aria-label", "Markdown 변환본");
    mdPane.appendChild(mdView);

    previewGrid.appendChild(origPane);
    previewGrid.appendChild(mdPane);
    previewWrap.appendChild(previewGrid);
    resultCol.appendChild(previewWrap);

    /* 지난 변환(#7865 바꿀 모양 5): 접힌 한 줄, 펼치면 날짜·파일 이름·배지 목록. */
    const histFold = el("details", "pdfmd-history-fold");
    const histSummary = el("summary", "pdfmd-history-summary", "지난 변환");
    histSummary.setAttribute("aria-label", "지난 변환 펼치기");
    histFold.appendChild(histSummary);
    const histBody = el("div", "pdfmd-history-body");
    const histTools = el("div", "pdfmd-history-tools");
    histTools.hidden = true;
    const histSearch = document.createElement("input");
    histSearch.type = "search";
    histSearch.id = "pdfmdHistorySearch";
    histSearch.className = "pdfmd-history-search";
    histSearch.autocomplete = "off";
    histSearch.setAttribute("data-locale-placeholder", "pdfmd-history-search-placeholder");
    histSearch.setAttribute("data-locale-aria-label", "pdfmd-history-search-label");
    histSearch.placeholder = copy("pdfmd-history-search-placeholder", "날짜·파일명·상태로 검색");
    histSearch.setAttribute("aria-label", copy("pdfmd-history-search-label", "작업 이력 검색"));
    histTools.appendChild(histSearch);
    histBody.appendChild(histTools);
    const histList = el("div", "pdfmd-history");
    histBody.appendChild(histList);
    histFold.appendChild(histBody);
    resultCol.appendChild(histFold);

    let currentJobId = null;
    let currentItems = [];
    let lastUploadError = "";
    let previewItem = null;
    let previewPageNumber = 1;
    // While this window is open the pane is being moved by a control, so the
    // scroll listener must not read the page back out of the scroll position.
    let previewPageUntil = 0;
    const PREVIEW_PAGE_GUARD_MS = 900;
    let previewPageCount = 1;
    let previewReviewPages = new Set();
    let historyJobs = [];
    let historyQuery = "";
    const itemNames = new Map();
    const pcOrigin = new Map();

    // The conversion runs server-side after a 202, so the panel follows the
    // item detail until the result is stored. A reopened panel rebuilds the
    // DOM; a poller whose itemsWrap left the document stops quietly.
    const POLL_INTERVAL_MS = 2000;
    const polledItems = new Set();
    // #7865: uploads start their own conversion, so a queued row is claimed
    // once — the same intent the old 변환 실행 button carried.
    const autoRunItems = new Set();

    function reviewPagesFor(item) {
      return new Set(window.PadiemPdfMdPageMap.reviewPages(item && item.report));
    }

    function setPreviewPage(value, scrollMarkdown = true, fromControl = false) {
      const page = window.PadiemPdfMdPageMap.pageTarget(value, previewPageCount);
      previewPageNumber = page;
      pageInput.value = String(page);
      pageInput.max = String(previewPageCount);
      pageTotal.textContent = "/ " + previewPageCount;
      previousPageBtn.disabled = page <= 1;
      nextPageBtn.disabled = page >= previewPageCount;
      pageReviewFlag.textContent = previewReviewPages.has(page) ? " · 확인 필요" : "";
      pageReviewFlag.dataset.review = previewReviewPages.has(page) ? "true" : "false";
      if (fromControl) previewPageUntil = Date.now() + PREVIEW_PAGE_GUARD_MS;
      original.show(previewItem, page);
      if (scrollMarkdown) {
        const block = mdView.querySelector('[data-page="' + page + '"]');
        if (block) block.scrollIntoView({ block: "start", behavior: "smooth" });
      }
    }

    function renderMarkdownPreview(markdown, item) {
      const pages = window.PadiemPdfMdPageMap.splitPages(markdown);
      previewItem = item;
      previewReviewPages = reviewPagesFor(item);
      previewPageCount = Math.max(pages.length, Number(item.page_count) || 1);
      mdView.replaceChildren();
      pages.forEach((page) => {
        const block = el("section", "pdfmd-page");
        block.dataset.page = String(page.number);
        block.setAttribute("aria-label", page.number + "쪽");
        const heading = el("div", "pdfmd-page-heading", page.number + "쪽");
        if (previewReviewPages.has(page.number)) {
          heading.appendChild(el("span", "pdfmd-page-review-badge", "확인 필요"));
        }
        const text = el("pre", "pdfmd-page-text", page.text);
        block.appendChild(heading);
        block.appendChild(text);
        mdView.appendChild(block);
      });

      const summary = item.report && item.report.agreement_summary;
      const summarizedCount = summary && Number(summary.review_page_count) || 0;
      const exactPages = Array.from(previewReviewPages).sort((a, b) => a - b);
      if (exactPages.length) {
        reviewSummary.textContent = "확인 필요: " + exactPages.join(", ") + "쪽. 원본 PDF에서 표시한 페이지를 확인해 주세요.";
      } else if (summarizedCount) {
        reviewSummary.textContent = "확인 필요 페이지 " + summarizedCount + "쪽이 있습니다. 원본 PDF에서 확인해 주세요.";
      } else if (describeWarnings(item.report)) {
        reviewSummary.textContent = describeWarnings(item.report);
      } else {
        reviewSummary.textContent = "확인 필요 페이지가 없습니다.";
      }
      setPreviewPage(1);
    }

    previousPageBtn.addEventListener("click", () => setPreviewPage(previewPageNumber - 1, true, true));
    nextPageBtn.addEventListener("click", () => setPreviewPage(previewPageNumber + 1, true, true));
    pageInput.addEventListener("change", () => setPreviewPage(pageInput.value, true, true));
    pageInput.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      setPreviewPage(pageInput.value, true, true);
      if (typeof pageInput.blur === "function") pageInput.blur();
    });
    mdView.addEventListener("scroll", () => {
      // A page chosen by a control stays chosen: the last page of a document
      // cannot always be scrolled to the top, and reading that clamp as "the
      // owner is still on the page before" is what moved the numbers back.
      if (Date.now() < previewPageUntil) return;
      if (document.activeElement === pageInput) return;
      const top = mdView.getBoundingClientRect().top;
      const rows = [];
      mdView.querySelectorAll(".pdfmd-page").forEach((block) => {
        rows.push({ page: Number(block.dataset.page), top: block.getBoundingClientRect().top - top });
      });
      const scrollable = Number(mdView.scrollHeight) - Number(mdView.clientHeight);
      const atEnd = scrollable > 4 && Number(mdView.scrollTop) + Number(mdView.clientHeight) >= Number(mdView.scrollHeight) - 4;
      const visiblePage = window.PadiemPdfMdPageMap.pageForScroll(rows, 0, 24, atEnd);
      if (visiblePage && visiblePage !== previewPageNumber) setPreviewPage(visiblePage, false);
    });

    async function pollItemUntilTerminal(jobId, item) {
      if (polledItems.has(item.id)) return;
      polledItems.add(item.id);
      try {
        while (true) {
          await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
          if (!itemsWrap.isConnected) return;
          let data = null;
          try {
            data = await api("/api/document-conversions/items/" + item.id);
          } catch (_) {
            continue; // a transient read failure must not end the watch
          }
          const status = data && data.item && data.item.status;
          if (status === "queued" || status === "working") continue;
          if (jobId === currentJobId) await loadJob();
          await loadHistory();
          if (status === "failed") {
            uploadStatus.textContent = item.name + " 변환 실패. " + describeError({ code: (data.item && data.item.error_code) || "convert_failed" });
          } else if (status === "reviewed" || status === "done") {
            uploadStatus.textContent = item.name + " 변환 완료. 결과 카드에서 받을 수 있습니다.";
          }
          return;
        }
      } finally {
        polledItems.delete(item.id);
      }
    }

    // Re-entry: a panel opened while a conversion runs keeps watching it.
    function pollWorkingItemsOfJob(jobId) {
      (async () => {
        let data = null;
        try {
          data = await api("/api/document-conversions/" + jobId);
        } catch (_) {
          return;
        }
        (data && data.items || []).forEach((item) => {
          if (item.status === "working") void pollItemUntilTerminal(jobId, item);
        });
      })();
    }

    function markActiveHistory() {
      histList.querySelectorAll(".pdfmd-history-item").forEach((btn) => {
        if (btn.dataset.jobId === currentJobId) btn.setAttribute("aria-current", "true");
        else btn.removeAttribute("aria-current");
      });
    }

    function setJobId(id) {
      if (id !== currentJobId) {
        previewWrap.hidden = true;
        previewItem = null;
        mdView.replaceChildren();
        original.reset();
      }
      currentJobId = id;
      allZipBtn.hidden = !id;
      markActiveHistory();
    }

    /* #7865: [새 작업] 단추는 없어졌지만 대화 모드가 방식을 바꾸며 작업을
       내려놓을 때 쓰는 경로는 남는다 — 파일을 올리면 새 작업이 자동으로
       만들어지므로 화면에는 이 단추가 다시 나오지 않는다. */
    function startNewJob() {
      if (workBlocked) return;
      currentItems = [];
      setJobId(null);
      uploadStatus.textContent = "새 작업을 시작합니다. 파일을 고르세요.";
      renderItems();
      if (typeof drop.focus === "function") drop.focus();
    }

    async function createJob() {
      if (workBlocked) return;
      const mode = modeSel.value;
      uploadStatus.textContent = "작업을 준비하는 중...";
      try {
        const data = await api("/api/document-conversions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mode: mode }),
        });
        setJobId(data.job.id);
        await loadJob();
        await loadHistory();
      } catch (e) {
        uploadStatus.textContent = "작업을 만들지 못했습니다. " + describeError(e);
      }
    }

    // #6012: a file chosen in the shared dialog comes back as the file lane's
    // id; its bytes are read once and handed to the SAME upload the browser
    // path uses, so there is one conversion and one ledger.
    async function importFromPc(picked) {
      if (!picked || !picked.fileId || workBlocked) return;
      const name = picked.name || "문서.pdf";
      uploadStatus.textContent = name + " 가져오는 중...";
      let blob;
      try {
        const res = await fetch(
          "/api/pc/file?dispatch_id=" + encodeURIComponent(picked.fileId),
          { credentials: "include", cache: "no-store" },
        );
        if (!res.ok) throw new Error("http_" + res.status);
        blob = await res.blob();
      } catch (e) {
        uploadStatus.textContent = name + " " + PC_COPY.noFile + " " + describeError(e);
        return;
      }
      const isZip = name.toLowerCase().endsWith(".zip");
      const file = new File([blob], name, { type: isZip ? "application/zip" : "application/pdf" });
      if (await uploadFile(file)) pcOrigin.set(name, picked.folder || ".");
    }

    async function uploadFile(file, onProgress) {
      if (workBlocked) return false;
      const update = (message) => {
        uploadStatus.textContent = message;
        if (typeof onProgress === "function") onProgress(message);
      };
      lastUploadError = "";
      if (!currentJobId) {
        update(file.name + " 작업 준비 중...");
        await createJob();
      }
      if (!currentJobId) {
        update(file.name + " 업로드 실패. 작업을 만들지 못했습니다.");
        return false;
      }
      const isZip = file.name.toLowerCase().endsWith(".zip") || file.type === "application/zip";
      const mediaType = isZip ? "application/zip" : "application/pdf";
      update(file.name + " 업로드 중...");
      try {
        const buf = await file.arrayBuffer();
        const data = await api("/api/document-conversions/" + currentJobId + "/files", {
          method: "POST",
          headers: {
            "Content-Type": "application/octet-stream",
            "X-Padiem-Filename": encodeURIComponent(file.name),
            "X-Padiem-Media-Type": mediaType,
          },
          body: buf,
        });
        const createdCount = Array.isArray(data.items) ? data.items.length : 0;
        const rejected = Array.isArray(data.rejected) ? data.rejected : [];
        const details = rejected.map((entry) => entry.name).join(", ");
        const summary = file.name + ": PDF " + createdCount + "개 추가 · " +
          rejected.length + "개 건너뜀" + (details ? " (" + details + ")" : "");
        update(summary);
        await loadJob();
        return true;
      } catch (e) {
        lastUploadError = describeError(e);
        update(file.name + " 업로드 실패. " + lastUploadError);
        return false;
      }
    }

    let chatBridge = { recordFiles() {}, sync() {}, enterChat() {} };
    async function uploadFiles(files) {
      if (workBlocked) return;
      if (!files.length) return;
      chatBridge.recordFiles(files);
      uploadProgress.replaceChildren();
      uploadProgress.hidden = false;
      const rows = files.map((file) => {
        const row = el("li", "pdfmd-upload-progress-row");
        row.appendChild(el("span", "pdfmd-upload-progress-name", file.name));
        const state = el("span", "pdfmd-upload-progress-state", "대기 중");
        row.appendChild(state);
        uploadProgress.appendChild(row);
        return state;
      });
      let uploaded = 0;
      let failed = 0;
      for (let index = 0; index < files.length; index += 1) {
        const name = files[index].name;
        const onProgress = (message) => {
          rows[index].textContent = message.startsWith(name + ": ")
            ? message.slice(name.length + 2)
            : message.startsWith(name + " ") ? message.slice(name.length + 1) : message;
        };
        if (await uploadFile(files[index], onProgress)) uploaded += 1;
        else failed += 1;
      }
      if (uploaded && !failed) {
        uploadStatus.textContent = uploaded + "개 파일을 올렸습니다. 변환이 곧 시작됩니다.";
      } else if (uploaded && failed) {
        uploadStatus.textContent = uploaded + "개 파일 처리 완료, " + failed + "개 실패. " + (lastUploadError || "파일 형식을 확인해 주세요.");
      } else if (failed) {
        uploadStatus.textContent = failed + "개 파일을 처리하지 못했습니다. " + (lastUploadError || "파일 형식을 확인해 주세요.");
      }
      if (uploaded) await loadHistory();
    }

    function openPicker() {
      if (workBlocked) return;
      fileInput.click();
    }
    drop.addEventListener("click", openPicker);
    drop.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openPicker();
      }
    });
    drop.addEventListener("dragover", (e) => { e.preventDefault(); if (!workBlocked) drop.classList.add("dragover"); });
    drop.addEventListener("dragleave", () => drop.classList.remove("dragover"));
    drop.addEventListener("drop", (e) => {
      e.preventDefault();
      if (workBlocked) return;
      drop.classList.remove("dragover");
      if (e.dataTransfer && e.dataTransfer.files) uploadFiles(Array.from(e.dataTransfer.files));
    });
    fileInput.addEventListener("change", () => {
      if (fileInput.files) uploadFiles(Array.from(fileInput.files));
      fileInput.value = "";
    });

    async function loadJob() {
      if (!currentJobId) {
        renderItems();
        return;
      }
      try {
        const data = await api("/api/document-conversions/" + currentJobId);
        currentItems = data.items || [];
        itemNames.set(currentJobId, currentItems.map((item) => item.name).filter(Boolean));
        renderItems();
        if (historyQuery.trim()) renderHistory();
        currentItems.forEach((item) => {
          if (item.status === "working" && !item.has_markdown) {
            void pollItemUntilTerminal(currentJobId, item);
          }
        });
        void runQueuedItems();
      } catch (e) {
        uploadStatus.textContent = "작업을 불러오지 못했습니다. " + describeError(e);
      }
    }

    /* #7865: an upload starts its own conversion. A queued row (fresh upload or
       a reopened job the owner came back for) claims itself once; the poller
       repaints when the row reaches a terminal state. */
    async function runQueuedItems() {
      if (workBlocked) return;
      const queued = currentItems.filter((item) => item.status === "queued" && !item.has_markdown);
      let started = 0;
      for (const item of queued) {
        if (autoRunItems.has(item.id)) continue;
        autoRunItems.add(item.id);
        try {
          const data = await api("/api/document-conversions/items/" + item.id + "/run", { method: "POST" });
          started += 1;
          if (data && data.conversion && Number.isFinite(Number(data.conversion.remaining))) {
            quotaNote.textContent = "오늘 " + Number(data.conversion.remaining) + "건 더 바꿀 수 있어요.";
          }
          if (data && data.item && data.item.status === "working") {
            void pollItemUntilTerminal(currentJobId, data.item);
          }
        } catch (e) {
          uploadStatus.textContent = item.name + " 변환 시작 실패. " + describeError(e);
        }
      }
      /* 한 번 실제로 시작했을 때만 다시 읽는다 — 서버가 계속 queued를 돌려주는
         경우(시험 대역·일시 오류)에 loadJob→runQueuedItems 재귀가 무한히
         돌지 않도록 하는 유일한 안전장치다. */
      if (started) await loadJob();
    }

    function syncZipBar() {
      const available = currentItems.filter((item) => item.has_markdown);
      allZipBtn.hidden = !currentJobId || available.length < 2;
      chatBridge.sync();
    }

    async function deleteItem(item) {
      try {
        await api("/api/document-conversions/items/" + item.id, { method: "DELETE" });
        await loadJob();
        await loadHistory();
      } catch (e) {
        uploadStatus.textContent = "파일을 삭제하지 못했습니다. " + describeError(e);
      }
    }

    function deleteButton(item) {
      /* 실패 카드의 유일한 단추(#7865): 이유 한 줄 + 지우기. */
      const delBtn = el("button", "pdfmd-btn", "지우기");
      delBtn.type = "button";
      delBtn.setAttribute("aria-label", item.name + " 삭제");
      delBtn.addEventListener("click", () => { void deleteItem(item); });
      return delBtn;
    }

    function moreMenu(item) {
      /* ··· 메뉴(#7865 바꿀 모양 3): 대화로 다듬기 · 내 PC에 저장 · 원본 PDF · 지우기 */
      /* 메뉴 카드는 .pdfmd-item 을 기준점으로 오른쪽 정렬해 열린다. */
      const more = el("details", "pdfmd-more");
      const summary = el("summary", "pdfmd-more-btn", "···");
      summary.setAttribute("aria-label", item.name + " 더보기");
      more.appendChild(summary);
      const menu = el("div", "pdfmd-more-menu");
      menu.setAttribute("role", "menu");

      const refine = el("button", "pdfmd-btn pdfmd-menu-item", "대화로 다듬기");
      refine.type = "button";
      refine.setAttribute("role", "menuitem");
      /* #7865: the old archive-row refine button moved here — the same marker
         keeps the chat-mode contract findable at the new place. */
      refine.setAttribute("data-util-refine-chat", "");
      refine.disabled = workBlocked;
      refine.addEventListener("click", () => {
        more.removeAttribute("open");
        chatBridge.enterChat();
      });
      menu.appendChild(refine);

      const pcSaveBtn = el("button", "pdfmd-btn pdfmd-menu-item", PC_COPY.save);
      pcSaveBtn.type = "button";
      pcSaveBtn.setAttribute("role", "menuitem");
      pcSaveBtn.setAttribute("aria-label", item.name + " " + PC_COPY.save);
      pcSaveBtn.addEventListener("click", async () => {
        more.removeAttribute("open");
        if (await pcLinked() !== true) { showPcNote(PC_COPY.saveNoPc); return; }
        let component;
        try {
          component = await loadPcExchange();
        } catch (_) {
          component = null;
        }
        if (!component || typeof component.open !== "function") {
          uploadStatus.textContent = PC_COPY.noSave;
          return;
        }
        uploadStatus.textContent = PC_COPY.saving;
        let markdown;
        try {
          const res = await fetch(
            "/api/document-conversions/items/" + item.id + "/markdown?display=inline",
            { credentials: "include" },
          );
          if (!res.ok) throw new Error("http_" + res.status);
          markdown = await res.text();
        } catch (e) {
          uploadStatus.textContent = PC_COPY.saveFailed + " " + describeError(e);
          return;
        }
        component.open({
          mode: "save",
          content: markdown,
          fileName: resultName(item.name),
          startFolder: pcOrigin.get(item.name) || ".",
          onSave: () => { uploadStatus.textContent = PC_COPY.saved; },
        });
      });
      menu.appendChild(pcSaveBtn);

      const origBtn = el("button", "pdfmd-btn pdfmd-menu-item", "원본 PDF");
      origBtn.type = "button";
      origBtn.setAttribute("role", "menuitem");
      origBtn.setAttribute("aria-label", item.name + " 원본 PDF 다운로드");
      origBtn.addEventListener("click", async () => {
        more.removeAttribute("open");
        const res = await fetch("/api/document-conversions/items/" + item.id + "/original", { credentials: "include" });
        if (!res.ok) { uploadStatus.textContent = "원본 PDF 다운로드에 실패했습니다."; return; }
        const blob = await res.blob();
        downloadBlob(blob, (item.name.replace(/\.[^.]+$/, "") || "document") + ".pdf");
      });
      menu.appendChild(origBtn);

      const delBtn = el("button", "pdfmd-btn pdfmd-menu-item pdfmd-menu-danger", "지우기");
      delBtn.type = "button";
      delBtn.setAttribute("role", "menuitem");
      delBtn.setAttribute("aria-label", item.name + " 삭제");
      delBtn.addEventListener("click", async () => {
        more.removeAttribute("open");
        await deleteItem(item);
      });
      menu.appendChild(delBtn);

      more.appendChild(menu);
      return more;
    }

    function renderItems() {
      itemsWrap.replaceChildren();
      syncZipBar();
      if (!currentJobId) {
        itemsWrap.appendChild(emptyBlock("첫 PDF를 변환해 보세요.", null, [
          "PDF 또는 ZIP 파일을 고릅니다.",
          "올리면 바로 변환이 시작됩니다.",
          "원본과 Markdown을 비교하고 내려받습니다.",
        ]));
        return;
      }
      if (!currentItems.length) {
        itemsWrap.appendChild(emptyBlock("이 작업에는 아직 파일이 없습니다.", "위에서 PDF 또는 ZIP 파일을 고르세요.", null));
        return;
      }
      const list = el("div", "pdfmd-itemlist");
      currentItems.forEach((item) => {
        const card = el("div", "pdfmd-item");
        const head = el("div", "pdfmd-item-head");
        const title = el("span", "pdfmd-item-title", item.page_count ? item.name + " (" + item.page_count + "쪽)" : item.name);
        head.appendChild(title);
        head.appendChild(statusChip(item));
        card.appendChild(head);

        const meta = el("div", "pdfmd-item-meta");
        if (item.character_count) {
          meta.appendChild(el("span", "pdfmd-item-count", Number(item.character_count).toLocaleString("ko-KR") + "자"));
        }
        card.appendChild(meta);

        if (item.status === "failed") {
          /* 실패 카드(#7865): 이유 한 줄 + [지우기]만. 스캔본 같은 긴 안내도
             이유 줄에서 한 번만 보인다. */
          const reason = el("div", "pdfmd-warn", describeError({ code: item.error_code }, "변환에 실패했습니다."));
          card.appendChild(reason);
          const actions = el("div", "pdfmd-item-actions");
          actions.appendChild(deleteButton(item));
          card.appendChild(actions);
          list.appendChild(card);
          return;
        }

        const actions = el("div", "pdfmd-item-actions");
        if (item.has_markdown) {
          const mdBtn = el("button", "pdfmd-btn pdfmd-btn-primary", "Markdown 받기");
          mdBtn.type = "button";
          mdBtn.setAttribute("aria-label", item.name + " Markdown 받기");
          mdBtn.addEventListener("click", async () => {
            const res = await fetch("/api/document-conversions/items/" + item.id + "/markdown", { credentials: "include" });
            if (!res.ok) { uploadStatus.textContent = "Markdown 다운로드에 실패했습니다."; return; }
            const blob = await res.blob();
            downloadBlob(blob, (item.name.replace(/\.[^.]+$/, "") || "document") + ".md");
          });
          actions.appendChild(mdBtn);

          const previewBtn = el("button", "pdfmd-btn", "원본과 비교");
          previewBtn.type = "button";
          previewBtn.setAttribute("aria-label", item.name + " 원본과 변환본 비교");
          previewBtn.addEventListener("click", async () => {
            previewWrap.hidden = false;
            previewWrap.scrollIntoView({ block: "nearest" });
            mdView.replaceChildren(el("p", "pdfmd-preview-loading", "Markdown을 불러오는 중..."));
            previewItem = item;
            original.show(previewItem, 1);
            try {
              const res = await fetch("/api/document-conversions/items/" + item.id + "/markdown?display=inline", { credentials: "include" });
              if (!res.ok) throw new Error("http_" + res.status);
              renderMarkdownPreview(await res.text(), item);
            } catch (e) {
              mdView.replaceChildren(el("p", "pdfmd-preview-error", "미리보기를 불러오지 못했습니다. " + describeError(e)));
            }
          });
          actions.appendChild(previewBtn);

          actions.appendChild(moreMenu(item));
        } else if (item.status === "working" || item.status === "queued") {
          /* 바꾸는 중 카드: 단추 없음 — 업로드 때 변환이 시작되고 폴러가 갱신한다. */
          card.appendChild(el("div", "pdfmd-stage", "바꾸는 중 — 잠시 후 결과가 이 자리에 생깁니다."));
        }

        card.appendChild(actions);

        if (item.report && item.report.agreement && item.report.agreement.length) {
          let lowestCover = null;
          let lowestDigit = null;
          item.report.agreement.forEach((row) => {
            const c = Number(row && row.character_coverage);
            if (Number.isFinite(c) && (lowestCover === null || c < lowestCover)) lowestCover = c;
            const d = Number(row && row.digit_preservation);
            if (Number.isFinite(d) && (lowestDigit === null || d < lowestDigit)) lowestDigit = d;
          });
          const lowPages = item.report.agreement.filter((row) => Number(row && row.character_coverage) < 0.99).length;
          const info = el("div", "pdfmd-agreement", "일치도(전체 최저): " + (lowestCover !== null ? (lowestCover * 100).toFixed(1) + "%" : "—") + (lowestDigit !== null ? " / 숫자 보존(최저): " + (lowestDigit * 100).toFixed(1) + "%" : "") + " · 확인 필요 " + lowPages + "쪽");
          card.appendChild(info);
        } else if (item.report && item.report.agreement_summary) {
          const s = item.report.agreement_summary;
          const info = el("div", "pdfmd-agreement", "일치도(전체 최저): " + (s.min_character_coverage !== null && s.min_character_coverage !== undefined ? (s.min_character_coverage * 100).toFixed(1) + "%" : "—") + (s.min_digit_preservation !== null && s.min_digit_preservation !== undefined ? " / 숫자 보존(최저): " + (s.min_digit_preservation * 100).toFixed(1) + "%" : "") + " · 확인 필요 " + (s.review_page_count || 0) + "쪽");
          card.appendChild(info);
        }
        if (item.status !== "failed" && describeWarnings(item.report)) card.appendChild(el("div", "pdfmd-warn", describeWarnings(item.report)));
        list.appendChild(card);
      });
      itemsWrap.appendChild(list);
    }

    async function downloadAllZip(button) {
      if (!currentJobId) return;
      button.disabled = true;
      try {
        const res = await fetch("/api/document-conversions/" + currentJobId + "/archive", { credentials: "include" });
        if (!res.ok) {
          uploadStatus.textContent = "ZIP 다운로드에 실패했습니다.";
          return;
        }
        const blob = await res.blob();
        downloadBlob(blob, "pdf-to-markdown-" + currentJobId + ".zip");
      } catch (e) {
        uploadStatus.textContent = "ZIP 다운로드에 실패했습니다. " + describeError(e);
      } finally {
        button.disabled = false;
      }
    }

    allZipBtn.addEventListener("click", () => downloadAllZip(allZipBtn));

    function historyGroup(value) {
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return "earlier";
      const now = new Date();
      const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      const day = new Date(date.getFullYear(), date.getMonth(), date.getDate());
      const age = Math.round((today - day) / 86400000);
      if (age <= 0) return "today";
      if (age === 1) return "yesterday";
      const monday = new Date(today);
      monday.setDate(today.getDate() - ((today.getDay() + 6) % 7));
      return day >= monday ? "this-week" : "earlier";
    }

    function jobText(job) {
      return [
        formatWhen(job.created_at),
        job.created_at || "",
        job.id || "",
        job.id ? job.id.slice(-8) : "",
        modeLabel(job.mode),
        badgeText(job),
        countLabel(job.item_count),
      ].concat(itemNames.get(job.id) || []).join(" ").toLowerCase();
    }

    function matchesQuery(job, query) {
      if (!query) return true;
      const haystack = jobText(job);
      return query.split(/\s+/).every((token) => haystack.indexOf(token) !== -1);
    }

    function historyRow(job) {
      const li = document.createElement("li");
      const btn = el("button", "pdfmd-history-item");
      btn.type = "button";
      btn.dataset.jobId = job.id;
      const main = el("span", "pdfmd-history-main");
      const when = formatWhen(job.created_at);
      main.appendChild(el("span", "pdfmd-history-when", when));
      const names = itemNames.get(job.id);
      if (names && names.length) main.appendChild(el("span", "pdfmd-history-name", names.join(", ")));
      main.appendChild(el("span", "pdfmd-history-meta", countLabel(job.item_count) + " · " + modeLabel(job.mode)));
      btn.appendChild(main);
      const chip = statusChip(job);
      btn.appendChild(chip);
      btn.setAttribute("aria-label", when + ", " + countLabel(job.item_count) + ", " + modeLabel(job.mode) + ", 상태 " + chip.textContent);
      btn.addEventListener("click", async () => {
        setJobId(job.id);
        await loadJob();
        histFold.removeAttribute("open");
        if (typeof histFold.scrollIntoView === "function") {
          try { itemsWrap.scrollIntoView({ block: "nearest" }); } catch (_) {}
        }
      });
      li.appendChild(btn);
      return li;
    }

    function renderHistory() {
      histList.replaceChildren();
      if (!historyJobs.length) {
        histList.appendChild(emptyBlock("아직 작업 이력이 없습니다.", "첫 파일을 변환하면 여기에 기록됩니다.", null));
        return;
      }
      const query = historyQuery.trim().toLowerCase();
      const groups = { today: [], yesterday: [], "this-week": [], earlier: [] };
      let matched = 0;
      historyJobs.forEach((job) => {
        if (!matchesQuery(job, query)) return;
        groups[historyGroup(job.created_at)].push(job);
        matched += 1;
      });
      if (!matched) {
        histList.appendChild(emptyBlock(
          copy("pdfmd-history-no-match", "검색 결과가 없습니다."),
          copy("pdfmd-history-no-match-detail", "다른 날짜나 파일명으로 검색해 보세요."),
          null,
          "pdfmd-history-no-match",
          "pdfmd-history-no-match-detail",
        ));
        return;
      }
      HISTORY_GROUPS.forEach(([key, localeKey, fallback]) => {
        if (!groups[key].length) return;
        const head = el("h5", "pdfmd-history-group", copy(localeKey, fallback));
        head.dataset.localeKey = localeKey;
        histList.appendChild(head);
        const ul = document.createElement("ul");
        ul.className = "pdfmd-history-list";
        groups[key].forEach((job) => ul.appendChild(historyRow(job)));
        histList.appendChild(ul);
      });
      markActiveHistory();
    }

    function syncHistoryFold() {
      histSummary.textContent = "지난 변환 " + historyJobs.length + "건";
      histTools.hidden = !historyJobs.length;
    }

    histSearch.addEventListener("input", () => {
      historyQuery = histSearch.value;
      renderHistory();
    });
    histFold.addEventListener("toggle", () => {
      if (histFold.open) markActiveHistory();
    });

    async function loadHistory() {
      histList.replaceChildren(el("p", "pdfmd-empty", "작업 이력을 불러오는 중..."));
      try {
        const data = await api("/api/document-conversions?limit=50");
        const answer = data.new_work_enabled === true ? "open" : "paused";
        if (answer !== workState) {
          // One repaint, from the answer. The first paint never claims a pause.
          window.initPdfMdUtility(panel, answer);
          return;
        }
        historyJobs = data.jobs || [];
        syncHistoryFold();
        renderHistory();
        historyJobs.forEach((job) => {
          if (job.status === "working") pollWorkingItemsOfJob(job.id);
        });
      } catch (e) {
        if (e.status === 401) {
          // A guest is not a pause: the work itself is open, this session is
          // not. Repaint once as login_required; the repaint's own history read
          // lands on the login explanation below.
          if (workState !== "login_required") {
            window.initPdfMdUtility(panel, "login_required");
            return;
          }
          historyJobs = [];
          syncHistoryFold();
          histList.replaceChildren();
          histList.appendChild(emptyBlock("로그인하면 작업 이력을 볼 수 있습니다.", null, null));
          return;
        }
        if (PDFMD_CHECKING) {
          // No answer is an answer of its own: the work cannot start without
          // it, so the pause sentence is the truthful one. The history area
          // still states the reason it could not be read.
          window.initPdfMdUtility(panel, "paused");
          return;
        }
        historyJobs = [];
        syncHistoryFold();
        histList.replaceChildren();
        histList.appendChild(emptyBlock("작업 이력을 불러오지 못했습니다.", describeError(e), null));
      }
    }

    if (window.PadiemUtilChatMode && typeof window.PadiemUtilChatMode.bindPdfmd === "function") {
      chatBridge = window.PadiemUtilChatMode.bindPdfmd({
        panel, inputCol, formWrap, uploadStatus, modeSel, dropTitle,
        workBlocked, loginRequired: PDFMD_LOGIN_REQUIRED, copy, startNewJob, uploadFiles,
        modeSwitchHost,
        getState: () => ({ currentJobId, currentItems, lastUploadError }),
      });
    }

    renderItems();
    loadHistory();
  };
})();
