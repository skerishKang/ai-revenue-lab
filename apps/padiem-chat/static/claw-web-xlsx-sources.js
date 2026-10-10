/* #3580 WEB FIRST: explicit, browser-chosen immutable XLSX originals.
 * No local-PC path, P01 approval, model, PDF processing or Drive WRITE.
 */
(() => {
  "use strict";
  const MAX_BYTES = 1048576;
  const ID = /^doc_[0-9a-f]{32}$/;
  const HASH = /^[a-f0-9]{64}$/;
  const ENDPOINT = "/api/claw/office/web-sources";
  const SELECTIONS = "/api/claw/office/web-selections";

  function validFile(file) {
    return Boolean(file && typeof file.document_id === "string" && ID.test(file.document_id)
      && typeof file.filename === "string" && file.filename.length > 0
      && file.filename.length <= 155 && file.filename.toLowerCase().endsWith(".xlsx")
      && !/[\\/:<>\x00-\x1f]/.test(file.filename)
      && Number.isSafeInteger(file.size_bytes) && file.size_bytes > 0
      && file.size_bytes <= MAX_BYTES
      && HASH.test(file.source_sha256)
      && file.original_immutable === true && file.processing_authorized === false);
  }

  function validateSelection(body, source) {
    const selected = body?.selection;
    return Boolean(source && validFile(source)
      && body?.ok === true
      && body.contract_version === "claw-web-xlsx-selection.v1"
      && body.p01_approval_started === false
      && body.processing_started === false
      && body.workcopy_created === false
      && body.drive_uploaded === false
      && selected && /^sel_[a-f0-9]{32}$/.test(selected.selection_ref)
      && selected.document_id === source.document_id
      && selected.source_sha256 === source.source_sha256
      && selected.size_bytes === source.size_bytes
      && selected.filename === source.filename
      && selected.status === "source_selected_p01_not_started"
      && selected.p01_approval_started === false
      && selected.processing_started === false);
  }

  function validateListing(body) {
    if (!body || body.ok !== true || body.contract_version !== "claw-web-xlsx-source.v1"
        || body.source !== "browser_upload" || body.read_authorized_for_processing !== false
        || body.requires_p01_for_processing !== true || !Array.isArray(body.files)
        || body.files.length > 40 || !body.files.every(validFile)) return null;
    if (new Set(body.files.map((file) => file.document_id)).size !== body.files.length) return null;
    return body.files;
  }

  async function jsonRequest(url, options) {
    const res = await fetch(url, {
      credentials: "same-origin", cache: "no-store", ...options,
    });
    const data = await res.json().catch(() => null);
    if (!res.ok || !data || data.ok !== true) {
      const reason = data?.error?.code;
      throw new Error(reason === "unauthorized" ? "로그인한 후 다시 시도해 주세요."
        : reason === "web_xlsx_store_unavailable" ? "웹 파일 보관 기능이 아직 연결되지 않았습니다."
        : reason === "web_xlsx_too_large" ? "XLSX 파일은 1 MiB 이하여야 합니다."
        : reason === "invalid_web_xlsx_file" ? "안전하게 확인할 수 있는 XLSX 파일만 보관할 수 있습니다."
        : "웹 파일 요청에 실패했습니다. 연결과 파일 상태를 확인해 주세요.");
    }
    return data;
  }

  function bytesBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    const blockSize = 32768;
    const parts = [];
    for (let i = 0; i < bytes.length; i += blockSize) {
      let str = "";
      const end = Math.min(i + blockSize, bytes.length);
      for (let j = i; j < end; j++) str += String.fromCharCode(bytes[j]);
      parts.push(str);
    }
    return btoa(parts.join(""));
  }

  function init(root = document) {
    const $ = (id) => root.getElementById(id);
    const panel = $("clawWebOfficeDetails");
    const input = $("clawWebXlsxInput");
    const upload = $("clawWebXlsxSave");
    const refresh = $("clawWebXlsxRefresh");
    const message = $("clawWebXlsxNotice");
    const list = $("clawWebXlsxList");
    if (![panel, input, upload, refresh, message, list].every(Boolean)) return null;
    // The legacy Project Files input stays text/PDF/DOCX-only. This separate
    // browser-original intake allows XLSX without changing that contract.
    input.accept = ".xlsx";

    let busy = false;
    let selectedDocumentId = null;
    let selectedSelectionRef = null;
    let loaded = false;
    const report = (value) => { message.textContent = value; };
    const setBusy = (value) => {
      busy = value;
      upload.disabled = value;
      refresh.disabled = value;
      input.disabled = value;
      panel.setAttribute("aria-busy", value ? "true" : "false");
    };

    function render(files) {
      list.replaceChildren();
      for (const item of files) {
        const li = root.createElement("li");
        const select = root.createElement("button");
        select.type = "button";
        select.textContent = "선택: " + item.filename + " (" + Math.ceil(item.size_bytes / 1024) + "KB)";
        select.addEventListener("click", () => void selectSource(item));
        const link = root.createElement("a");
        link.textContent = "원본 다운로드";
        link.href = ENDPOINT + "/" + encodeURIComponent(item.document_id) + "/download";
        li.append(select, link);
        list.appendChild(li);
      }
    }

    async function selectSource(item) {
      if (busy || !validFile(item)) return;
      setBusy(true);
      report("원본의 소유권과 정확한 파일 지문을 확인하고 있습니다.");
      try {
        const body = await jsonRequest(SELECTIONS, {
          method: "POST",
          headers: { "Content-Type": "application/json", "Accept": "application/json" },
          body: JSON.stringify({ document_id: item.document_id }),
        });
        if (!validateSelection(body, item)) {
          throw new Error("파일 선택 기록을 검증할 수 없습니다.");
        }
        selectedDocumentId = body.selection.document_id;
        selectedSelectionRef = body.selection.selection_ref;
        report("'" + item.filename + "' 원본 선택이 서버에 저장됐습니다. P01 승인은 아직 시작되지 않았으며, 읽기·수정·변환도 진행되지 않았습니다.");
      } catch (error) {
        report(error.message);
      } finally {
        setBusy(false);
      }
    }

    async function reload() {
      if (busy) return;
      setBusy(true);
      try {
        const files = validateListing(await jsonRequest(ENDPOINT));
        if (!files) throw new Error("웹 파일 목록 형식을 확인할 수 없습니다.");
        render(files);
        loaded = true;
        report(files.length
          ? files.length + "개 원본이 보관되어 있습니다. 처리에는 별도 P01 승인이 필요합니다."
          : "보관된 Excel 원본이 없습니다. 파일을 직접 선택해 보관할 수 있습니다.");
      } catch (error) {
        list.replaceChildren();
        loaded = false;
        report(error.message);
      } finally {
        setBusy(false);
      }
    }

    async function save() {
      if (busy) return;
      const file = input.files?.[0];
      if (!file || !file.name.toLowerCase().endsWith(".xlsx")) {
        report("XLSX 파일 하나를 먼저 선택해 주세요.");
        return;
      }
      if (!file.size || file.size > MAX_BYTES) {
        report("XLSX 파일은 1 MiB 이하여야 합니다.");
        return;
      }
      setBusy(true);
      report("웹 저장소에 선택한 원본을 보관하고 있습니다.");
      try {
        const buffer = await file.arrayBuffer();
        if (buffer.byteLength !== file.size) throw new Error("파일 크기가 변경되어 보관하지 않았습니다.");
        const body = await jsonRequest(ENDPOINT, {
          method: "POST",
          headers: { "Content-Type": "application/json", "Accept": "application/json" },
          body: JSON.stringify({ name: file.name, base64: bytesBase64(buffer) }),
        });
        if (body.processing_started !== false || body.p01_approved !== false
            || body.drive_uploaded !== false || !validFile(body.file)) {
          throw new Error("웹 원본 저장 결과를 확인할 수 없습니다.");
        }
        input.value = "";
        selectedDocumentId = null;
        selectedSelectionRef = null;
        report("원본 XLSX 보관 완료. 수정·PDF 변환은 시작되지 않았으며 별도 승인이 필요합니다.");
      } catch (error) {
        report(error.message);
      } finally {
        setBusy(false);
      }
      await reload();
    }

    upload.addEventListener("click", () => void save());
    refresh.addEventListener("click", () => void reload());
    panel.addEventListener("toggle", () => {
      if (panel.open && !loaded) void reload();
    });
    return { getState: () => ({
      busy, loaded, selectedDocumentId, selectedSelectionRef, p01Approved: false,
    }) };
  }

  const api = Object.freeze({ validFile, validateListing, validateSelection, init });
  if (typeof module === "object" && module.exports) module.exports = api;
  if (typeof window === "object") window.PadiemClawWebXlsxSources = api;
  if (typeof document === "object") init(document);
})();
