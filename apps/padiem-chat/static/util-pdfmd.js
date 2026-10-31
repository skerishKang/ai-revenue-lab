(() => {
  "use strict";

  const STATUS_LABELS = {
    queued: "준비중",
    working: "변환중",
    reviewed: "검토중",
    done: "완료",
    failed: "실패",
  };

  const ERROR_MESSAGES = {
    unauthorized: "로그인이 필요합니다.",
    document_convert_unavailable: "지금은 변환을 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.",
    document_convert_not_found: "작업을 찾을 수 없습니다. 새 작업을 시작해 주세요.",
    convert_store_unavailable: "작업 기록을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    convert_failed: "변환에 실패했습니다. 다시 시도해 주세요.",
    invalid_archive: "ZIP 파일을 열 수 없습니다.",
    empty_archive: "ZIP 파일 안에 변환할 PDF가 없습니다.",
    invalid_document: "PDF 또는 ZIP 파일만 올릴 수 있습니다.",
    document_too_large: "파일이 너무 큽니다.",
    pdf_magic_mismatch: "PDF 형식이 아니거나 손상된 파일입니다.",
  };

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function statusChip(status) {
    const known = Object.prototype.hasOwnProperty.call(STATUS_LABELS, status);
    const chip = el("span", "pdfmd-status-chip", known ? STATUS_LABELS[status] : "확인 필요");
    chip.dataset.status = known ? status : "unknown";
    return chip;
  }

  function modeLabel(mode) {
    return mode === "verify" ? "검증 변환" : "빠른 변환";
  }

  const MODE_HELP = {
    fast: ["pdfmd-mode-help-fast", "빠른 변환: PDF의 텍스트만 곧바로 Markdown으로 옮깁니다. 디지털 PDF를 빠르게 확인할 때 적합합니다."],
    verify: ["pdfmd-mode-help-verify", "검증 변환: 같은 변환에 페이지별 문자 일치도·숫자 보존·읽기 순서 검토를 더합니다. 숫자·조항 대조가 중요할 때 적합합니다."],
  };

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

  function describeError(err, fallback) {
    if (err && err.code && ERROR_MESSAGES[err.code]) return ERROR_MESSAGES[err.code];
    if (err && err.status === 401) return ERROR_MESSAGES.unauthorized;
    return fallback || "잠시 후 다시 시도해 주세요.";
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
    if (!res.ok) {
      let code = "http_" + res.status;
      try { const j = await res.json(); if (j && j.error && j.error.code) code = j.error.code; } catch (_) {}
      const err = new Error(code);
      err.status = res.status;
      err.code = code;
      throw err;
    }
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) return res.json();
    return res;
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  const PDFMD_NEW_WORK_DISABLED = true; // #5710 COM2 migration, existing downloads remain.

  // #6012: the shared "내 PC에서 가져오기·저장하기" part. It is loaded the first
  // time this menu uses it, so a page that never opens the menu touches no
  // script and no PC endpoint (#6034).
  const PC_COPY = {
    pick: "내 PC에서 가져오기",
    ready: "준비 중",
    noPc: "PC를 연결하면 내 PC 문서를 바로 변환할 수 있습니다.",
    connect: "이 PC 연결",
    save: "내 PC에 저장",
    saving: "내 PC에 저장하는 중...",
    saved: "내 PC에 저장했습니다.",
    noSave: "PC에 저장할 창을 열지 못했습니다. 잠시 후 다시 시도해 주세요.",
    saveFailed: "저장할 결과를 불러오지 못했습니다.",
    noFile: "PC에서 가져온 파일을 읽지 못했습니다.",
  };

  // Where each original came from on the PC, so its result can be offered back
  // into the same folder. A file uploaded from the browser has no PC folder.
  const pcOrigin = new Map();

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

  window.initPdfMdUtility = function (panel) {
    panel.replaceChildren();
    panel.classList.add("pdfmd-shell");

    const header = el("div", "pdfmd-header");
    header.appendChild(el("h3", null, "PDF → Markdown 변환"));
    header.appendChild(el("p", "pdfmd-desc", "PDF나 ZIP을 올려 변환하면 원본과 Markdown을 나란히 비교하고 내려받을 수 있습니다. OCR(정밀 변환)은 지원하지 않습니다."));
    panel.appendChild(header);
    if (PDFMD_NEW_WORK_DISABLED) {
      header.querySelector(".pdfmd-desc").textContent = "문서 처리 서버를 COM2로 이전 중입니다. 신규 PDF·ZIP 업로드 및 변환은 일시 중단하며, 기존 작업 이력과 결과 다운로드는 이용할 수 있습니다.";
      const notice = el("p", "pdfmd-status", "서비스 준비 중 · 신규 업로드 및 변환 일시 중단");
      notice.setAttribute("role", "status");
      panel.appendChild(notice);
    }

    // Mode + job controls
    const controls = el("div", "pdfmd-controls");
    const modeField = el("label", null, "변환 방식 ");
    const modeSel = document.createElement("select");
    modeSel.id = "pdfmdMode";
    [["fast", "빠른 변환"], ["verify", "검증 변환"]].forEach(([v, t]) => {
      const o = document.createElement("option");
      o.value = v; o.textContent = t;
      if (v === "fast") o.selected = true;
      modeSel.appendChild(o);
    });
    modeField.appendChild(modeSel);
    modeSel.disabled = PDFMD_NEW_WORK_DISABLED;
    modeSel.setAttribute("aria-describedby", "pdfmdModeHelp");
    controls.appendChild(modeField);

    const newJobBtn = el("button", "pdfmd-btn", "새 작업");
    newJobBtn.type = "button";
    newJobBtn.hidden = true;
    controls.appendChild(newJobBtn);

    const jobIdSpan = el("span", "pdfmd-jobid", "");
    jobIdSpan.hidden = true;
    controls.appendChild(jobIdSpan);
    panel.appendChild(controls);

    const modeHelp = el("p", "pdfmd-mode-help");
    modeHelp.id = "pdfmdModeHelp";
    panel.appendChild(modeHelp);
    function updateModeHelp() {
      const [key, fallback] = MODE_HELP[modeSel.value] || MODE_HELP.fast;
      modeHelp.dataset.localeKey = key;
      modeHelp.textContent = copy(key, fallback);
    }
    updateModeHelp();

    // Upload area: one large, keyboard-operable target. The picker is the
    // primary action on mobile, where drag-and-drop copy alone is no help.
    const drop = el("div", "pdfmd-drop");
    drop.setAttribute("role", "button");
    drop.tabIndex = 0;
    drop.setAttribute("aria-label", "PDF 또는 ZIP 파일 선택");
    const dropTitle = el("span", "pdfmd-drop-title", "PDF 파일을 선택하세요");
    const dropSub = el("span", "pdfmd-drop-sub", "끌어다 놓거나 눌러서 선택 · ZIP과 여러 파일도 가능");
    dropSub.id = "pdfmdDropHint";
    const dropCta = el("span", "pdfmd-drop-cta", "파일 선택");
    drop.appendChild(dropTitle);
    drop.appendChild(dropSub);
    drop.appendChild(dropCta);
    drop.setAttribute("aria-describedby", "pdfmdDropHint");
    panel.appendChild(drop);
    if (PDFMD_NEW_WORK_DISABLED) {
      drop.removeAttribute("role");
      drop.removeAttribute("tabindex");
      drop.removeAttribute("aria-label");
      drop.classList.add("pdfmd-paused");
      drop.style.cursor = "not-allowed";
      drop.style.opacity = "0.65";
      dropTitle.textContent = "PDF 업로드 준비 중";
      dropSub.textContent = "COM2 이전 완료 후 이용할 수 있습니다.";
      dropCta.textContent = "업로드 일시 중단";
    }

    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.multiple = true;
    fileInput.accept = ".pdf,.zip,application/pdf,application/zip";
    fileInput.hidden = true;
    fileInput.disabled = PDFMD_NEW_WORK_DISABLED;
    panel.appendChild(fileInput);

    // #6012: the same documents, taken straight from the owner's own PC.
    const pcPick = el("button", "pdfmd-btn pdfmd-pc-pick", PC_COPY.pick);
    pcPick.type = "button";
    pcPick.id = "pdfmdPcPick";
    panel.appendChild(pcPick);

    const pcNote = el("p", "pdfmd-status pdfmd-pc-note", "");
    pcNote.id = "pdfmdPcNote";
    pcNote.hidden = true;
    const pcConnect = el("button", "pdfmd-link", PC_COPY.connect);
    pcConnect.type = "button";
    pcConnect.addEventListener("click", openPcConnect);
    pcNote.appendChild(el("span", null, PC_COPY.noPc + " "));
    pcNote.appendChild(pcConnect);
    panel.appendChild(pcNote);

    const uploadStatus = el("div", "pdfmd-status", "");
    uploadStatus.id = "pdfmdStatus";
    uploadStatus.setAttribute("role", "status");
    uploadStatus.setAttribute("aria-live", "polite");
    panel.appendChild(uploadStatus);

    // Items
    const itemsWrap = el("div", "pdfmd-items");
    panel.appendChild(itemsWrap);

    // Preview
    const previewWrap = el("div", "pdfmd-preview");
    previewWrap.hidden = true;
    const previewTitle = el("h4", null, "원본과 변환본 비교");
    previewWrap.appendChild(previewTitle);
    const previewGrid = el("div", "pdfmd-preview-grid");

    const origPane = el("div", "pdfmd-pane");
    origPane.appendChild(el("span", "pdfmd-pane-label", "원본 PDF"));
    const origFrame = document.createElement("iframe");
    origFrame.className = "pdfmd-iframe";
    origFrame.title = "원본 PDF";
    origPane.appendChild(origFrame);

    const mdPane = el("div", "pdfmd-pane");
    mdPane.appendChild(el("span", "pdfmd-pane-label", "Markdown 변환본"));
    const mdView = document.createElement("pre");
    mdView.className = "pdfmd-md";
    mdView.tabIndex = 0;
    mdView.setAttribute("aria-label", "Markdown 변환본");
    mdPane.appendChild(mdView);

    previewGrid.appendChild(origPane);
    previewGrid.appendChild(mdPane);
    previewWrap.appendChild(previewGrid);
    panel.appendChild(previewWrap);

    // Archive
    const archiveBtn = el("button", "pdfmd-btn", "전체 ZIP 다운로드");
    archiveBtn.type = "button";
    archiveBtn.hidden = true;
    panel.appendChild(archiveBtn);

    // History: client-side date grouping and filtering. The list API carries
    // no filenames, so names join the search index as jobs are opened.
    const histHeader = el("h4", "pdfmd-history-head", "작업 이력");
    panel.appendChild(histHeader);
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
    panel.appendChild(histTools);
    const histList = el("div", "pdfmd-history");
    panel.appendChild(histList);

    let currentJobId = null;
    let currentItems = [];
    let lastUploadError = "";
    let historyJobs = [];
    let historyQuery = "";
    const itemNames = new Map();

    function markActiveHistory() {
      histList.querySelectorAll(".pdfmd-history-item").forEach((btn) => {
        if (btn.dataset.jobId === currentJobId) btn.setAttribute("aria-current", "true");
        else btn.removeAttribute("aria-current");
      });
    }

    function setJobId(id) {
      if (id !== currentJobId) {
        previewWrap.hidden = true;
        mdView.textContent = "";
        origFrame.removeAttribute("src");
      }
      currentJobId = id;
      jobIdSpan.textContent = id ? "작업 " + id.slice(-8) : "";
      jobIdSpan.title = id || "";
      jobIdSpan.hidden = !id;
      newJobBtn.hidden = PDFMD_NEW_WORK_DISABLED || !id;
      archiveBtn.hidden = !id;
      markActiveHistory();
    }

    function startNewJob() {
      if (PDFMD_NEW_WORK_DISABLED) return;
      currentItems = [];
      setJobId(null);
      uploadStatus.textContent = "새 작업을 시작합니다. 파일을 선택하세요.";
      renderItems();
      drop.focus();
    }

    async function createJob() {
      if (PDFMD_NEW_WORK_DISABLED) return;
      const mode = modeSel.value;
      uploadStatus.textContent = "작업을 준비하는 중...";
      try {
        const data = await api("/api/document-conversions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mode: mode }),
        });
        setJobId(data.job.id);
        uploadStatus.textContent = "작업이 준비되었습니다. 파일을 올려 주세요.";
        await loadJob();
        await loadHistory();
      } catch (e) {
        uploadStatus.textContent = "작업을 만들지 못했습니다. " + describeError(e);
      }
    }

    newJobBtn.addEventListener("click", startNewJob);
    modeSel.addEventListener("change", () => {
      updateModeHelp();
      if (currentJobId) uploadStatus.textContent = "변환 방식은 새 작업부터 적용됩니다.";
    });

    // #6012: a file chosen in the shared dialog comes back as the file lane's
    // id; its bytes are read once and handed to the SAME upload the browser
    // path uses, so there is one conversion and one ledger.
    async function importFromPc(picked) {
      if (!picked || !picked.fileId || PDFMD_NEW_WORK_DISABLED) return;
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

    if (PDFMD_NEW_WORK_DISABLED) {
      pcPick.disabled = true;
      pcPick.textContent = PC_COPY.pick + " · " + PC_COPY.ready;
    } else {
      pcPick.addEventListener("click", async () => {
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
    }
    // Only an answer that there is no PC shows the notice; a failed check stays quiet.
    void pcLinked().then((linked) => {
      if (linked === false) pcNote.hidden = false;
    });

    async function uploadFile(file) {
      if (PDFMD_NEW_WORK_DISABLED) return false;
      lastUploadError = "";
      if (!currentJobId) await createJob();
      if (!currentJobId) return false;
      const isZip = file.name.toLowerCase().endsWith(".zip") || file.type === "application/zip";
      const mediaType = isZip ? "application/zip" : "application/pdf";
      const buf = await file.arrayBuffer();
      uploadStatus.textContent = file.name + " 업로드 중...";
      try {
        const data = await api("/api/document-conversions/" + currentJobId + "/files", {
          method: "POST",
          headers: {
            "Content-Type": "application/octet-stream",
            "X-Padiem-Filename": encodeURIComponent(file.name),
            "X-Padiem-Media-Type": mediaType,
          },
          body: buf,
        });
        if (data.rejected && data.rejected.length) {
          const rejected = data.rejected.map((r) => r.name + ": " + describeError({ code: r.code }, "지원하지 않는 파일입니다.")).join(" / ");
          lastUploadError = rejected;
          uploadStatus.textContent = "일부 파일을 올리지 못했습니다. " + rejected;
          await loadJob();
          return false;
        }
        uploadStatus.textContent = file.name + " 업로드 완료";
        await loadJob();
        return true;
      } catch (e) {
        lastUploadError = describeError(e);
        uploadStatus.textContent = file.name + " 업로드 실패. " + lastUploadError;
        return false;
      }
    }

    async function uploadFiles(files) {
      if (PDFMD_NEW_WORK_DISABLED) return;
      if (!files.length) return;
      let uploaded = 0;
      let failed = 0;
      for (const f of files) {
        if (await uploadFile(f)) uploaded += 1;
        else failed += 1;
      }
      if (uploaded && !failed) {
        uploadStatus.textContent = uploaded + "개 파일 업로드 완료. 목록에서 '변환 실행'을 눌러 주세요.";
      } else if (uploaded && failed) {
        uploadStatus.textContent = uploaded + "개 업로드 완료, " + failed + "개 파일을 올리지 못했습니다. " + (lastUploadError || "파일 형식을 확인해 주세요.");
      }
      if (uploaded) await loadHistory();
    }

    function openPicker() {
      if (PDFMD_NEW_WORK_DISABLED) return;
      fileInput.click();
    }
    drop.addEventListener("click", openPicker);
    drop.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openPicker();
      }
    });
    drop.addEventListener("dragover", (e) => { e.preventDefault(); if (!PDFMD_NEW_WORK_DISABLED) drop.classList.add("dragover"); });
    drop.addEventListener("dragleave", () => drop.classList.remove("dragover"));
    drop.addEventListener("drop", (e) => {
      e.preventDefault();
      if (PDFMD_NEW_WORK_DISABLED) return;
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
      } catch (e) {
        uploadStatus.textContent = "작업을 불러오지 못했습니다. " + describeError(e);
      }
    }

    function renderItems() {
      itemsWrap.replaceChildren();
      if (!currentJobId) {
        itemsWrap.appendChild(emptyBlock("첫 PDF를 변환해 보세요.", null, [
          "PDF 또는 ZIP 파일을 선택합니다.",
          "목록에서 '변환 실행'을 누릅니다.",
          "원본과 Markdown을 비교하고 내려받습니다.",
        ]));
        return;
      }
      if (!currentItems.length) {
        itemsWrap.appendChild(emptyBlock("이 작업에는 아직 파일이 없습니다.", "위에서 PDF 또는 ZIP 파일을 선택하세요.", null));
        return;
      }
      const list = el("div", "pdfmd-itemlist");
      currentItems.forEach((item) => {
        const card = el("div", "pdfmd-item");
        const title = el("div", "pdfmd-item-title", item.page_count ? item.name + " (" + item.page_count + "쪽)" : item.name);
        card.appendChild(title);

        const meta = el("div", "pdfmd-item-meta");
        meta.appendChild(statusChip(item.status));
        if (item.character_count) {
          meta.appendChild(el("span", "pdfmd-item-count", Number(item.character_count).toLocaleString("ko-KR") + "자"));
        }
        card.appendChild(meta);

        if (item.error_code) {
          const err = el("div", "pdfmd-warn", describeError({ code: item.error_code }, "변환에 실패했습니다."));
          err.title = item.error_code;
          card.appendChild(err);
        }

        const actions = el("div", "pdfmd-item-actions");

        if (!item.has_markdown && !PDFMD_NEW_WORK_DISABLED) {
          const runBtn = el("button", "pdfmd-btn pdfmd-btn-primary", item.status === "failed" ? "다시 변환" : "변환 실행");
          runBtn.type = "button";
          runBtn.setAttribute("aria-label", item.name + " " + runBtn.textContent);
          runBtn.addEventListener("click", async () => {
            runBtn.disabled = true;
            uploadStatus.textContent = item.name + " 변환 중...";
            try {
              await api("/api/document-conversions/items/" + item.id + "/run", { method: "POST" });
              uploadStatus.textContent = item.name + " 변환 완료. 원본과 결과를 비교해 보세요.";
              await loadJob();
              await loadHistory();
            } catch (e) {
              uploadStatus.textContent = item.name + " 변환 실패. " + describeError(e);
              await loadJob();
              await loadHistory();
            }
          });
          actions.appendChild(runBtn);
        } else if (item.has_markdown) {
          const previewBtn = el("button", "pdfmd-btn pdfmd-btn-primary", "비교 보기");
          previewBtn.type = "button";
          previewBtn.setAttribute("aria-label", item.name + " 원본과 변환본 비교");
          previewBtn.addEventListener("click", async () => {
            previewWrap.hidden = false;
            mdView.textContent = "Markdown을 불러오는 중...";
            origFrame.src = "/api/document-conversions/items/" + item.id + "/original?display=inline";
            try {
              const res = await fetch("/api/document-conversions/items/" + item.id + "/markdown?display=inline", { credentials: "include" });
              if (!res.ok) throw new Error("http_" + res.status);
              mdView.textContent = await res.text();
            } catch (e) {
              mdView.textContent = "미리보기를 불러오지 못했습니다. " + describeError(e);
            }
          });
          actions.appendChild(previewBtn);

          const mdBtn = el("button", "pdfmd-btn", "MD 다운로드");
          mdBtn.type = "button";
          mdBtn.setAttribute("aria-label", item.name + " Markdown 다운로드");
          mdBtn.addEventListener("click", async () => {
            const res = await fetch("/api/document-conversions/items/" + item.id + "/markdown", { credentials: "include" });
            if (!res.ok) { uploadStatus.textContent = "Markdown 다운로드에 실패했습니다."; return; }
            const blob = await res.blob();
            downloadBlob(blob, (item.name.replace(/\.[^.]+$/, "") || "document") + ".md");
          });
          actions.appendChild(mdBtn);

          // #6012: the same result, put back on the owner's PC beside the file it
          // came from. The shared part keeps the previous contents as a backup.
          const pcSaveBtn = el("button", "pdfmd-btn", PC_COPY.save);
          pcSaveBtn.type = "button";
          pcSaveBtn.setAttribute("aria-label", item.name + " " + PC_COPY.save);
          pcSaveBtn.addEventListener("click", async () => {
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
          actions.appendChild(pcSaveBtn);

          const origBtn = el("button", "pdfmd-btn", "원본 PDF");
          origBtn.type = "button";
          origBtn.setAttribute("aria-label", item.name + " 원본 PDF 다운로드");
          origBtn.addEventListener("click", async () => {
            const res = await fetch("/api/document-conversions/items/" + item.id + "/original", { credentials: "include" });
            if (!res.ok) { uploadStatus.textContent = "원본 PDF 다운로드에 실패했습니다."; return; }
            const blob = await res.blob();
            downloadBlob(blob, (item.name.replace(/\.[^.]+$/, "") || "document") + ".pdf");
          });
          actions.appendChild(origBtn);

          if (item.status !== "done") {
            const reviewBtn = el("button", "pdfmd-btn", "검토 완료");
            reviewBtn.type = "button";
            reviewBtn.setAttribute("aria-label", item.name + " 검토 완료");
            reviewBtn.addEventListener("click", async () => {
              try {
                await api("/api/document-conversions/items/" + item.id + "/review", { method: "POST" });
                await loadJob();
                await loadHistory();
              } catch (e) {
                uploadStatus.textContent = "검토 상태를 저장하지 못했습니다. " + describeError(e);
              }
            });
            actions.appendChild(reviewBtn);
          }
        }

        const delBtn = el("button", "pdfmd-btn", "삭제");
        delBtn.type = "button";
        delBtn.setAttribute("aria-label", item.name + " 삭제");
        delBtn.addEventListener("click", async () => {
          try {
            await api("/api/document-conversions/items/" + item.id, { method: "DELETE" });
            await loadJob();
            await loadHistory();
          } catch (e) {
            uploadStatus.textContent = "파일을 삭제하지 못했습니다. " + describeError(e);
          }
        });
        actions.appendChild(delBtn);

        card.appendChild(actions);

        if (item.report && item.report.agreement && item.report.agreement.length) {
          const agr = item.report.agreement[0];
          const info = el("div", "pdfmd-agreement", "일치도(문자): " + (agr.character_coverage * 100).toFixed(1) + "%" + (agr.digit_preservation != null ? " / 숫자 보존: " + (agr.digit_preservation * 100).toFixed(1) + "%" : ""));
          card.appendChild(info);
        }
        if (item.report && item.report.warnings && item.report.warnings.length) {
          const w = el("div", "pdfmd-warn", "경고: " + item.report.warnings.join(", "));
          card.appendChild(w);
        }
        list.appendChild(card);
      });
      itemsWrap.appendChild(list);
    }

    archiveBtn.addEventListener("click", async () => {
      if (!currentJobId) return;
      archiveBtn.disabled = true;
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
        archiveBtn.disabled = false;
      }
    });

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
        STATUS_LABELS[job.status] || "",
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
      main.appendChild(el("span", "pdfmd-history-meta", countLabel(job.item_count) + " · " + modeLabel(job.mode)));
      btn.appendChild(main);
      const chip = statusChip(job.status);
      btn.appendChild(chip);
      btn.setAttribute("aria-label", when + ", " + countLabel(job.item_count) + ", " + modeLabel(job.mode) + ", 상태 " + chip.textContent);
      btn.addEventListener("click", async () => {
        setJobId(job.id);
        await loadJob();
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

    histSearch.addEventListener("input", () => {
      historyQuery = histSearch.value;
      renderHistory();
    });

    async function loadHistory() {
      histTools.hidden = true;
      histList.replaceChildren(el("p", "pdfmd-empty", "작업 이력을 불러오는 중..."));
      try {
        const data = await api("/api/document-conversions?limit=50");
        historyJobs = data.jobs || [];
        histTools.hidden = !historyJobs.length;
        renderHistory();
      } catch (e) {
        historyJobs = [];
        histTools.hidden = true;
        histList.replaceChildren();
        if (e.status === 401) {
          histList.appendChild(emptyBlock("로그인하면 작업 이력을 볼 수 있습니다.", null, null));
        } else {
          histList.appendChild(emptyBlock("작업 이력을 불러오지 못했습니다.", describeError(e), null));
        }
      }
    }

    renderItems();
    loadHistory();
  };
})();
