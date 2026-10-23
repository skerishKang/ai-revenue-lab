(() => {
  "use strict";

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function authHeaders(extra) {
    return Object.assign({ "Content-Type": "application/octet-stream" }, extra || {});
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

  window.initPdfMdUtility = function (panel) {
    panel.replaceChildren();

    const header = el("div", "pdfmd-header");
    header.appendChild(el("h3", null, "PDF → Markdown 변환"));
    const desc = el("p", "pdfmd-desc", "PDF 파일을 Markdown으로 변환합니다. 빠른 변환은 텍스트 레이어를 그대로 옮기고, 검증 변환은 원본과 결과의 일치도를 함께 보여줍니다. OCR(정밀 변환)은 현재 지원되지 않습니다.");
    header.appendChild(desc);
    panel.appendChild(header);

    // Mode + job controls
    const controls = el("div", "pdfmd-controls");
    const modeLabel = el("label", null, "변환 모드 ");
    const modeSel = document.createElement("select");
    modeSel.id = "pdfmdMode";
    [["fast", "빠른 변환"], ["verify", "검증 변환"]].forEach(([v, t]) => {
      const o = document.createElement("option");
      o.value = v; o.textContent = t;
      if (v === "fast") o.selected = true;
      modeSel.appendChild(o);
    });
    modeLabel.appendChild(modeSel);
    controls.appendChild(modeLabel);

    const newJobBtn = el("button", "pdfmd-btn", "새 작업 만들기");
    newJobBtn.type = "button";
    controls.appendChild(newJobBtn);

    const jobIdSpan = el("span", "pdfmd-jobid", "");
    controls.appendChild(jobIdSpan);
    panel.appendChild(controls);

    // Upload area
    const drop = el("div", "pdfmd-drop");
    drop.textContent = "PDF 또는 ZIP 파일을 여기에 끌어다 놓거나 클릭하여 선택하세요 (다중 선택 가능)";
    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.multiple = true;
    fileInput.accept = ".pdf,.zip,application/pdf,application/zip";
    fileInput.hidden = true;
    drop.appendChild(fileInput);
    panel.appendChild(drop);

    const uploadStatus = el("div", "pdfmd-status", "");
    panel.appendChild(uploadStatus);

    // Items
    const itemsWrap = el("div", "pdfmd-items");
    panel.appendChild(itemsWrap);

    // Preview
    const previewWrap = el("div", "pdfmd-preview");
    previewWrap.hidden = true;
    const previewTitle = el("h4", null, "원본 / 변환본 비교");
    previewWrap.appendChild(previewTitle);
    const previewGrid = el("div", "pdfmd-preview-grid");
    const origFrame = document.createElement("iframe");
    origFrame.className = "pdfmd-iframe";
    origFrame.title = "원본 PDF";
    const mdView = document.createElement("pre");
    mdView.className = "pdfmd-md";
    previewGrid.appendChild(origFrame);
    previewGrid.appendChild(mdView);
    previewWrap.appendChild(previewGrid);
    panel.appendChild(previewWrap);

    // Archive
    const archiveBtn = el("button", "pdfmd-btn", "전체 ZIP 다운로드");
    archiveBtn.type = "button";
    archiveBtn.hidden = true;
    panel.appendChild(archiveBtn);

    // History
    const histHeader = el("h4", null, "작업 이력");
    panel.appendChild(histHeader);
    const histList = el("div", "pdfmd-history");
    panel.appendChild(histList);

    let currentJobId = null;
    let currentItems = [];

    function setJobId(id) {
      currentJobId = id;
      jobIdSpan.textContent = id ? "작업: " + id : "";
      archiveBtn.hidden = !id;
    }

    async function createJob() {
      const mode = modeSel.value;
      uploadStatus.textContent = "작업 생성 중...";
      try {
        const data = await api("/api/document-conversions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mode: mode }),
        });
        setJobId(data.job.id);
        uploadStatus.textContent = "작업이 생성되었습니다.";
        await loadJob();
      } catch (e) {
        uploadStatus.textContent = "작업 생성 실패: " + e.message;
      }
    }

    newJobBtn.addEventListener("click", createJob);

    async function uploadFile(file) {
      if (!currentJobId) await createJob();
      if (!currentJobId) return;
      const isZip = file.name.toLowerCase().endsWith(".zip") || file.type === "application/zip";
      const mediaType = isZip ? "application/zip" : "application/pdf";
      const buf = await file.arrayBuffer();
      uploadStatus.textContent = file.name + " 업로드 중...";
      try {
        const res = await fetch("/api/document-conversions/" + currentJobId + "/files", {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/octet-stream",
            "X-Padiem-Filename": encodeURIComponent(file.name),
            "X-Padiem-Media-Type": mediaType,
          },
          body: buf,
        });
        if (!res.ok) {
          let code = "http_" + res.status;
          try { const j = await res.json(); if (j && j.error && j.error.code) code = j.error.code; } catch (_) {}
          throw new Error(code);
        }
        const data = await res.json();
        if (data.rejected && data.rejected.length) {
          uploadStatus.textContent = file.name + " 일부 거부: " + data.rejected.map(r => r.name + "(" + r.code + ")").join(", ");
        } else {
          uploadStatus.textContent = file.name + " 업로드 완료";
        }
        await loadJob();
      } catch (e) {
        uploadStatus.textContent = file.name + " 업로드 실패: " + e.message;
      }
    }

    async function uploadFiles(files) {
      for (const f of files) await uploadFile(f);
    }

    drop.addEventListener("click", () => fileInput.click());
    drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("dragover"); });
    drop.addEventListener("dragleave", () => drop.classList.remove("dragover"));
    drop.addEventListener("drop", (e) => {
      e.preventDefault();
      drop.classList.remove("dragover");
      if (e.dataTransfer && e.dataTransfer.files) uploadFiles(Array.from(e.dataTransfer.files));
    });
    fileInput.addEventListener("change", () => {
      if (fileInput.files) uploadFiles(Array.from(fileInput.files));
      fileInput.value = "";
    });

    async function loadJob() {
      if (!currentJobId) return;
      try {
        const data = await api("/api/document-conversions/" + currentJobId);
        currentItems = data.items || [];
        renderItems();
      } catch (e) {
        uploadStatus.textContent = "작업 조회 실패: " + e.message;
      }
    }

    function renderItems() {
      itemsWrap.replaceChildren();
      if (!currentItems.length) return;
      const list = el("div", "pdfmd-itemlist");
      currentItems.forEach((item) => {
        const card = el("div", "pdfmd-item");
        const title = el("div", "pdfmd-item-title", item.name + " (" + item.page_count + "쪽)");
        card.appendChild(title);
        const status = el("div", "pdfmd-item-status", "상태: " + item.status + (item.error_code ? " (" + item.error_code + ")" : ""));
        card.appendChild(status);

        const actions = el("div", "pdfmd-item-actions");
        const runBtn = el("button", "pdfmd-btn", "변환 실행");
        runBtn.type = "button";
        runBtn.disabled = item.has_markdown;
        runBtn.addEventListener("click", async () => {
          runBtn.disabled = true;
          uploadStatus.textContent = item.name + " 변환 중...";
          try {
            await api("/api/document-conversions/items/" + item.id + "/run", { method: "POST" });
            uploadStatus.textContent = item.name + " 변환 완료";
            await loadJob();
          } catch (e) {
            uploadStatus.textContent = item.name + " 변환 실패: " + e.message;
            await loadJob();
          }
        });
        actions.appendChild(runBtn);

        if (item.has_markdown) {
          const reviewBtn = el("button", "pdfmd-btn", "검토 완료");
          reviewBtn.type = "button";
          reviewBtn.addEventListener("click", async () => {
            try {
              await api("/api/document-conversions/items/" + item.id + "/review", { method: "POST" });
              await loadJob();
            } catch (e) { uploadStatus.textContent = "검토 실패: " + e.message; }
          });
          actions.appendChild(reviewBtn);

          const mdBtn = el("button", "pdfmd-btn", "MD 다운로드");
          mdBtn.type = "button";
          mdBtn.addEventListener("click", async () => {
            const res = await fetch("/api/document-conversions/items/" + item.id + "/markdown", { credentials: "include" });
            if (!res.ok) { uploadStatus.textContent = "다운로드 실패"; return; }
            const blob = await res.blob();
            downloadBlob(blob, (item.name.replace(/\.[^.]+$/, "") || "document") + ".md");
          });
          actions.appendChild(mdBtn);

          const origBtn = el("button", "pdfmd-btn", "원본 다운로드");
          origBtn.type = "button";
          origBtn.addEventListener("click", async () => {
            const res = await fetch("/api/document-conversions/items/" + item.id + "/original", { credentials: "include" });
            if (!res.ok) { uploadStatus.textContent = "다운로드 실패"; return; }
            const blob = await res.blob();
            downloadBlob(blob, (item.name.replace(/\.[^.]+$/, "") || "document") + ".pdf");
          });
          actions.appendChild(origBtn);

          const previewBtn = el("button", "pdfmd-btn", "비교 보기");
          previewBtn.type = "button";
          previewBtn.addEventListener("click", async () => {
            previewWrap.hidden = false;
            origFrame.src = "/api/document-conversions/items/" + item.id + "/original?display=inline";
            try {
              const res = await fetch("/api/document-conversions/items/" + item.id + "/markdown?display=inline", { credentials: "include" });
              const text = await res.text();
              mdView.textContent = text;
            } catch (e) { mdView.textContent = "미리보기 실패: " + e.message; }
          });
          actions.appendChild(previewBtn);
        }

        const delBtn = el("button", "pdfmd-btn", "삭제");
        delBtn.type = "button";
        delBtn.addEventListener("click", async () => {
          try {
            await api("/api/document-conversions/items/" + item.id, { method: "DELETE" });
            await loadJob();
          } catch (e) { uploadStatus.textContent = "삭제 실패: " + e.message; }
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
      const res = await fetch("/api/document-conversions/" + currentJobId + "/archive", { credentials: "include" });
      if (!res.ok) { uploadStatus.textContent = "ZIP 다운로드 실패"; return; }
      const blob = await res.blob();
      downloadBlob(blob, "pdf-to-markdown-" + currentJobId + ".zip");
    });

    async function loadHistory() {
      try {
        const data = await api("/api/document-conversions?limit=50");
        histList.replaceChildren();
        const jobs = data.jobs || [];
        if (!jobs.length) { histList.textContent = "이력이 없습니다."; return; }
        const ul = document.createElement("ul");
        ul.className = "pdfmd-history-list";
        jobs.forEach((job) => {
          const li = document.createElement("li");
          const btn = document.createElement("button");
          btn.type = "button";
          btn.textContent = job.id + " (" + job.status + ", " + job.item_count + "개, " + job.mode + ")";
          btn.addEventListener("click", async () => {
            setJobId(job.id);
            await loadJob();
          });
          li.appendChild(btn);
          ul.appendChild(li);
        });
        histList.appendChild(ul);
      } catch (e) {
        histList.textContent = "이력 조회 실패: " + e.message;
      }
    }

    loadHistory();
  };
})();
