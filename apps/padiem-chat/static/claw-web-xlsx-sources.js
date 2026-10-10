/* #3580 WEB FIRST: browser-selected immutable XLSX originals.
 * P01 owner intent approval is a separate server-issued pause; neither
 * this browser UI nor its status projection may grant workbook access.
 */
(() => {
  "use strict";
  const MAX_BYTES = 1048576;
  const ID = /^doc_[0-9a-f]{32}$/;
  const HASH = /^[a-f0-9]{64}$/;
  const ENDPOINT = "/api/claw/office/web-sources";
  const SELECTIONS = "/api/claw/office/web-selections";
  const SELECTION_ID = /^sel_[a-f0-9]{32}$/;
  const P01_STAGES = new Set([
    "not_requested", "request_unknown", "waiting_p01", "decision_unknown",
    "confirmed", "denied", "expired", "manual_review",
  ]);

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

  function validateP01Status(body, selected, selectionRef) {
    return Boolean(validFile(selected) && SELECTION_ID.test(selectionRef)
      && body?.ok === true
      && body.contract_version === "claw-web-xlsx-p01-status.v1"
      && body.selection_ref === selectionRef
      && body.document_id === selected.document_id
      && body.source_sha256 === selected.source_sha256
      && body.filename === selected.filename
      && body.size_bytes === selected.size_bytes
      && P01_STAGES.has(body.status)
      && typeof body.owner_decision_enabled === "boolean"
      && (body.status === "waiting_p01" || body.owner_decision_enabled === false)
      && body.processing_started === false && body.workcopy_created === false);
  }

  function validateP01Decision(body, decision, selectionRef) {
    return Boolean(body?.ok === true
      && body.contract_version === "claw-web-xlsx-p01-owner-decision.v1"
      && body.selection_ref === selectionRef
      && body.status === (decision === "approve" ? "confirmed" : "denied")
      && body.owner_intent_only === true
      && body.processing_started === false && body.workcopy_created === false);
  }

  function validateSelectionsListing(body, files) {
    if (body?.ok !== true || body.contract_version !== "claw-web-xlsx-selection.v1"
        || !Array.isArray(body.selections) || body.selections.length > 20
        || body.p01_approval_started !== false || body.processing_started !== false) return null;
    const refs = new Set();
    const out = [];
    for (const selected of body.selections) {
      if (!selected || !SELECTION_ID.test(selected.selection_ref)
          || refs.has(selected.selection_ref)
          || selected.status !== "source_selected_p01_not_started"
          || selected.p01_approval_started !== false
          || selected.processing_started !== false
          || !files.some((f) => f.document_id === selected.document_id
            && f.source_sha256 === selected.source_sha256
            && f.filename === selected.filename && f.size_bytes === selected.size_bytes)) return null;
      refs.add(selected.selection_ref);
      out.push(selected);
    }
    return out;
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
    const approvalPanel = $("clawWebXlsxP01Panel");
    const approvalSelected = $("clawWebXlsxP01Selected");
    const approvalStatus = $("clawWebXlsxP01Status");
    const approvalRefresh = $("clawWebXlsxP01Refresh");
    const approve = $("clawWebXlsxP01Approve");
    const deny = $("clawWebXlsxP01Deny");
    if (![panel, input, upload, refresh, message, list, approvalPanel,
      approvalSelected, approvalStatus, approvalRefresh, approve, deny].every(Boolean)) return null;
    // The legacy Project Files input stays text/PDF/DOCX-only. This separate
    // browser-original intake allows XLSX without changing that contract.
    input.accept = ".xlsx";

    let busy = false;
    let selectedDocumentId = null;
    let selectedSelectionRef = null;
    let selectedSource = null;
    let ownerDecisionReady = false;
    let decisionAttempted = false;
    const attemptedRefs = new Set(); // never POST twice per selection in this page lifetime
    let loaded = false;
    const report = (value) => { message.textContent = value; };
    const setBusy = (value) => {
      busy = value;
      upload.disabled = value;
      refresh.disabled = value;
      input.disabled = value;
      approvalRefresh.disabled = value || !selectedSelectionRef;
      approve.disabled = value || !ownerDecisionReady || decisionAttempted;
      deny.disabled = value || !ownerDecisionReady || decisionAttempted;
      panel.setAttribute("aria-busy", value ? "true" : "false");
    };

    const P01_MESSAGES = Object.freeze({
      not_requested: "원본 선택 완료. P01 승인 요청이 아직 시작되지 않았습니다.",
      request_unknown: "P01 승인 요청 결과가 불확실합니다. 자동 재시도하지 않습니다.",
      waiting_p01: "원본 확인 승인을 기다리고 있습니다. 승인 또는 거절을 직접 선택하세요.",
      decision_unknown: "승인 결정 전달 결과가 불확실합니다. 다시 제출하지 마세요.",
      confirmed: "원본 확인 의도가 승인되었습니다. 파일 읽기·작업 사본·PDF 처리는 시작하지 않았습니다.",
      denied: "원본 확인을 거절했습니다. 파일은 처리되지 않았습니다.",
      expired: "원본 선택 또는 승인 대기 기한이 만료됐습니다.",
      manual_review: "승인 상태를 검증할 수 없습니다. 운영 확인이 필요합니다.",
    });

    function hideDecisions() {
      ownerDecisionReady = false;
      approve.hidden = true;
      deny.hidden = true;
      approve.disabled = true;
      deny.disabled = true;
    }

    async function checkSelectedStatus() {
      if (!selectedSelectionRef || !selectedSource) return;
      const selectionRef = selectedSelectionRef;
      const source = selectedSource;
      hideDecisions();
      approvalStatus.textContent = "서버에 기록된 P01 승인 상태를 확인하고 있습니다.";
      const status = await jsonRequest(
        SELECTIONS + "/" + encodeURIComponent(selectionRef) + "/p01-status",
      );
      if (selectedSelectionRef !== selectionRef || selectedSource !== source) return;
      if (!validateP01Status(status, source, selectionRef)) {
        throw new Error("소유자별 P01 승인 상태를 확인할 수 없습니다.");
      }
      ownerDecisionReady = status.status === "waiting_p01"
        && status.owner_decision_enabled === true && !decisionAttempted;
      approve.hidden = !ownerDecisionReady;
      deny.hidden = !ownerDecisionReady;
      approve.disabled = busy || !ownerDecisionReady;
      deny.disabled = busy || !ownerDecisionReady;
      approvalStatus.textContent = P01_MESSAGES[status.status];
      if (status.status === "waiting_p01" && !status.owner_decision_enabled) {
        approvalStatus.textContent = "P01 승인 대기는 있지만 웹 승인 기능이 아직 연결되지 않았습니다.";
      }
    }

    async function showSelection(source, selectionRef) {
      if (!validFile(source) || !SELECTION_ID.test(selectionRef)) return;
      selectedDocumentId = source.document_id;
      selectedSelectionRef = selectionRef;
      selectedSource = source;
      decisionAttempted = attemptedRefs.has(selectionRef);
      approvalPanel.hidden = false;
      approvalSelected.textContent = "선택한 원본: " + source.filename;
      hideDecisions();
      try {
        await checkSelectedStatus();
      } catch (_error) {
        hideDecisions();
        approvalStatus.textContent = "승인 상태를 안전하게 확인하지 못했습니다. 상태 확인을 눌러 다시 조회하세요.";
      }
      approvalRefresh.disabled = busy;
    }

    async function refreshSelectedStatus() {
      if (busy || !selectedSelectionRef) return;
      setBusy(true);
      try {
        await checkSelectedStatus();
      } catch (_error) {
        hideDecisions();
        approvalStatus.textContent = "서버의 승인 상태를 확인하지 못했습니다. 결정을 보내지 않았습니다.";
      } finally {
        setBusy(false);
      }
    }

    async function decideP01(decision) {
      if (busy || !ownerDecisionReady || decisionAttempted
          || !selectedSelectionRef || !selectedSource
          || !["approve", "deny"].includes(decision)) return;
      // A transport timeout might be after an Engine commit. Never resend
      // automatically or allow a second click in this page instance.
      decisionAttempted = true;
      const ref = selectedSelectionRef;
      attemptedRefs.add(ref);
      hideDecisions();
      setBusy(true);
      approvalStatus.textContent = "사용자 결정을 한 번만 전송하고 있습니다.";
      try {
        const body = await jsonRequest(
          SELECTIONS + "/" + encodeURIComponent(ref) + "/p01-decision",
          {
            method: "POST",
            headers: { "Content-Type": "application/json", "Accept": "application/json" },
            body: JSON.stringify({ decision }),
          },
        );
        if (!validateP01Decision(body, decision, ref)) {
          throw new Error("결정 결과를 확인할 수 없습니다.");
        }
        approvalStatus.textContent = decision === "approve"
          ? P01_MESSAGES.confirmed : P01_MESSAGES.denied;
        report("사용자 결정은 서버에서 확인됐습니다. 원본 내용 처리는 아직 시작하지 않았습니다.");
      } catch (_error) {
        approvalStatus.textContent = "결정 전송 결과가 불확실합니다. 재전송하지 말고 상태를 조회하세요.";
        report("P01 결정 결과가 확인되지 않았습니다. 중복 승인·거절을 보내지 않습니다.");
      } finally {
        setBusy(false);
      }
      // GET is safe to repeat, POST is not. Recover the durable receipt.
      try {
        await checkSelectedStatus();
      } catch (_error) {
        hideDecisions();
      }
    }

    function render(files, selections) {
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
        const stored = selections.find((s) => s.document_id === item.document_id
          && s.source_sha256 === item.source_sha256
          && s.filename === item.filename && s.size_bytes === item.size_bytes);
        if (stored) {
          const existing = root.createElement("button");
          existing.type = "button";
          existing.textContent = "기존 선택·승인 상태";
          existing.addEventListener("click", () => {
            if (busy) return;
            void showSelection(item, stored.selection_ref);
          });
          li.appendChild(existing);
        }
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
        await showSelection(item, body.selection.selection_ref);
        report("'" + item.filename + "' 원본 선택이 서버에 저장됐습니다. 별도의 P01 승인 대기 상태가 있어야 승인·거절할 수 있습니다.");
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
        // The original-file list remains useful even if the separate owner
        // selection history is unavailable. Never invent a missing P01 pause.
        let selections = [];
        let historyAvailable = true;
        try {
          const verified = validateSelectionsListing(
            await jsonRequest(SELECTIONS), files,
          );
          if (!verified) throw new Error("소유자별 선택 기록 계약 불일치");
          selections = verified;
        } catch (_error) {
          historyAvailable = false;
        }
        render(files, selections);
        loaded = true;
        report(files.length
          ? files.length + "개 원본이 보관되어 있습니다. 처리에는 별도 P01 승인이 필요합니다."
            + (historyAvailable ? "" : " 기존 승인 이력은 현재 조회할 수 없습니다.")
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
        selectedSource = null;
        approvalPanel.hidden = true;
        hideDecisions();
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
    approvalRefresh.addEventListener("click", () => void refreshSelectedStatus());
    approve.addEventListener("click", () => void decideP01("approve"));
    deny.addEventListener("click", () => void decideP01("deny"));
    panel.addEventListener("toggle", () => {
      if (panel.open && !loaded) void reload();
    });
    return { getState: () => ({
      busy, loaded, selectedDocumentId, selectedSelectionRef,
      p01Approved: false, ownerDecisionReady, decisionAttempted,
    }) };
  }

  const api = Object.freeze({
    validFile, validateListing, validateSelection,
    validateSelectionsListing, validateP01Status, validateP01Decision, init,
  });
  if (typeof module === "object" && module.exports) module.exports = api;
  if (typeof window === "object") window.PadiemClawWebXlsxSources = api;
  if (typeof document === "object") init(document);
})();
