/* Hark #3580 — owner-selected local Office candidate UI.
 * No local paths, approval tokens, or device credentials ever enter the page.
 * The existing P01 Engine approval decision API is the ONLY decision sender.
 */
(() => {
  "use strict";

  const TOKEN = /^[a-f0-9]{64}$/;
  const RUN = /^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,127}$/;
  function parseCandidates(body, expectedRun) {
    if (!body || body.ok !== true || body.run_id !== expectedRun
        || body.contract_version !== "hark-office-owner-chooser.v1"
        || body.metadata_only !== true || body.read_authorized !== false
        || body.requires_engine_approval !== true
        || !Array.isArray(body.candidates) || body.candidates.length > 40) return null;
    const seen = new Set();
    const candidates = [];
    for (const row of body.candidates) {
      if (!row || typeof row.filename !== "string" || row.filename.length > 160
          || /[\\/:\x00-\x1f]/.test(row.filename)
          || !["xls", "xlsx"].includes(row.kind)
          || !row.filename.toLowerCase().endsWith("." + row.kind)
          || !Number.isSafeInteger(row.size_bytes) || row.size_bytes < 1 || row.size_bytes > 1048576
          || typeof row.candidate_ref !== "string" || !TOKEN.test(row.candidate_ref)
          || seen.has(row.candidate_ref)) return null;
      seen.add(row.candidate_ref);
      candidates.push({
        filename: row.filename, kind: row.kind,
        size_bytes: row.size_bytes, candidate_ref: row.candidate_ref,
      });
    }
    return candidates;
  }

  async function readJson(url, init) {
    const response = await fetch(url, { credentials: "same-origin", cache: "no-store", ...init });
    const body = await response.json().catch(() => null);
    if (!response.ok || !body || body.ok !== true) {
      const code = body?.error?.code;
      throw new Error(
        code === "office_chooser_unconfigured"
          ? "PC 파일 선택 기능이 아직 연결되지 않았습니다."
          : code === "unauthorized"
            ? "로그인 후 다시 시도해 주세요."
            : "승인된 파일 요청을 확인하지 못했습니다."
      );
    }
    return body;
  }

  function initChooser(documentRoot = document) {
    const $ = (id) => documentRoot.getElementById(id);
    const panel = $("clawOfficeChooser");
    const find = $("clawOfficeFind");
    const notice = $("clawOfficeNotice");
    const list = $("clawOfficeCandidates");
    const group = $("clawOfficeDecision");
    const label = $("clawOfficeDecisionLabel");
    const approve = $("clawOfficeApprove");
    const deny = $("clawOfficeDeny");
    const resultPanel = $("clawOfficeResult");
    const checkResult = $("clawOfficeCheckResult");
    const pdfPreview = $("clawOfficePreview");
    if (![panel, find, notice, list, group, label, approve, deny].every(Boolean)) return null;
    let active = null;
    let pending = null;
    let busy = false;
    const setBusy = (value) => {
      busy = value;
      for (const button of [find, approve, deny, checkResult]) if (button) button.disabled = value;
    };
    const setMessage = (text) => { notice.textContent = text; };

    function currentRun() {
      const model = window.__padiemClawLocalHandoff?.getViewModel?.();
      const run = model?.identity?.runId;
      if (model?.device?.usable !== true || model.requiresLocalAccess !== true
          || typeof run !== "string" || !RUN.test(run)) return null;
      return run;
    }

    find.addEventListener("click", async () => {
      if (busy) return;
      active = null;
      pending = null;
      group.hidden = true;
      if (resultPanel) resultPanel.hidden = true;
      if (pdfPreview) pdfPreview.hidden = true;
      list.replaceChildren();
      const runId = currentRun();
      if (!runId) {
        setMessage("먼저 이 작업에 연결된 컴퓨터와 실행 정보를 확인해 주세요.");
        return;
      }
      setBusy(true);
      setMessage("승인된 견적서 후보를 조회하고 있습니다.");
      try {
        const body = await readJson("/api/claw/office/candidates?run_id=" + encodeURIComponent(runId));
        const candidates = parseCandidates(body, runId);
        if (!candidates) throw new Error("파일 목록 응답을 검증할 수 없습니다.");
        active = { runId, candidates };
        for (const row of candidates) {
          const item = documentRoot.createElement("li");
          const button = documentRoot.createElement("button");
          button.type = "button";
          button.className = "claw-office-choice";
          button.textContent = row.filename + " (" + row.kind.toUpperCase() + " · " +
            Math.ceil(row.size_bytes / 1024) + "KB)";
          button.addEventListener("click", () => void choose(row.candidate_ref));
          item.appendChild(button);
          list.appendChild(item);
        }
        setMessage(candidates.length
          ? (candidates.length + "개 발견. 읽을 파일을 선택하면 별도의 승인을 요청합니다.")
          : "승인된 폴더에 지원하는 견적서가 없습니다.");
      } catch (error) {
        setMessage(error.message);
      } finally {
        setBusy(false);
      }
    });

    async function choose(candidateRef) {
      if (busy || !active || !TOKEN.test(candidateRef)
          || !active.candidates.some((c) => c.candidate_ref === candidateRef)
          || currentRun() !== active.runId) return;
      setBusy(true);
      group.hidden = true;
      setMessage("선택한 파일의 P01 승인 요청을 확인하고 있습니다.");
      try {
        const body = await readJson("/api/claw/office/candidates/select", {
          method: "POST",
          headers: { "Content-Type": "application/json", "Accept": "application/json" },
          body: JSON.stringify({ run_id: active.runId, candidate_ref: candidateRef }),
        });
        if (body.run_id !== active.runId || body.status !== "awaiting_approval"
            || body.approval_required !== true || body.processing_started !== false
            || body.file_read_authorized !== false || typeof body.engine_run_id !== "string"
            || !RUN.test(body.engine_run_id)) throw new Error("P01 승인 대기 상태를 확인하지 못했습니다.");
        pending = { runId: active.runId, candidateRef, engineRunId: body.engine_run_id };
        const selected = active.candidates.find((c) => c.candidate_ref === candidateRef);
        label.textContent = "선택 파일: " + selected.filename + " · 파일 읽기를 승인하시겠습니까?";
        group.hidden = false;
        setMessage("승인 전에는 파일을 읽거나 실행하지 않습니다.");
      } catch (error) {
        setMessage(error.message);
      } finally {
        setBusy(false);
      }
    }

    async function decide(decision) {
      if (busy || !pending || currentRun() !== pending.runId) return;
      setBusy(true);
      const submitted = pending;
      setMessage("P01 Engine 승인 결과를 확인하고 있습니다.");
      try {
        const body = await readJson("/api/claw/approvals/decision", {
          method: "POST",
          headers: { "Content-Type": "application/json", "Accept": "application/json" },
          body: JSON.stringify({ run_id: submitted.engineRunId, decision }),
        });
        if (body.result?.run_id !== submitted.engineRunId) {
          throw new Error("다른 실행의 승인 결과는 적용할 수 없습니다.");
        }
        pending = null;
        group.hidden = true;
        if (resultPanel) resultPanel.hidden = decision !== "approve";
        if (pdfPreview) pdfPreview.hidden = true;
        setMessage(decision === "deny"
          ? "승인이 거절되었습니다. 파일을 읽지 않았습니다."
          : "Engine 승인 처리가 완료됐습니다. 실제 파일 처리 결과는 실행 이력에서 확인해 주세요.");
      } catch (error) {
        setMessage(error.message);
      } finally {
        setBusy(false);
      }
    }
    if (checkResult) checkResult.addEventListener("click", async () => {
      if (busy || !active || currentRun() !== active.runId) return;
      setBusy(true);
      if (pdfPreview) pdfPreview.hidden = true;
      setMessage("승인된 PC 작업의 완료 여부를 확인합니다.");
      try {
        const body = await readJson("/api/claw/runs/" + encodeURIComponent(active.runId) + "/local-result", {
          method: "POST", headers: { "Content-Type": "application/json", "Accept": "application/json" },
          body: JSON.stringify({}),
        });
        if (body.projection?.runId !== active.runId || body.projection?.status !== "completed"
            || body.projection?.appended !== true) {
          setMessage("파일 작업이 아직 완료되지 않았거나 확인할 수 없습니다.");
          return;
        }
        setMessage("실행 완료를 확인했습니다. PDF가 준비됐다면 미리보기를 열 수 있습니다.");
        if (pdfPreview) {
          pdfPreview.href = "/api/claw/office/runs/" + encodeURIComponent(active.runId) + "/pdf";
          pdfPreview.hidden = false;
        }
      } catch (error) {
        setMessage(error.message);
      } finally {
        setBusy(false);
      }
    });
    approve.addEventListener("click", () => void decide("approve"));
    deny.addEventListener("click", () => void decide("deny"));
    return { getState: () => ({ busy, hasCandidates: Boolean(active), approvalPending: Boolean(pending) }) };
  }

  const api = Object.freeze({ parseCandidates, initChooser });
  if (typeof module === "object" && module.exports) module.exports = api;
  if (typeof window === "object") {
    window.PadiemHarkOfficeChooser = api;
    if (typeof document === "object") initChooser(document);
  }
})();
